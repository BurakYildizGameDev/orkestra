"""Batches: many tasks, their dependencies and safe parallelism (Mimari §12, Faz 7a).

A batch file is ``{tasks: [TaskSpec, ...], parallel: N}`` (YAML, or JSON for ``.json``).

- ``load_batch``: every task is validated as a task file would be; duplicate ids, unknown or
  cyclic ``depends_on`` are usage errors (exit code 2) before anything runs.
- ``plan_batch``: the run order (dependencies first, then the order of the file) and, for
  ``edit`` tasks whose context files overlap, an extra "after" order with a warning: they
  run one after the other, each in its own worktree from the user's files, so applying both
  may still conflict.
- ``run_batch``: at most ``parallel`` tasks at a time; requests to a provider are limited by
  its ``concurrency`` across all tasks (``runner.ProviderSlots``). A task whose dependency did
  not end ``ok`` is ``skipped``; ``fail_fast`` starts nothing after the first failure. A task
  that raises becomes an ``error`` item: one task never brings the batch down.

- ``estimate_batch`` (Faz 7b, Mimari §19): every task's first request on its first candidate,
  priced like a budget reservation; nothing is sent. Before a real run it is compared with
  ``estimate.confirm_above_usd`` (the CLI asks, or needs ``--yes-cost``).

A dependency orders tasks; it does not hand its unapplied change to the next task. A task
that needs another one's change belongs in a later batch, after ``apply``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orkestra.config.schema import CliAgentProvider, Config, Provider
from orkestra.envelope import (
    BatchEnvelope,
    BatchEstimate,
    BatchItem,
    BatchTotals,
    EstimateItem,
    EstimateTotals,
)
from orkestra.errors import ExitCode, InternalError, OrkestraError, UsageError
from orkestra.i18n import t
from orkestra.state import db
from orkestra.tasks import runner
from orkestra.tasks.context import glob_files
from orkestra.tasks.spec import TaskSpec, parse_task, read_document

DEFAULT_PARALLEL = 4
BATCH_KEYS = frozenset({"tasks", "parallel"})
ERROR_CHARS = 300
SHOWN_FILES = 3  # files named in the "same files" warning


@dataclass(frozen=True)
class BatchSpec:
    tasks: tuple[TaskSpec, ...]
    parallel: int | None
    source: str
    order: tuple[str, ...] = ()  # task ids, dependencies first (``load_batch`` checks it once)


@dataclass(frozen=True)
class BatchPlan:
    order: tuple[str, ...]  # task ids, dependencies first
    depends: Mapping[str, frozenset[str]]  # depends_on: skipped when one did not end ok
    after: Mapping[str, frozenset[str]]  # edit tasks on the same files: only waits
    warnings: tuple[str, ...] = ()


# --- loading ---------------------------------------------------------------------------


def _usage(key: str, **params: object) -> UsageError:
    return UsageError(t(key, **params))


def _parallel(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _usage("batch.error.parallel", value=value)
    return value


def load_batch(path: Path) -> BatchSpec:
    """Read and check a batch file. Problems raise ``UsageError`` (exit code 2)."""
    data = read_document(path)
    if not isinstance(data, dict):
        raise _usage("config.error.not_mapping", path=path)
    unknown = sorted(set(data) - BATCH_KEYS)
    if unknown:
        raise _usage("batch.error.unknown_key", path=path, keys=", ".join(unknown))
    items = data.get("tasks")
    if not isinstance(items, list) or not items:
        raise _usage("batch.error.no_tasks", path=path)
    tasks: list[TaskSpec] = []
    for index, item in enumerate(items):
        source = f"{path} tasks[{index}]"
        if not isinstance(item, dict):
            raise _usage("config.error.not_mapping", path=source)
        tasks.append(parse_task(item, source=source))
    _check_ids(tasks)
    order = _order(tasks)  # raises on a cycle
    return BatchSpec(tuple(tasks), _parallel(data.get("parallel")), str(path), order)


def _check_ids(tasks: Sequence[TaskSpec]) -> None:
    seen: set[str] = set()
    for task in tasks:
        if task.id in seen:
            raise _usage("batch.error.duplicate", id=task.id)
        seen.add(task.id)
    for task in tasks:
        for dep in task.depends_on:
            if dep not in seen:
                raise _usage("batch.error.unknown_dependency", id=task.id, dep=dep)


def _order(tasks: Sequence[TaskSpec]) -> tuple[str, ...]:
    """Topological order, ties broken by the order of the file; a cycle is a usage error."""
    position = {task.id: index for index, task in enumerate(tasks)}
    waiting = {task.id: set(task.depends_on) for task in tasks}
    order: list[str] = []
    while True:
        ready = sorted((tid for tid, deps in waiting.items() if not deps), key=position.__getitem__)
        if not ready:
            break
        current = ready[0]
        order.append(current)
        del waiting[current]
        for deps in waiting.values():
            deps.discard(current)
    if waiting:
        raise UsageError(t("batch.error.cycle"), details=_cycle(waiting, position))
    return tuple(order)


def _cycle(waiting: dict[str, set[str]], position: Mapping[str, int]) -> list[str]:
    """The tasks on a cycle: what is left after also dropping tasks nothing left needs."""
    left = dict(waiting)
    while True:
        needed = {dep for deps in left.values() for dep in deps}
        loose = [tid for tid in left if tid not in needed]
        if not loose:
            break
        for tid in loose:
            del left[tid]
    return [
        t("batch.error.cycle_item", id=tid, deps=", ".join(sorted(deps, key=position.__getitem__)))
        for tid, deps in sorted(left.items(), key=lambda item: position[item[0]])
    ]


# --- planning --------------------------------------------------------------------------


def _edit_files(task: TaskSpec, cwd: Path, ignore_file: str | None) -> frozenset[Path]:
    """The context files of an edit task, resolved; globs expand as in ``orkestra run``
    (``.git/``, ``.gitignore`` and the ignore file are left out, bad patterns are usage
    errors)."""
    if task.kind != "edit":
        return frozenset()
    base = task.base_dir(cwd)
    files = {(base / name).resolve() for name in task.context.files}
    files.update(p.resolve() for p in glob_files(task.context.globs, base, ignore_file))
    return frozenset(p for p in files if not p.is_dir())


def plan_batch(spec: BatchSpec, *, cwd: Path, ignore_file: str | None = None) -> BatchPlan:
    """``ignore_file``: ``security.ignore_file``, so overlaps use the files a run would use."""
    order = spec.order or _order(spec.tasks)
    tasks = {task.id: task for task in spec.tasks}
    files = {tid: _edit_files(tasks[tid], cwd, ignore_file) for tid in order}
    after: dict[str, set[str]] = {tid: set() for tid in order}
    warnings: list[str] = []
    for later_index, later in enumerate(order):
        for earlier in order[:later_index]:
            shared = files[earlier] & files[later]
            if not shared:
                continue
            after[later].add(earlier)
            names = ", ".join(sorted(p.name for p in shared)[:SHOWN_FILES])
            warnings.append(t("batch.warning.same_files", first=earlier, second=later, files=names))
    return BatchPlan(
        order,
        {tid: frozenset(tasks[tid].depends_on) for tid in order},
        {tid: frozenset(deps) for tid, deps in after.items()},
        tuple(warnings),
    )


# --- running ---------------------------------------------------------------------------


@dataclass
class _State:
    results: dict[str, BatchItem]
    done: dict[str, asyncio.Event]
    stopped: bool = False


def _item_from_outcome(task: TaskSpec, outcome: runner.TaskOutcome) -> BatchItem:
    env = outcome.envelope
    return BatchItem(
        task_id=task.id, status=env.status, exit_code=outcome.exit_code, run_id=env.run_id,
        envelope=env, error=env.error,
    )  # fmt: skip


async def _run_one(
    task: TaskSpec,
    config: Config,
    options: runner.RunOptions,
    *,
    cwd: Path | None,
    slots: runner.ProviderSlots,
    batch_id: str,
    warnings: list[str],
) -> BatchItem:
    started: list[str] = []  # the run id once the run is recorded, even if it crashes later
    try:
        outcome = await runner.run_task(
            task, config, options, cwd=cwd, slots=slots, batch_id=batch_id,
            on_start=started.append,
        )  # fmt: skip
    except OrkestraError as exc:  # no provider, consent, a bad context file ...
        return BatchItem(task_id=task.id, status="error", exit_code=int(exc.exit_code),
                         run_id=started[0] if started else None, error=_detail(exc))  # fmt: skip
    except Exception as exc:  # a bug in one task must not bring the batch down
        detail = f"{type(exc).__name__}: {exc}"[:ERROR_CHARS]
        return BatchItem(task_id=task.id, status="error", exit_code=int(ExitCode.INTERNAL),
                         run_id=started[0] if started else None, error=detail)  # fmt: skip
    warnings.extend(f"{task.id}: {w}" for w in outcome.warnings)
    return _item_from_outcome(task, outcome)


def _detail(exc: OrkestraError) -> str:
    """An error and its details on one line, cut to ``ERROR_CHARS``."""
    return "; ".join([exc.message, *exc.details])[:ERROR_CHARS]


def _skipped(task_id: str, key: str, **params: object) -> BatchItem:
    return BatchItem(
        task_id=task_id, status="skipped", exit_code=int(ExitCode.TASK_FAILED),
        error=t(key, **params),
    )  # fmt: skip


def _totals(items: Sequence[BatchItem]) -> BatchTotals:
    counts = {status: sum(1 for i in items if i.status == status)
              for status in ("ok", "failed", "escalate", "error", "skipped")}  # fmt: skip
    costs = [
        i.envelope.usage.cost_usd
        for i in items
        if i.envelope is not None and i.envelope.usage.cost_usd is not None
    ]
    return BatchTotals(**counts, cost_usd=round(sum(costs), 6) if costs else None)


def run_warnings(document: BatchEnvelope, plan: BatchPlan) -> list[str]:
    """Warnings the tasks raised while running (the plan's own were shown before)."""
    return document.warnings[len(plan.warnings) :]


def new_batch_id() -> str:
    return f"b-{runner.new_run_id()}"


# --- cost estimate (Faz 7b, Mimari §19) ------------------------------------------------


def _estimate_item(task: TaskSpec, est: runner.Estimate) -> EstimateItem:
    if est.candidate is None:
        if est.error is None:  # an estimate without a candidate always says why
            raise InternalError("estimate without a candidate and without an error")
        return EstimateItem(
            task_id=task.id, exit_code=int(est.error.exit_code), error=_detail(est.error)
        )
    return EstimateItem(
        task_id=task.id, provider=est.candidate.provider, model=est.candidate.model.id,
        tier=est.candidate.tier, prompt_tokens=est.prompt_tokens,
        max_output_tokens=est.max_output_tokens,
        cost_usd=None if est.cost_usd is None else round(est.cost_usd, 6),
        agent=isinstance(est.candidate.config, CliAgentProvider),
    )  # fmt: skip


def _estimate_totals(items: Sequence[EstimateItem]) -> EstimateTotals:
    runnable = [i for i in items if i.error is None]
    unpriced = [i for i in runnable if i.cost_usd is None]
    return EstimateTotals(
        tasks=len(items),
        tokens=sum(i.prompt_tokens + (i.max_output_tokens or 0) for i in runnable),
        cost_usd=round(sum(i.cost_usd for i in runnable if i.cost_usd is not None), 6),
        unpriced=len(unpriced),
        unpriced_remote=sum(1 for i in unpriced if not i.agent),
        cannot_run=len(items) - len(runnable),
    )


async def estimate_batch(
    spec: BatchSpec,
    config: Config,
    options: runner.RunOptions | None = None,
    *,
    cwd: Path | None = None,
    fetch_prices: bool = False,
) -> BatchEstimate:
    """Every task's first request on its first candidate; nothing is sent to a worker.

    ``fetch_prices``: refresh price lists first, as the run itself would (before a real
    run); ``--estimate`` alone uses the cached ones. A task that cannot run is an item with
    its error and exit code, the others are still estimated.

    Confirmation is needed above ``estimate.confirm_above_usd``, and also when a task goes
    to a paid (remote) model whose price is not known: its cost cannot be checked, so it
    must not slip under the threshold as $0. Code agents use the user's own quota, not USD.
    """
    options = options or runner.RunOptions()
    lock = asyncio.Lock()  # one price list fetch for the whole batch
    items: list[EstimateItem] = []
    warnings: list[str] = []
    with closing(db.connect()) as conn:
        for task in spec.tasks:
            try:
                est = await runner.estimate_task(
                    task, config, options, cwd=cwd, conn=conn, fetch_prices=fetch_prices,
                    price_lock=lock,
                )  # fmt: skip
            except OrkestraError as exc:
                items.append(
                    EstimateItem(task_id=task.id, exit_code=int(exc.exit_code), error=_detail(exc))
                )
                continue
            warnings.extend(f"{task.id}: {w}" for w in est.warnings)
            items.append(_estimate_item(task, est))
    totals = _estimate_totals(items)
    limit = config.estimate.confirm_above_usd
    above = limit is not None and (totals.cost_usd > limit or totals.unpriced_remote > 0)
    return BatchEstimate(
        results=items, totals=totals, confirm_above_usd=limit, needs_confirmation=above,
        warnings=warnings,
    )  # fmt: skip


def estimate_exit_code(document: BatchEstimate) -> int:
    """``--estimate``: 0, or the exit code of the first task that cannot run."""
    return next((i.exit_code for i in document.results if i.error is not None), 0)


def _may_cost(provider: Provider) -> bool:
    if isinstance(provider, CliAgentProvider) or not provider.enabled:
        return False  # agents: the user's own quota
    return not provider.local or any(m.price_per_mtok for m in provider.models)


def checks_cost(config: Config) -> bool:
    """Estimate a batch before it runs only if there is a threshold and a provider that can
    cost money: a setup with only local models without a price (and agents) skips the
    extra preparation of every task."""
    if config.estimate.confirm_above_usd is None:
        return False
    return any(_may_cost(p) for p in config.providers.values())


async def run_batch(
    spec: BatchSpec,
    plan: BatchPlan,
    config: Config,
    options: runner.RunOptions | None = None,
    *,
    parallel: int = DEFAULT_PARALLEL,
    fail_fast: bool = False,
    cwd: Path | None = None,
    on_done: Callable[[BatchItem], Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[BatchEnvelope, int]:
    """Run the batch; the document and the exit code (0: every task ok, else 1)."""
    started = clock()
    batch_id = new_batch_id()
    options = options or runner.RunOptions()
    tasks = {task.id: task for task in spec.tasks}
    slots = runner.ProviderSlots(config)
    gate = asyncio.Semaphore(parallel)
    state = _State(results={}, done={tid: asyncio.Event() for tid in plan.order})
    warnings: list[str] = list(plan.warnings)

    async def one(task_id: str) -> None:
        try:
            for dep in plan.depends[task_id] | plan.after[task_id]:
                await state.done[dep].wait()
            state.results[task_id] = await _decide(task_id)
            if on_done is not None:
                on_done(state.results[task_id])
        finally:
            state.done[task_id].set()

    async def _decide(task_id: str) -> BatchItem:
        failed = [d for d in sorted(plan.depends[task_id]) if state.results[d].status != "ok"]
        if failed:
            return _skipped(task_id, "batch.skipped.dependency", deps=", ".join(failed))
        async with gate:
            if state.stopped:
                return _skipped(task_id, "batch.skipped.fail_fast")
            item = await _run_one(
                tasks[task_id], config, options, cwd=cwd, slots=slots, batch_id=batch_id,
                warnings=warnings,
            )  # fmt: skip
        if fail_fast and item.status != "ok":
            state.stopped = True
        return item

    await asyncio.gather(*(one(tid) for tid in plan.order))
    items = [state.results[task.id] for task in spec.tasks]  # in the order of the file
    document = BatchEnvelope(
        batch_id=batch_id, results=items, totals=_totals(items), warnings=warnings,
        duration_s=round(clock() - started, 3),
    )  # fmt: skip
    code = int(ExitCode.OK) if all(i.status == "ok" for i in items) else int(ExitCode.TASK_FAILED)
    return document, code
