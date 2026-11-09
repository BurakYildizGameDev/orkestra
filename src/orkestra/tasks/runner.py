"""Task lifecycle (Mimari §8). Current version (Faz 5a): ``ask`` tasks, from ``orkestra ask``
or a task file (``orkestra run``).

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

Every run gets ``runs/<run_id>/`` with ``task.yaml``, ``attempts/<n>/request.json``,
``attempts/<n>/response.txt``, ``attempts/<n>/verify.log``, ``output.md``, ``envelope.json``
and ``orkestra.log`` (Mimari §3, §14). Everything written there is redacted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import secrets
import sqlite3
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from orkestra import paths
from orkestra.config.loader import dump_yaml
from orkestra.config.schema import Config
from orkestra.envelope import (
    EnvelopeUsage,
    Escalation,
    Failover,
    ResultEnvelope,
    Status,
    summarize_text,
    to_json,
)
from orkestra.errors import (
    BudgetExhausted,
    ExitCode,
    NoProviderAvailable,
    ProviderError,
    ProviderTimeout,
    UsageError,
)
from orkestra.i18n import t
from orkestra.logging_setup import run_log
from orkestra.providers import pricing
from orkestra.providers.base import CompletionRequest, CompletionResult, Usage, estimate_tokens
from orkestra.providers.registry import create_chat_provider, request_timeout
from orkestra.routing import retry
from orkestra.routing.router import (
    Candidate,
    Route,
    Snapshot,
    TaskNeeds,
    route,
    scope,
    take_snapshot,
)
from orkestra.security.redact import Redactor, configured_secrets
from orkestra.security.secrets_scan import Finding, blocking, scan_text
from orkestra.state import budget, consent, db, health
from orkestra.tasks.context import Context, collect_context
from orkestra.tasks.prompts import build_ask_messages, build_retry_message
from orkestra.tasks.spec import TaskSpec
from orkestra.verify import CheckResult, Verifier, VerifyContext, build_verifiers, run_verifiers
from orkestra.verify.schema import JsonSchemaCheck

Sleep = Callable[[float], Awaitable[None]]

PROMPT_SOURCE = "<prompt>"  # where a finding in the prompt text itself is reported
CANNOT_DO = "CANNOT_DO:"  # worker protocol (prompts/worker_system.md, Mimari §8.1)
VERIFICATION_FAILED = "VerificationFailed"  # failover "error" when answers kept failing checks
TOP_TIER = 3
IGNORED_WARNINGS = 5  # more skipped files than this are reported as one count


async def _sleep(seconds: float) -> None:
    """Retry backoff wait; tests replace it so they never really wait."""
    await asyncio.sleep(seconds)


def new_run_id(now: datetime | None = None, token: str | None = None) -> str:
    """``YYYYMMDD-HHMMSS-<4 hex>``: sortable and practically collision free."""
    moment = datetime.now() if now is None else now
    return f"{moment:%Y%m%d-%H%M%S}-{token or secrets.token_hex(2)}"


@dataclass(frozen=True)
class RunOptions:
    """Command line choices that are not part of the task itself."""

    profile: str | None = None
    allow_secrets: bool = False


@dataclass(frozen=True)
class TaskOutcome:
    envelope: ResultEnvelope
    output: str | None
    exit_code: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DryRun:
    route: Route
    warnings: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        return 0 if self.route.candidates else self.route.error().exit_code


def _scan(prompt: str, context: Context, known: Sequence[str]) -> list[Finding]:
    """The prompt counts as much as the context: ``ask "$(cat .env)"`` must not leak either."""
    findings = scan_text(PROMPT_SOURCE, prompt, known)
    for f in context.files:
        findings.extend(scan_text(f.display, f.text, known))
    return findings


def _cannot_do(text: str) -> str | None:
    """The worker's reason when it answered ``CANNOT_DO: <reason>``, else ``None``."""
    stripped = text.strip()
    if not stripped.startswith(CANNOT_DO):
        return None
    return stripped[len(CANNOT_DO) :].strip().splitlines()[0] if stripped != CANNOT_DO else ""


