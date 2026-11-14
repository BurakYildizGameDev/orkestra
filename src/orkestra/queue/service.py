"""``queue run``: work through the queue under the lock (Faz 12a, Mimari §21, D-072).

Items run one after another. Before each new item the loop stops when ``--until`` has passed
or ``--max-cost-usd`` is spent; the item that is running always finishes. Items a killed run
left ``running`` go back to ``pending`` first. One broken item never stops the others.

``execute`` runs one item and is injected in tests; ``execute_item`` is the real one: it
works in the directory the item was added from, with that directory's project config, as if
``orkestra run``/``batch`` had been typed there.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from orkestra.config import loader
from orkestra.config.schema import Config
from orkestra.errors import OrkestraError, QueueBusy, UsageError
from orkestra.i18n import t
from orkestra.notify import notify
from orkestra.queue import store
from orkestra.state import db
from orkestra.tasks import batch, runner, spec

ItemStatus = Literal["done", "failed", "skipped"]
Stop = Literal["until", "cost"]
_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@dataclass(frozen=True)
class ItemResult:
    status: ItemStatus
    result_ref: str | None = None
    cost_usd: float = 0.0
    note: str | None = None
    warnings: tuple[str, ...] = ()


Execute = Callable[[store.QueueItem, "float | None"], ItemResult]
OnItem = Callable[[store.QueueItem, ItemResult], object]


@dataclass
class QueueReport:
    done: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)
    stopped: Stop | None = None
    spent_usd: float = 0.0
    recovered: int = 0
    results: list[tuple[store.QueueItem, ItemResult]] = field(default_factory=list)

    @property
    def finished(self) -> int:
        return len(self.done) + len(self.failed)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


def deadline(until: str, now: datetime) -> datetime:
    """The next moment the clock shows ``HH:MM`` (tomorrow when it is that time or later)."""
    match = _HHMM.match(until.strip())
    if match is None:
        raise UsageError(t("queue.error.until", value=until))
    moment = now.replace(hour=int(match[1]), minute=int(match[2]), second=0, microsecond=0)
    return moment if moment > now else moment + timedelta(days=1)


def run_queue(
    conn: sqlite3.Connection,
    *,
    execute: Execute,
    until: str | None = None,
    max_cost_usd: float | None = None,
    now: db.Clock = db.local_now,
    alive: store.Alive = store.process_alive,
    owner: store.Owner | None = None,
    on_item: OnItem | None = None,
) -> QueueReport:
    started = now()
    stop_at = deadline(until, started) if until is not None else None
    me = owner or store.current_owner()
    store.acquire_lock(conn, started, owner=me, alive=alive)
    report = QueueReport()
    try:
        report.recovered = store.recover(conn)
        last = 0
        while (item := store.next_pending(conn, last)) is not None:
            last = item.id
            if stop_at is not None and now() >= stop_at:
                report.stopped = "until"
                break
            if max_cost_usd is not None and report.spent_usd >= max_cost_usd:
                report.stopped = "cost"
                break
            remaining = None if max_cost_usd is None else max_cost_usd - report.spent_usd
            store.mark_running(conn, item.id, now())
            result = _run_one(execute, item, remaining)
            _record(conn, item, result, now())
            report.spent_usd += result.cost_usd
            {"done": report.done, "failed": report.failed, "skipped": report.skipped}[
                result.status
            ].append(item.id)
            report.results.append((item, result))
            if on_item is not None:
                on_item(item, result)
    finally:
        store.release_lock(conn, me)
    return report


def run_with_notify(
    conn: sqlite3.Connection, config: Config, *, notify_on: bool, **kwargs: Any
) -> tuple[QueueReport, list[notify.Delivery]]:
    """``queue run --notify``: the counts when it ends, a short line when it breaks (never
    for a refused start or Ctrl+C: somebody is there to see it)."""
    try:
        report = run_queue(conn, **kwargs)
    except (QueueBusy, UsageError):
        raise
    except Exception:
        if notify_on:
            notify.send(config.notify, t("notify.title.queue"), t("notify.queue_error"))
        raise
    if not notify_on:
        return report, []
    deliveries = notify.send(
        config.notify,
        t("notify.title.queue"),
        notify.counts_text(report.finished, len(report.failed)),
    )
    return report, deliveries


def _run_one(execute: Execute, item: store.QueueItem, remaining: float | None) -> ItemResult:
    try:
        return execute(item, remaining)
    except OrkestraError as exc:
        return ItemResult("failed", note=exc.message or type(exc).__name__)
    except Exception as exc:  # one broken item must not stop the night's queue
        detail = f"{type(exc).__name__}: {exc}"
        return ItemResult("failed", note=t("errors.internal", detail=detail))


def _record(
    conn: sqlite3.Connection, item: store.QueueItem, result: ItemResult, at: datetime
) -> None:
    if result.status == "skipped":
        store.mark_skipped(conn, item.id, result.note)
    else:
        store.mark_finished(
            conn, item.id, result.status, at, result_ref=result.result_ref, note=result.note
        )


# --- the real executor ------------------------------------------------------------------


def item_config(config: Config, profile: str | None) -> Config:
    """Without ``--profile`` the item runs on ``queue.default_profile`` as the *default*
    profile, so a task that needs a higher tier still gets it (an explicit profile would be a
    conflict, router.tier_range)."""
    if profile is not None:
        return config
    defaults = config.defaults.model_copy(update={"profile": config.queue.default_profile})
    return config.model_copy(update={"defaults": defaults})


def _cost_skip(
    batch_spec: batch.BatchSpec, config: Config, options: runner.RunOptions, remaining: float | None
) -> str | None:
    """Nobody is there to confirm a cost at night: an item that would ask is skipped; with
    ``--max-cost-usd`` the cap replaces the question."""
    if remaining is None and not batch.checks_cost(config):
        return None
    if remaining is not None and not batch.may_cost(config):
        return None
    costs = asyncio.run(batch.estimate_batch(batch_spec, config, options, fetch_prices=True))
    if remaining is None:
        return t("queue.note.needs_confirmation") if costs.needs_confirmation else None
    if costs.totals.unpriced_remote or costs.totals.cost_usd > remaining:
        return t(
            "queue.note.over_cost",
            cost=f"{costs.totals.cost_usd:.4f}",
            remaining=f"{max(remaining, 0.0):.4f}",
        )
    return None


def execute_item(
    item: store.QueueItem, remaining: float | None, *, config_path: Path | None = None
) -> ItemResult:
    path = Path(item.path)
    workdir = Path(item.workdir)
    if not workdir.is_dir():
        return ItemResult("failed", note=t("queue.note.no_workdir", path=workdir))
    if not path.is_file():
        return ItemResult("failed", note=t("queue.error.no_file", path=path))
    warnings: tuple[str, ...] = ()
    if item.file_hash and store.file_hash(path) != item.file_hash:
        warnings = (t("queue.warning.changed", id=item.id, path=path),)
    with contextlib.chdir(workdir):
        config = item_config(loader.load_config(config_path).config, item.profile)
        options = runner.RunOptions(profile=item.profile)
        if item.kind == "batch":
            result = _execute_batch(path, config, options, remaining)
        else:
            result = _execute_task(path, config, options, remaining)
    return ItemResult(
        result.status, result.result_ref, result.cost_usd, result.note, warnings + result.warnings
    )


def _execute_task(
    path: Path, config: Config, options: runner.RunOptions, remaining: float | None
) -> ItemResult:
    task = spec.load_task(path)
    skip = _cost_skip(batch.from_tasks([task], str(path)), config, options, remaining)
    if skip is not None:
        return ItemResult("skipped", note=skip)
    outcome = asyncio.run(runner.run_task(task, config, options))
    envelope = outcome.envelope
    cost = envelope.usage.cost_usd or 0.0
    if outcome.exit_code == 0:
        return ItemResult("done", envelope.run_id, cost, warnings=outcome.warnings)
    return ItemResult(
        "failed", envelope.run_id, cost, note=envelope.status, warnings=outcome.warnings
    )


def _execute_batch(
    path: Path, config: Config, options: runner.RunOptions, remaining: float | None
) -> ItemResult:
    batch_spec = batch.load_batch(path)
    skip = _cost_skip(batch_spec, config, options, remaining)
    if skip is not None:
        return ItemResult("skipped", note=skip)
    plan = batch.plan_batch(batch_spec, cwd=Path.cwd(), ignore_file=config.security.ignore_file)
    document, code = asyncio.run(
        batch.run_batch(
            batch_spec,
            plan,
            config,
            options,
            parallel=batch_spec.parallel or batch.DEFAULT_PARALLEL,
        )
    )
    cost = sum((r.envelope.usage.cost_usd or 0.0) for r in document.results if r.envelope)
    totals = document.totals
    note = None if code == 0 else t("queue.note.batch", ok=totals.ok, total=len(document.results))
    return ItemResult(
        "done" if code == 0 else "failed", document.batch_id, cost, note, tuple(document.warnings)
    )
