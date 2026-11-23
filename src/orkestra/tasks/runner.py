"""Task lifecycle (Mimari §8): ``ask`` tasks (``orkestra ask`` or a task file) and ``edit``
tasks answered by API workers with whole files (§8.2, Faz 5c).

1. Prepare: verifiers, context, secret scan, prompt.
2. Route (``routing/router.py``): ordered candidates; every left-out provider has a reason.
   ``--dry-run`` stops here.
3. Try the candidates in order. Per candidate, up to ``max_retries + 1`` answers:
   reserve budget → request → settle budget → verify. A failed check is sent back to the
   same model as feedback (``prompts/retry_feedback.md``) and it tries again. When its
   answers keep failing, or it says ``CANNOT_DO``, the run moves up to the next tier (same-
   tier candidates are skipped). Provider errors are retried with backoff or fail over to
   the next candidate (``routing/retry.py``). Every abandoned candidate is listed in the
   envelope's ``failovers`` (and in ``escalations`` when the next one is on a higher tier).
4. Result: ``ok``; ``failed`` (checks never passed); ``escalate`` (checks failed on tier 3,
   or the worker said it cannot do the task: the chief must take over); ``error``.

Edit tasks run in a worktree (``workspace/git_worktree.py``) that starts from the user's
current files. Every answer starts from that baseline: it is parsed and its paths checked
(``tasks/edit_format.py``; a bad answer is a failed ``edit_format`` check with feedback), its
files are written, then the verifiers run in the worktree. Afterwards only the answer's files
stay (no verifier leftovers). An answer cut off at the output limit means the file is too
large for that model: the run moves straight to tier 3. The user's checkout changes only on
``orkestra apply``; an interrupted run keeps its worktree.

Code agents (Faz 6, ``providers/cli_agent.py``) are candidates too, normally on tier 3. An
agent edits the worktree itself (``workspace-write`` sandbox) or reads the project for an
``ask`` task (``read-only``). Its change is the worktree diff against the baseline (its own
commits included); verifier leftovers are dropped the same way. The user's repository is
snapshotted around every agent run: if anything changed there, the ``workspace_scope``
check fails and the user is warned.

Every run gets ``runs/<run_id>/`` with ``task.yaml``, ``attempts/<n>/request.json``,
``attempts/<n>/response.txt``, ``attempts/<n>/verify.log``, ``output.md``, ``envelope.json``
and ``orkestra.log``, plus ``worktree.json`` and ``changes.patch`` for edit tasks (Mimari §3,
§14). Everything written there is redacted.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sqlite3
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from orkestra.cache import responses
from orkestra.config.loader import dump_yaml
from orkestra.config.schema import CliAgentProvider, Config
from orkestra.envelope import (
    Escalation,
    Failover,
)
from orkestra.errors import (
    BudgetExhausted,
    ProviderError,
    ProviderTimeout,
    UsageError,
)
from orkestra.i18n import t
from orkestra.logging_setup import run_log
from orkestra.providers.base import (
    AgentRequest,
    AgentResult,
    CompletionRequest,
    CompletionResult,
    Usage,
    estimate_tokens,
)
from orkestra.providers.cli_agent import create_agent
from orkestra.providers.registry import (
    ChatConfig,
    agent_timeout,
    create_chat_provider,
    request_timeout,
)
from orkestra.routing import retry
from orkestra.routing.router import (
    Candidate,
)
from orkestra.state import budget, db, health
from orkestra.tasks import edit_format as ef
from orkestra.tasks.fix import run_fix_commands
from orkestra.tasks.prepare import (
    AGENT_CONTINUE,
    OUTPUT_TRUNCATED,
    SCOPE_CHECK,
    SCOPE_FILES,
    TOP_TIER,
    VERIFICATION_FAILED,
    _cannot_do,
    _prepare,
    _route,
)
from orkestra.tasks.prepare import (
    DryRun as DryRun,
)
from orkestra.tasks.prepare import (
    Estimate as Estimate,
)
from orkestra.tasks.prepare import (
    ProviderSlots as ProviderSlots,
)
from orkestra.tasks.prepare import (
    RunOptions as RunOptions,
)
from orkestra.tasks.prepare import (
    Sleep as Sleep,
)
from orkestra.tasks.prepare import (
    Slot as Slot,
)
from orkestra.tasks.prepare import (
    TaskOutcome as TaskOutcome,
)
from orkestra.tasks.prepare import (
    estimate_task as estimate_task,
)
from orkestra.tasks.prepare import (
    new_run_id as new_run_id,
)
from orkestra.tasks.prepare import (
    plan_task as plan_task,
)
from orkestra.tasks.prompts import (
    build_retry_message,
)
from orkestra.tasks.run_record import RunRecord, _Answer
from orkestra.tasks.spec import TaskSpec
from orkestra.verify import CheckResult, VerifyContext, run_verifiers
from orkestra.verify.base import Message, failed, passed
from orkestra.workspace import git_worktree as gw
from orkestra.workspace import service as workspaces


async def _sleep(seconds: float) -> None:
    """Retry backoff wait; tests replace it so they never really wait."""
    await asyncio.sleep(seconds)


async def run_task(
    task: TaskSpec,
    config: Config,
    options: RunOptions | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    now: db.Clock = db.local_now,
    conn: sqlite3.Connection | None = None,
    sleep: Sleep | None = None,
    rand: Callable[[], float] = random.random,
    policy: retry.RetryPolicy | None = None,
    slots: ProviderSlots | None = None,
    batch_id: str | None = None,
    on_start: Callable[[str], object] | None = None,
) -> TaskOutcome:
    """Run one task. A batch passes shared ``slots``, its ``batch_id`` and ``on_start``
    (called with the run id once the run is recorded) (Faz 7a)."""
    env = os.environ if environ is None else environ
    prep = _prepare(task, options or RunOptions(), config, env, cwd)
    state = db.connect() if conn is None else conn
    try:
        started_at = now()
        lock = slots.prices if slots is not None else None
        planned = await _route(prep, state, started_at, fetch_prices=True, price_lock=lock)
        if not planned.candidates:
            raise planned.error()
        runner = _TaskRun(prep, state, planned, started_at, now, clock, sleep or _sleep, rand,
                          policy or retry.RetryPolicy(),
                          slots=slots, batch_id=batch_id, on_start=on_start)  # fmt: skip
        return await runner.run()
    finally:
        if conn is None:
            state.close()


@dataclass(frozen=True)
class _Scope:
    """The user's repository and its state before a code agent ran."""

    repo: Path | None
    before: dict[str, str] | None