@dataclass
class _Prepared:
    task: TaskSpec
    options: RunOptions
    config: Config
    env: Mapping[str, str]
    base_dir: Path
    checks: list[Verifier]
    context: Context
    redact: Redactor  # records and logs: everything that looks secret
    redact_output: Redactor  # the answer: secrets only, so "password: changeme" stays intact
    findings: list[Finding]
    warnings: list[str]
    system: str
    user: str

    def needs(self) -> TaskNeeds:
        return TaskNeeds(
            kind=self.task.kind,
            tier=self.task.tier,
            privacy=self.task.privacy,
            provider=self.task.provider,
            model=self.task.model,
            prompt_chars=len(self.system) + len(self.user),
            has_secrets=bool(blocking(self.findings)),
            allow_secrets=self.options.allow_secrets,
        )


def _warnings(context: Context, findings: Sequence[Finding]) -> list[str]:
    warnings = [t("context.warning.binary", path=p) for p in context.skipped_binary]
    ignored = context.skipped_ignored
    if len(ignored) > IGNORED_WARNINGS:  # one line instead of a screenful
        names = ", ".join(sorted({f for _, f in ignored}))
        warnings.append(t("context.warning.ignored_many", count=len(ignored), files=names))
    else:
        warnings += [t("context.warning.ignored", path=p, file=f) for p, f in ignored]
    warnings += [
        t("secrets.warning.found_prompt", line=f.line, kind=f.kind)
        if f.path == PROMPT_SOURCE
        else t("secrets.warning.found", path=f.path, line=f.line, kind=f.kind)
        for f in findings
    ]
    return warnings


def _prepare(
    task: TaskSpec, options: RunOptions, config: Config, env: Mapping[str, str], cwd: Path | None
) -> _Prepared:
    if task.kind != "ask":
        raise UsageError(t("task.error.edit_not_available"))
    base = task.base_dir(Path.cwd() if cwd is None else cwd)
    checks = build_verifiers(task, base_dir=base)
    # The model is told the schema it is checked against (loaded once, by the verifier).
    schema = next((c.schema for c in checks if isinstance(c, JsonSchemaCheck) and c.schema), None)
    context = collect_context(
        [Path(f) for f in task.context.files], globs=task.context.globs, cwd=base,
        max_bytes=config.security.max_context_bytes, ignore_file=config.security.ignore_file,
    )  # fmt: skip
    known = configured_secrets(config, env)
    findings = _scan(task.prompt, context, known)
    system, user = build_ask_messages(
        task.prompt, context, schema, json_output=task.output.format == "json"
    )
    return _Prepared(
        task, options, config, env, base, checks, context, Redactor(known),
        Redactor(known, passwords=False), findings, _warnings(context, findings), system, user,
    )  # fmt: skip


def _price_targets(prep: _Prepared, conn: sqlite3.Connection) -> set[str]:
    """Providers whose price list may be fetched: in scope, enabled, consented, remote allowed.

    The request carries the provider's API key, so it never goes to a provider the user has
    not enabled, nor to one this task cannot use anyway (D-037).
    """
    needs = prep.needs()
    targets: set[str] = set()
    for name in scope(needs, prep.config):
        cfg = prep.config.providers[name]
        if needs.privacy == "local_only" and not cfg.local:
            continue
        if cfg.enabled and consent.state(conn, name, cfg) == "granted":
            targets.add(name)
    return targets


async def _route(
    prep: _Prepared, conn: sqlite3.Connection, moment: datetime, *, fetch_prices: bool
) -> Route:
    needs = prep.needs()
    profile = prep.options.profile
    if needs.provider is not None and needs.provider not in prep.config.providers:
        return route(needs, prep.config, Snapshot(moment), profile=profile)  # raises
    if fetch_prices:
        cache = await pricing.refresh(
            prep.config, moment, only=_price_targets(prep, conn), environ=prep.env
        )
    else:  # --dry-run sends nothing: use whatever prices are cached
        cache = pricing.load_cache()
    extra = (needs.provider, needs.model) if needs.provider and needs.model else None
    snapshot = take_snapshot(
        conn, prep.config, moment, environ=prep.env, price_cache=cache,
        names=scope(needs, prep.config), extra_model=extra,
    )  # fmt: skip
    return route(needs, prep.config, snapshot, profile=profile)


async def plan_task(
    task: TaskSpec,
    config: Config,
    options: RunOptions | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    now: db.Clock = db.local_now,
    conn: sqlite3.Connection | None = None,
) -> DryRun:
    """``--dry-run``: the route only, no request, no budget, no run directory."""
    env = os.environ if environ is None else environ
    prep = _prepare(task, options or RunOptions(), config, env, cwd)
    state = db.connect() if conn is None else conn
    try:
        planned = await _route(prep, state, now(), fetch_prices=False)
        return DryRun(planned, tuple(prep.warnings))
    finally:
        if conn is None:
            state.close()


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
) -> TaskOutcome:
    env = os.environ if environ is None else environ
    prep = _prepare(task, options or RunOptions(), config, env, cwd)
    state = db.connect() if conn is None else conn
    try:
        started_at = now()
        planned = await _route(prep, state, started_at, fetch_prices=True)
        if not planned.candidates:
            raise planned.error()
        runner = _TaskRun(prep, state, planned, started_at, now, clock, sleep or _sleep, rand,
                          policy or retry.RetryPolicy())  # fmt: skip
        return await runner.run()
    finally:
        if conn is None:
            state.close()


@dataclass(frozen=True)
class _Answer:
    """An answer that came back but did not pass its checks."""

    candidate: Candidate
    text: str
    checks: list[CheckResult]
    result: CompletionResult