def _repo_of(path: Path) -> Path | None:
    try:
        return gw.repo_root(path)
    except UsageError:
        return None


class _TaskRun(RunRecord):
    """The attempts of one run: candidates, answers, checks, agents, failover."""

    def _completion(self, candidate: Candidate, config: ChatConfig, user: str) -> CompletionRequest:
        timeout = self.task.limits.timeout_s or request_timeout(config, self.prep.config.defaults)
        edit_format = self.prep.edit_format(candidate)
        return CompletionRequest(
            model=candidate.model.id,
            system=self.prep.messages(edit_format)[0],
            user=user,
            max_output_tokens=self._max_output(candidate),
            # SEARCH/REPLACE blocks are plain text; only whole-file edits are JSON.
            json_mode=self.task.output.format == "json" or edit_format == "whole",
            timeout_s=timeout,
        )

    async def run(self) -> TaskOutcome:
        db.record_run_start(
            self.conn, run_id=self.run_id, task_id=self.task.id, kind=self.task.kind,
            started_at=self.started_at, tags=self.task.tags, batch_id=self.batch_id,
        )  # fmt: skip
        if self.on_start is not None:
            self.on_start(self.run_id)  # a batch keeps it even if the run crashes later
        with run_log(self.run_dir, self.prep.redact) as log:
            self.log = log
            try:
                return await self._run()
            except BaseException as exc:
                # Ctrl+C or a bug: still close the run row and leave an envelope behind.
                self._crashed(exc)
                raise

    async def _run(self) -> TaskOutcome:
        self._write_task()
        if self.prep.edit is not None:
            self._open_worktree()
        self.log.info(
            "route: profile=%s tiers=%s-%s candidates=%s eliminated=%d",
            self.route.profile, *self.route.tier_range,
            [c.label for c in self.route.candidates], len(self.route.eliminated),
        )  # fmt: skip
        remaining = list(self.route.candidates)
        skipped_providers: set[str] = set()
        previous: Candidate | None = None
        while remaining:
            candidate = remaining.pop(0)
            if candidate.provider in skipped_providers:
                continue
            if health.get(self.conn, candidate.provider).is_open(self.now()):
                # Paused during this run (e.g. by our own failed retries).
                self.log.info("skipping %s: provider paused", candidate.label)
                skipped_providers.add(candidate.provider)
                continue
            if previous is not None and candidate.tier > previous.tier and self.failovers:
                last = self.failovers[-1]
                self.escalations.append(
                    Escalation(provider=last.provider, model=last.model, tier=last.tier,
                               reason=last.reason)
                )  # fmt: skip
            previous = candidate
            outcome = await self._try(candidate)
            if isinstance(outcome, TaskOutcome):
                return outcome
            action = outcome
            if action is retry.Action.SKIP_PROVIDER:
                skipped_providers.add(candidate.provider)
            elif action is retry.Action.BIGGER_CONTEXT:
                window = candidate.model.context_window
                remaining = [c for c in remaining if c.model.context_window > window]
            elif action is retry.Action.ESCALATE:
                remaining = [c for c in remaining if c.tier > candidate.tier]
            elif action is retry.Action.TOP_TIER:
                remaining = [c for c in remaining if c.tier >= TOP_TIER]
        if self.last_problem == "checks" and self.rejected is not None:
            if self.wt is not None and self.rejected_patch is not None:
                # A later candidate (e.g. an agent that crashed) may have changed the
                # worktree: the envelope must describe the answer it reports.
                gw.reset(self.wt)
                gw.restore(self.wt, self.rejected_patch)
            return self._checks_failed(self.rejected)
        if self.last_problem == "escalate":
            return self._escalate()
        return self._all_failed()

    def _open_worktree(self) -> None:
        """The edit task's worktree, starting from the user's current files (Mimari §9)."""
        wt = gw.create(self.prep.base_dir, self.run_id)
        workspaces.attach_worktree(self.conn, self.run_id, wt)
        self.wt = wt
        try:
            self.workdir = wt.path / self.prep.base_dir.relative_to(wt.repo)
        except ValueError:
            self.workdir = wt.path
        self.prep.warnings.extend(wt.warnings)
        self.log.info("worktree %s (baseline %s)", wt.path, wt.baseline[:12])

    def _write_task(self) -> None:
        data = self.task.model_dump(mode="json", by_alias=True)
        data["context"]["resolved_files"] = [f.display for f in self.prep.context.files]
        data["profile"] = self.route.profile
        self._write(self.run_dir / "task.yaml", dump_yaml(data))

    async def _try(self, candidate: Candidate) -> TaskOutcome | retry.Action:
        """One candidate: answers, checks and feedback retries, plus transport retries.

        Returns the outcome when an answer passed, otherwise what to do next.
        """
        self.cache_key = None  # set per candidate, so no other candidate's key is reused
        config = candidate.config
        if isinstance(config, CliAgentProvider):
            return await self._try_agent(candidate, config)
        provider = create_chat_provider(candidate.provider, config, self.prep.env)
        if config.budget.daily_usd is not None and candidate.price is None:
            self.prep.warnings.append(
                t("budget.warning.no_price", provider=candidate.provider, model=candidate.model.id)
            )
        self.edit_format = self.prep.edit_format(candidate)
        base_user = self.prep.messages(self.edit_format)[1]
        user = base_user
        tries = 0  # requests sent to this candidate
        transport = 0  # failed requests in a row (backoff counter)
        answers = 0
        while True:
            completion = self._completion(candidate, config, user)
            if user is base_user:  # only the task's own prompt; feedback retries are not cached
                self.cache_key = self._cache_key(candidate, completion)
                cached = self._cached(candidate, completion)
                if cached is not None:
                    # A cached answer is not one of the worker's answers (max_retries): if it
                    # fails the checks now, it is dropped and the worker is asked.
                    attempt_dir = self._cache_attempt(candidate)
                    verdict = await self._answered(
                        candidate, cached, attempt_dir, tries, answers, completion, base_user
                    )
                    self.cache_hit = False
                    if isinstance(verdict, TaskOutcome):
                        return verdict
                    responses.forget(self.cache_key or "")
                    self.log.info("cached answer failed its checks; dropped")
                    if not isinstance(verdict, str):
                        verdict = base_user  # nothing to feed back: ask the task itself
                    user = verdict
                    continue
            prompt_chars = len(completion.system) + len(completion.user)
            amount = budget.estimate(
                prompt_chars, completion.max_output_tokens, candidate.price,
                runs=0 if candidate.provider in self.run_counted else 1,
            )  # fmt: skip
            # Wait for the provider (its concurrency) before reserving budget, and check its
            # health again after the wait: another task may have paused it meanwhile (D-054).
            slot = self.slots(candidate.provider)
            await slot.acquire()
            backoff: float | None = None
            result: CompletionResult | None = None
            try:
                paused = self._paused(candidate, tries)
                if paused is not None:
                    return paused
                try:
                    reservation = budget.reserve(
                        self.conn, provider=candidate.provider, model=candidate.model.id,
                        run_id=self.run_id, budget=candidate.config.budget, amount=amount,
                        now=self.now(),
                    )  # fmt: skip
                except BudgetExhausted as exc:  # nothing was sent: not an attempt
                    return self._fail(candidate, exc, tries, retry.Action.NEXT)
                self.run_counted.add(candidate.provider)
                self.attempts += 1
                tries += 1
                attempt_dir = self.run_dir / "attempts" / str(self.attempts)
                self._write(
                    attempt_dir / "request.json",
                    json.dumps({"provider": candidate.provider, **asdict(completion)}, indent=2),
                )
                self.log.info(
                    "attempt %d: %s (try %d%s)", self.attempts, candidate.label, tries,
                    f", edit_format {self.edit_format}" if self.edit_format else "",
                )  # fmt: skip
                try:
                    result = await provider.complete(completion)
                except ProviderError as exc:
                    if isinstance(exc, ProviderTimeout):
                        # The provider may have processed (and billed) it: keep the estimate.
                        budget.settle_as_reserved(self.conn, reservation, now=self.now())
                    else:
                        budget.settle(
                            self.conn, reservation, prompt_tokens=0, completion_tokens=0,
                            cost_usd=0.0, estimated=False, now=self.now(),
                        )  # fmt: skip
                    state = health.record_failure(self.conn, candidate.provider, exc, self.now())
                    self.log.warning(
                        "attempt %d failed: %s %s (failures in a row: %d)",
                        self.attempts, type(exc).__name__, exc.message,
                        state.consecutive_failures,
                    )  # fmt: skip
                    transport += 1
                    action = retry.classify(exc)
                    if action is retry.Action.RETRY and not state.is_open(self.now()):
                        backoff = retry.delay(transport, exc, self.policy, self.rand)
                    if backoff is None:
                        if action is retry.Action.RETRY:
                            action = retry.give_up(exc)
                        return self._fail(candidate, exc, tries, action)
                except BaseException:
                    budget.release(self.conn, reservation)  # interrupted: nothing to pay for
                    self.log.warning("interrupted; reservation released")
                    raise
            finally:
                slot.release()
            if backoff is not None:
                self.log.info("retrying %s in %.2fs", candidate.label, backoff)
                await self.sleep(backoff)  # the slot is free for other tasks meanwhile
                continue
            assert result is not None
            transport = 0
            usage = self._actual_usage(prompt_chars, candidate, result)
            budget.settle(
                self.conn, reservation, prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens, cost_usd=usage.cost_usd,
                estimated=usage.estimated, now=self.now(),
            )  # fmt: skip
            health.record_success(self.conn, candidate.provider)
            self.used.append(usage)
            answers += 1
            verdict = await self._answered(
                candidate, result, attempt_dir, tries, answers, completion, base_user
            )
            if not isinstance(verdict, str):
                return verdict
            user = verdict

    async def _answered(
        self,
        candidate: Candidate,
        result: CompletionResult,
        attempt_dir: Path,
        tries: int,
        answers: int,
        completion: CompletionRequest,
        base_user: str,
    ) -> TaskOutcome | retry.Action | str:
        """A chat worker's answer (sent or from the cache): refusal, cut-off, checks."""
        self._write(attempt_dir / "response.txt", result.text, answer=True)
        reason = _cannot_do(result.text)
        if reason is None and self.edit_format == "whole":
            # JSON mode: {"cannot_do": "..."}. SEARCH/REPLACE answers hold raw code, where
            # such a literal is content, not a refusal.
            reason = ef.cannot_do(result.text)
        if reason is not None:
            self.escalate_reason = t("ask.cannot_do", reason=reason or "-")
            self.last_problem = "escalate"
            return self._fail(candidate, None, tries, retry.Action.ESCALATE, reason=reason)
        if self.prep.edit is not None and result.raw_finish_reason == "length":
            # Whole files did not fit into the output limit: feedback cannot fix that.
            message = t("edit.truncated", tokens=completion.max_output_tokens)
            self.escalate_reason, self.last_problem = message, "escalate"
            return self._fail(candidate, None, tries, retry.Action.TOP_TIER, reason=message,
                              error=OUTPUT_TRUNCATED)  # fmt: skip
        checks = await self._verify(result.text, attempt_dir)
        return await self._judge(
            candidate, result, checks, tries, answers, completion.max_output_tokens, base_user
        )

    async def _judge(
        self,
        candidate: Candidate,
        result: CompletionResult,
        checks: list[CheckResult],
        tries: int,
        answers: int,
        limit: int,
        base_prompt: str,
    ) -> TaskOutcome | retry.Action | str:
        """Success, giving up on the candidate, or the next prompt (with feedback)."""
        if all(c.result.ok for c in checks):
            return await self._succeed(candidate, limit, result, checks)

        self.rejected = _Answer(candidate, result.text, checks, result)
        self.last_problem = "checks"
        if self.wt is not None:
            self.rejected_patch = gw.diff(self.wt).patch
        failures = [c.feedback for c in checks if not c.result.ok]
        self.log.info("attempt %d failed checks: %s", self.attempts, failures)
        if answers >= self.max_answers:
            names = ", ".join(c.result.type for c in checks if not c.result.ok)
            message = t("verify.failed", checks=names)
            return self._fail(candidate, None, tries, retry.Action.ESCALATE, reason=message,
                              error=VERIFICATION_FAILED)  # fmt: skip
        # Feedback goes to a model: mask everything secret, as in the records. An API worker's
        # answer is undone before the retry; a code agent continues from its change instead
        # (``AGENT_CONTINUE``), so only chat workers are told their change was discarded.
        api_edit = self.prep.edit is not None and not isinstance(candidate.config, CliAgentProvider)
        return build_retry_message(
            base_prompt,
            self.prep.redact_output(result.text),
            [self.prep.redact(f) for f in failures],
            edit=api_edit,
        )

    async def _try_agent(
        self, candidate: Candidate, cfg: CliAgentProvider
    ) -> TaskOutcome | retry.Action:
        """A code agent: runs, checks and feedback runs (no transport retries)."""
        try:
            agent = create_agent(candidate.provider, cfg, self.prep.env)
        except ProviderError as exc:  # not installed
            return self._fail(candidate, exc, 0, retry.classify(exc))
        timeout = self.task.limits.timeout_s or agent_timeout(cfg, self.prep.config.defaults)
        repo = self.wt.repo if self.wt is not None else _repo_of(self.prep.base_dir)
        prompt = self.prep.agent_user
        tries = answers = 0
        while True:
            amount = budget.estimate(
                len(prompt), 0, None, runs=0 if candidate.provider in self.run_counted else 1
            )
            # As for chat workers: the slot first, then health and budget (D-054).
            async with self.slots(candidate.provider):
                paused = self._paused(candidate, tries)
                if paused is not None:
                    return paused
                try:
                    reservation = budget.reserve(
                        self.conn, provider=candidate.provider, model=candidate.model.id,
                        run_id=self.run_id, budget=cfg.budget, amount=amount, now=self.now(),
                    )  # fmt: skip
                except BudgetExhausted as exc:
                    return self._fail(candidate, exc, tries, retry.Action.NEXT)
                self.run_counted.add(candidate.provider)
                self.attempts += 1
                tries += 1
                attempt_dir = self.run_dir / "attempts" / str(self.attempts)
                attempt_dir.mkdir(parents=True, exist_ok=True)
                req = AgentRequest(
                    prompt=prompt,
                    workdir=self.workdir,
                    model=self.task.model or cfg.model,
                    sandbox="workspace-write" if self.wt is not None else "read-only",
                    timeout_s=timeout,
                    output_file=attempt_dir / "agent_output.md",
                )
                self._write(
                    attempt_dir / "request.json",
                    json.dumps({"provider": candidate.provider, "kind": cfg.kind,
                                **asdict(req)}, indent=2, default=str),
                )  # fmt: skip
                self.log.info(
                    "attempt %d: %s (agent, try %d)", self.attempts, candidate.label, tries
                )
                if self.wt is not None and tries == 1:
                    gw.reset(self.wt)  # a new candidate starts from the user's files
                before = gw.status_snapshot(repo) if repo is not None else None
                scope = _Scope(repo, before)
                try:
                    result = await agent.run(req)
                except ProviderError as exc:
                    if isinstance(exc, ProviderTimeout):
                        budget.settle_as_reserved(self.conn, reservation, now=self.now())
                    else:
                        budget.settle(
                            self.conn, reservation, prompt_tokens=0, completion_tokens=0,
                            cost_usd=0.0, estimated=False, now=self.now(),
                        )  # fmt: skip
                    health.record_failure(self.conn, candidate.provider, exc, self.now())
                    self.log.warning("attempt %d failed: %s %s", self.attempts,
                                     type(exc).__name__, exc.message)  # fmt: skip
                    self._scope_checks(scope)  # a crashed agent may still have written outside
                    action = retry.classify(exc)
                    if action is retry.Action.RETRY:
                        action = retry.give_up(exc)
                    return self._fail(candidate, exc, tries, action)
                except BaseException:
                    budget.release(self.conn, reservation)  # interrupted: nothing to pay for
                    self.log.warning("interrupted; reservation released")
                    raise
            usage = self._agent_usage(len(prompt), result)
            budget.settle(
                self.conn, reservation, prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens, cost_usd=None,
                estimated=True, now=self.now(),
            )  # fmt: skip
            health.record_success(self.conn, candidate.provider)
            self.used.append(usage)
            text = result.final_message
            self._write(attempt_dir / "response.txt", text, answer=True)
            reason = _cannot_do(text)
            if reason is not None:
                self._scope_checks(scope)
                self.escalate_reason = t("ask.cannot_do", reason=reason or "-")
                self.last_problem = "escalate"
                return self._fail(candidate, None, tries, retry.Action.ESCALATE, reason=reason)
            answers += 1
            checks = await self._verify(text, attempt_dir, scope)
            verdict = await self._judge(
                candidate, CompletionResult(text, usage, None), checks, tries, answers,
                self._max_output(candidate), self.prep.agent_user,
            )  # fmt: skip

            if not isinstance(verdict, str):
                return verdict
            # Feedback runs continue from the agent's change (restored after the checks).
            prompt = f"{verdict}\n\n{AGENT_CONTINUE}" if self.wt is not None else verdict

    def _agent_usage(self, prompt_chars: int, result: AgentResult) -> Usage:
        reported = result.usage
        prompt = reported.prompt_tokens
        completion = reported.completion_tokens
        return Usage(
            prompt if prompt is not None else estimate_tokens(prompt_chars),
            completion if completion is not None else estimate_tokens(len(result.final_message)),
            None,
            estimated=True,
        )

    def _scope_checks(self, scope: _Scope | None) -> list[CheckResult]:
        """Did the agent write into the user's repository? (Snapshots around the run.)"""
        if scope is None or scope.repo is None or scope.before is None:
            return []
        after = gw.status_snapshot(scope.repo)
        keys = scope.before.keys() | after.keys()
        changed = sorted(k for k in keys if scope.before.get(k) != after.get(k))
        if not changed:
            return [passed(SCOPE_CHECK)]
        shown = ", ".join(changed[:SCOPE_FILES]) + (", …" if len(changed) > SCOPE_FILES else "")
        self.prep.warnings.append(t("agent.warning.outside", repo=scope.repo, files=shown))
        self.log.warning("files outside the worktree changed: %s", shown)
        return [failed(SCOPE_CHECK, Message("agent.error.outside", {"files": shown}))]

    async def _verify(
        self, text: str, attempt_dir: Path, scope: _Scope | None = None
    ) -> list[CheckResult]:
        """``scope`` is set for code agents (they write themselves; see ``_scope_checks``)."""
        if self.wt is not None and scope is not None:
            checks = await self._check_agent_edit(self.wt, text, scope, attempt_dir)
        elif self.wt is not None:
            checks = await self._check_edit(self.wt, text, attempt_dir)
        else:
            checks = self._scope_checks(scope)
            if self.prep.checks:
                ctx = VerifyContext(workdir=self.prep.base_dir, output=text)
                checks += await run_verifiers(self.prep.checks, ctx)
            if not checks:
                return []
        log = "\n".join(
            f"== {c.result.type}: {'ok' if c.result.ok else 'FAIL'} ==\n{c.log or c.result.detail}"
            for c in checks
        )
        self._write(attempt_dir / "verify.log", log + "\n")
        return checks

    async def _check_edit(self, wt: gw.Worktree, text: str, attempt_dir: Path) -> list[CheckResult]:
        """Write an edit answer into the worktree (from the baseline) and verify it."""
        assert self.prep.edit is not None
        gw.reset(wt)  # every answer starts from the user's files, not the last answer
        blocks: ef.ReplaceAnswer | None = None
        try:
            if self.edit_format == "replace":
                blocks = ef.parse_replace(text, known=self.prep.edit.editable)
                answer = ef.paths_only(blocks)  # paths are checked before any file is read
            else:
                answer = ef.parse(text)
        except ef.EditFormatError as exc:
            return [failed(ef.FORMAT_CHECK, exc.problem)]
        rels = [rel for e in answer.files if (rel := ef.normalize_path(e.path)) is not None]
        problems = ef.check_paths(
            answer, self.workdir, editable=self.prep.edit.editable,
            allow_new=self.task.allow_new_files, forbidden=self.prep.edit.forbidden,
            protected=self.prep.edit.protected, ignored=gw.ignored(self.workdir, rels),
        )  # fmt: skip
        if problems:
            return [failed(ef.FORMAT_CHECK, problems)]
        try:
            if blocks is not None:
                answer = ef.resolve_replace(blocks, self.workdir)  # whole files, in memory
            ef.write(answer, self.workdir)
        except ef.EditFormatError as exc:
            return [failed(ef.FORMAT_CHECK, exc.problem)]
        if self.task.fix:
            await run_fix_commands(self.task.fix, self.workdir, attempt_dir)
        self.note = answer.note
        change = gw.diff(wt) if self.task.fix else None
        ctx = VerifyContext(
            workdir=self.workdir,
            output=text,
            changes=self._changes(wt, change) if change else self._changes(wt),
        )
        checks = await run_verifiers(self.prep.checks, ctx) if self.prep.checks else []
        # Verifier commands leave files behind (__pycache__, build output): keep the answer only.
        gw.reset(wt)
        if self.task.fix and change is not None:
            gw.restore(wt, change.patch)
        else:
            ef.write(answer, self.workdir)
        return checks

    async def _check_agent_edit(
        self, wt: gw.Worktree, text: str, scope: _Scope, attempt_dir: Path
    ) -> list[CheckResult]:
        """Verify what an agent changed in the worktree; keep only its change afterwards."""
        if self.task.fix:
            await run_fix_commands(self.task.fix, self.workdir, attempt_dir)
        outside = self._scope_checks(scope)
        change = gw.diff(wt)  # against the baseline, so the agent's own commits count too
        self.note = text
        ctx = VerifyContext(workdir=self.workdir, output=text, changes=self._changes(wt, change))
        checks = await run_verifiers(self.prep.checks, ctx) if self.prep.checks else []
        gw.reset(wt)  # drop what the verifiers left behind
        gw.restore(wt, change.patch)
        return [*outside, *checks]

    def _actual_usage(
        self, prompt_chars: int, candidate: Candidate, result: CompletionResult
    ) -> Usage:
        """What the request used, for the budget and the envelope.

        Tokens the provider did not report are estimated from the text; a cost it did not
        report is priced with the model's resolved price (config, price list or history).
        """
        reported = result.usage
        estimated = reported.estimated
        prompt = reported.prompt_tokens
        completion = reported.completion_tokens
        if prompt is None:
            prompt, estimated = estimate_tokens(prompt_chars), True
        if completion is None:
            completion, estimated = estimate_tokens(len(result.text)), True
        cost = reported.cost_usd
        if cost is None and candidate.price is not None:
            cost = candidate.price.cost(prompt, completion)
            estimated = estimated or candidate.price.source == "history"
        return Usage(prompt, completion, cost, estimated)

    def _paused(self, candidate: Candidate, tries: int) -> retry.Action | None:
        """Give up on a provider that another task paused while this one waited for a slot."""
        state = health.get(self.conn, candidate.provider)
        if state.open_until is None or not state.is_open(self.now()):
            return None
        kind = health.pause_kind(state.reason)
        reason = t(
            f"select.reason.{kind}", name=candidate.provider,
            until=health.until_text(state.open_until, self.now()), error=state.last_error or "-",
        )  # fmt: skip
        if kind == "quota_paused":  # its other models are paused too
            return self._fail(candidate, None, tries, retry.Action.SKIP_PROVIDER, reason=reason,
                              error="QuotaPaused")  # fmt: skip
        return self._fail(candidate, None, tries, retry.Action.NEXT, reason=reason,
                          error="CircuitOpen")  # fmt: skip

    def _fail(
        self,
        candidate: Candidate,
        exc: ProviderError | BudgetExhausted | None,
        tries: int,
        action: retry.Action,
        *,
        reason: str | None = None,
        error: str = "CannotDo",
    ) -> retry.Action:
        """Record an abandoned candidate. Without ``exc``: CANNOT_DO or failed checks."""
        name = type(exc).__name__ if exc is not None else error
        if exc is not None:
            message = exc.message
        elif error == "CannotDo":
            message = t("ask.cannot_do", reason=reason or "-")
        else:
            message = reason or "-"
        self.failovers.append(
            Failover(
                provider=candidate.provider,
                model=candidate.model.id,
                tier=candidate.tier,
                error=name,
                reason=self.prep.redact(message),
                attempts=tries,
            )
        )
        self.log.warning("giving up on %s: %s → %s", candidate.label, name, action.value)
        return action

    async def _succeed(
        self,
        candidate: Candidate,
        limit: int,
        result: CompletionResult,
        checks: list[CheckResult],
    ) -> TaskOutcome:
        answer = _Answer(candidate, result.text, checks, result)
        envelope, text = self._answer_envelope(answer, "ok", limit)
        if self.cache_hit:
            envelope = envelope.model_copy(update={"cached": True})
        self._remember(candidate, result.text)
        if (
            self.prep.config.review.auto
            and self.wt is not None
            and envelope.changes is not None
            and envelope.changes.files > 0
        ):
            envelope = await self._auto_review(envelope)
        return self._finish(envelope, text, 0)