class _TaskRun:
    def __init__(
        self,
        prep: _Prepared,
        conn: sqlite3.Connection,
        planned: Route,
        started_at: datetime,
        now: db.Clock,
        clock: Callable[[], float],
        sleep: Sleep,
        rand: Callable[[], float],
        policy: retry.RetryPolicy,
    ) -> None:
        self.prep = prep
        self.task = prep.task
        self.conn = conn
        self.route = planned
        self.started_at = started_at
        self.now = now
        self.clock = clock
        self.sleep = sleep
        self.rand = rand
        self.policy = policy
        self.run_id = new_run_id(started_at.replace(tzinfo=None))
        self.run_dir = paths.run_dir(self.run_id)
        self.attempts = 0
        retries = prep.task.limits.max_retries
        self.max_answers = 1 + (prep.config.defaults.max_retries if retries is None else retries)
        # daily_runs is per provider: one run each, however many requests it takes there.
        self.run_counted: set[str] = set()
        self.cannot_do: str | None = None  # last CANNOT_DO reason from a worker
        self.rejected: _Answer | None = None  # last answer that failed its checks
        self.last_problem: str | None = None  # "cannot_do" | "checks": which came last
        self.failovers: list[Failover] = []
        self.escalations: list[Escalation] = []
        self.used: list[Usage] = []  # every answered request of the run (envelope usage)
        self.log = logging.getLogger("orkestra")
        self.started = clock()

    def _write(self, path: Path, text: str, *, answer: bool = False) -> None:
        """Write a run record, redacted. ``answer``: the worker's output (secrets only)."""
        redact = self.prep.redact_output if answer else self.prep.redact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(redact(text).encode("utf-8"))  # bytes: no newline translation

    def _max_output(self, candidate: Candidate) -> int:
        return candidate.model.max_output_tokens or self.prep.config.defaults.max_output_tokens

    def _completion(self, candidate: Candidate, user: str) -> CompletionRequest:
        timeout = self.task.limits.timeout_s or request_timeout(
            candidate.config, self.prep.config.defaults
        )
        return CompletionRequest(
            model=candidate.model.id,
            system=self.prep.system,
            user=user,
            max_output_tokens=self._max_output(candidate),
            json_mode=self.task.output.format == "json",
            timeout_s=timeout,
        )

    async def run(self) -> TaskOutcome:
        db.record_run_start(
            self.conn, run_id=self.run_id, task_id=self.task.id, kind=self.task.kind,
            started_at=self.started_at, tags=self.task.tags,
        )  # fmt: skip
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
        if self.last_problem == "checks" and self.rejected is not None:
            return self._checks_failed(self.rejected)
        if self.last_problem == "cannot_do":
            return self._escalate()
        return self._all_failed()

    def _write_task(self) -> None:
        data = self.task.model_dump(mode="json", by_alias=True)
        data["context"]["resolved_files"] = [f.display for f in self.prep.context.files]
        data["profile"] = self.route.profile
        self._write(self.run_dir / "task.yaml", dump_yaml(data))

    async def _try(self, candidate: Candidate) -> TaskOutcome | retry.Action:
        """One candidate: answers, checks and feedback retries, plus transport retries.

        Returns the outcome when an answer passed, otherwise what to do next.
        """
        provider = create_chat_provider(candidate.provider, candidate.config, self.prep.env)
        if candidate.config.budget.daily_usd is not None and candidate.price is None:
            self.prep.warnings.append(
                t("budget.warning.no_price", provider=candidate.provider, model=candidate.model.id)
            )
        user = self.prep.user
        tries = 0  # requests sent to this candidate
        transport = 0  # failed requests in a row (backoff counter)
        answers = 0
        while True:
            completion = self._completion(candidate, user)
            prompt_chars = len(completion.system) + len(completion.user)
            amount = budget.estimate(
                prompt_chars, completion.max_output_tokens, candidate.price,
                runs=0 if candidate.provider in self.run_counted else 1,
            )  # fmt: skip
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
            self.log.info("attempt %d: %s (try %d)", self.attempts, candidate.label, tries)
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
                    self.attempts, type(exc).__name__, exc.message, state.consecutive_failures,
                )  # fmt: skip
                transport += 1
                action = retry.classify(exc)
                if action is retry.Action.RETRY and not state.is_open(self.now()):
                    wait = retry.delay(transport, exc, self.policy, self.rand)
                    if wait is not None:
                        self.log.info("retrying %s in %.2fs", candidate.label, wait)
                        await self.sleep(wait)
                        continue
                if action is retry.Action.RETRY:
                    action = retry.give_up(exc)
                return self._fail(candidate, exc, tries, action)
            except BaseException:
                budget.release(self.conn, reservation)  # interrupted: nothing to pay for
                self.log.warning("interrupted; reservation released")
                raise
            transport = 0
            usage = self._actual_usage(prompt_chars, candidate, result)
            budget.settle(
                self.conn, reservation, prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens, cost_usd=usage.cost_usd,
                estimated=usage.estimated, now=self.now(),
            )  # fmt: skip
            health.record_success(self.conn, candidate.provider)
            self.used.append(usage)
            self._write(attempt_dir / "response.txt", result.text, answer=True)
            reason = _cannot_do(result.text)
            if reason is not None:
                self.cannot_do, self.last_problem = reason, "cannot_do"
                return self._fail(candidate, None, tries, retry.Action.ESCALATE, reason=reason)
            answers += 1
            checks = await self._verify(result.text, attempt_dir)
            if all(c.result.ok for c in checks):
                return self._succeed(candidate, completion, result, checks)
            self.rejected = _Answer(candidate, result.text, checks, result)
            self.last_problem = "checks"
            failures = [c.feedback for c in checks if not c.result.ok]
            self.log.info("attempt %d failed checks: %s", self.attempts, failures)
            if answers >= self.max_answers:
                names = ", ".join(c.result.type for c in checks if not c.result.ok)
                message = t("verify.failed", checks=names)
                return self._fail(candidate, None, tries, retry.Action.ESCALATE, reason=message,
                                  error=VERIFICATION_FAILED)  # fmt: skip
            # Feedback goes to a model: mask everything secret, as in the records.
            user = build_retry_message(
                self.prep.user,
                self.prep.redact_output(result.text),
                [self.prep.redact(f) for f in failures],
            )

    async def _verify(self, text: str, attempt_dir: Path) -> list[CheckResult]:
        if not self.prep.checks:
            return []
        ctx = VerifyContext(workdir=self.prep.base_dir, output=text)
        checks = await run_verifiers(self.prep.checks, ctx)
        log = "\n".join(
            f"== {c.result.type}: {'ok' if c.result.ok else 'FAIL'} ==\n{c.log or c.result.detail}"
            for c in checks
        )
        self._write(attempt_dir / "verify.log", log + "\n")
        return checks

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

    def _base(self, candidate: Candidate | None) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task.id,
            "provider": candidate.provider if candidate else None,
            "model": candidate.model.id if candidate else None,
            "tier": candidate.tier if candidate else None,
            "attempts": self.attempts,
            "escalations": self.escalations,
            "failovers": self.failovers,
        }

    def _answer_envelope(
        self, answer: _Answer, status: Status, completion_limit: int
    ) -> tuple[ResultEnvelope, str]:
        """Envelope for an answer that is kept (passed, or the last one that failed)."""
        # Files and the terminal get the answer with real secrets masked; checks saw the
        # answer itself, so masking can never break valid JSON.
        text = self.prep.redact_output(answer.text)
        output_path = self.run_dir / "output.md"
        self._write(output_path, text, answer=True)
        if answer.result.raw_finish_reason == "length":
            self.prep.warnings.append(t("ask.warning.truncated", tokens=completion_limit))
            self.log.warning("output hit max_output_tokens=%d", completion_limit)
        envelope = ResultEnvelope(
            **self._base(answer.candidate),
            status=status,
            summary=summarize_text(self.prep.redact(text), str(output_path)),
            # Command output can echo secrets from the environment: mask like the records.
            verification=[
                c.result.model_copy(update={"detail": self.prep.redact(c.result.detail)})
                for c in answer.checks
            ],
            output_path=str(output_path),
            usage=self._total_usage(),
            duration_s=self._duration(),
        )
        return envelope, text

    def _succeed(
        self,
        candidate: Candidate,
        completion: CompletionRequest,
        result: CompletionResult,
        checks: list[CheckResult],
    ) -> TaskOutcome:
        answer = _Answer(candidate, result.text, checks, result)
        envelope, text = self._answer_envelope(answer, "ok", completion.max_output_tokens)
        return self._finish(envelope, text, 0)

    def _checks_failed(self, answer: _Answer) -> TaskOutcome:
        """No answer passed. On tier 3 there is nothing left to try: the chief takes over."""
        status: Status = "escalate" if answer.candidate.tier >= TOP_TIER else "failed"
        limit = self._max_output(answer.candidate)
        envelope, text = self._answer_envelope(answer, status, limit)
        return self._finish(envelope, text, int(ExitCode.TASK_FAILED))

    def _total_usage(self) -> EnvelopeUsage:
        """Everything the run's answers used: retries and earlier candidates are paid too."""
        if not self.used:
            return EnvelopeUsage()
        costs = [u.cost_usd for u in self.used if u.cost_usd is not None]
        return EnvelopeUsage(
            prompt_tokens=sum(u.prompt_tokens or 0 for u in self.used),
            completion_tokens=sum(u.completion_tokens or 0 for u in self.used),
            cost_usd=sum(costs) if costs else None,
        )

    def _duration(self) -> float:
        return round(self.clock() - self.started, 3)

    def _escalate(self) -> TaskOutcome:
        """Workers said CANNOT_DO and no higher tier was left (or answered): exit code 1."""
        reason = t("ask.cannot_do", reason=self.cannot_do or "-")
        envelope = ResultEnvelope(
            **self._base(None),
            status="escalate",
            summary=self.prep.redact(reason),
            duration_s=self._duration(),
        )
        return self._finish(envelope, None, int(ExitCode.TASK_FAILED))

    def _all_failed(self) -> TaskOutcome:
        error = NoProviderAvailable(t("route.all_failed", count=len(self.failovers)))
        envelope = ResultEnvelope(
            **self._base(None),
            status="error",
            error=error.message,
            duration_s=self._duration(),
        )
        return self._finish(envelope, None, int(error.exit_code))

    def _crashed(self, exc: BaseException) -> None:
        """Best effort after an interrupt or a bug; never hides the original exception."""
        detail = (
            t("ask.interrupted")
            if isinstance(exc, KeyboardInterrupt | asyncio.CancelledError)
            else f"{type(exc).__name__}: {str(exc)[:300]}"
        )
        envelope = ResultEnvelope(
            **self._base(None), status="error", error=detail, duration_s=self._duration()
        )
        try:
            self._finish(envelope, None, int(ExitCode.INTERNAL))
        except Exception:  # the database or disk may be what failed
            self.log.exception("could not record the failed run")

    def _finish(self, envelope: ResultEnvelope, output: str | None, code: int) -> TaskOutcome:
        text = to_json(envelope)
        self._write(self.run_dir / "envelope.json", text)
        db.record_run_end(
            self.conn,
            self.run_id,
            status=envelope.status,
            provider=envelope.provider,
            model=envelope.model,
            tier=envelope.tier,
            attempts=envelope.attempts,
            finished_at=self.now(),
            duration_s=envelope.duration_s,
            worker_output_tokens=envelope.usage.completion_tokens,
            envelope_chars=len(text),
        )
        self.log.info(
            "finished status=%s exit=%s attempts=%d", envelope.status, code, self.attempts
        )
        return TaskOutcome(envelope, output, code, tuple(self.prep.warnings))
