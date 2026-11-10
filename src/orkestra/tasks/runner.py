"""Run lifecycle. Current version (Faz 4): ``ask`` through the router with retries.

1. Prepare: schema, context, secret scan, prompt.
2. Route (``routing/router.py``): ordered candidates; every left-out provider has a reason.
   ``--dry-run`` stops here.
3. Try the candidates in order. Per candidate: reserve budget → request → settle budget,
   update the circuit breaker. Transient errors are retried on the same candidate with
   backoff; other errors move on (``routing/retry.py``). Every abandoned candidate is
   listed in the envelope's ``failovers`` (and in ``escalations`` when the next one is on a
   higher tier).

Every run gets ``runs/<run_id>/`` with ``task.yaml``, ``attempts/<n>/request.json``,
``attempts/<n>/response.txt``, ``output.md``, ``envelope.json`` and ``orkestra.log``
(Mimari §3, §14). Everything written there is redacted.
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

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from orkestra import paths
from orkestra.config.loader import dump_yaml
from orkestra.config.schema import Config
from orkestra.envelope import (
    EnvelopeUsage,
    Escalation,
    Failover,
    ResultEnvelope,
    VerificationResult,
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
from orkestra.tasks.prompts import build_ask_messages

ASK_TASK_ID = "ask"

Sleep = Callable[[float], Awaitable[None]]


async def _sleep(seconds: float) -> None:
    """Retry backoff wait; tests replace it so they never really wait."""
    await asyncio.sleep(seconds)


def new_run_id(now: datetime | None = None, token: str | None = None) -> str:
    """``YYYYMMDD-HHMMSS-<4 hex>``: sortable and practically collision free."""
    moment = datetime.now() if now is None else now
    return f"{moment:%Y%m%d-%H%M%S}-{token or secrets.token_hex(2)}"


@dataclass(frozen=True)
class AskRequest:
    prompt: str
    provider: str | None = None
    model: str | None = None
    tier: int | None = None
    profile: str | None = None
    local_only: bool = False
    context: Sequence[Path] = ()
    schema: Path | None = None
    allow_secrets: bool = False


@dataclass(frozen=True)
class AskOutcome:
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


def _load_schema(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as exc:
        raise UsageError(t("ask.error.schema", path=path, reason=exc)) from exc
    if not isinstance(schema, dict):
        raise UsageError(t("ask.error.schema", path=path, reason=t("ask.error.schema_not_object")))
    return schema


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1])
    return stripped


def _check_json(text: str, schema: dict[str, Any]) -> VerificationResult:
    try:
        value = json.loads(_strip_fences(text))
    except ValueError as exc:
        return VerificationResult(
            type="json_schema", ok=False, detail=t("ask.verify.not_json", reason=exc)
        )
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "$"
        return VerificationResult(
            type="json_schema", ok=False, detail=f"{where}: {first.message}"[:300]
        )
    return VerificationResult(type="json_schema", ok=True)


PROMPT_SOURCE = "<prompt>"  # where a finding in the prompt text itself is reported
CANNOT_DO = "CANNOT_DO:"  # worker protocol (prompts/worker_system.md, Mimari §8.1)


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
    request: AskRequest
    config: Config
    env: Mapping[str, str]
    schema: dict[str, Any] | None
    context: Context
    redact: Redactor  # records and logs: everything that looks secret
    redact_output: Redactor  # the answer: secrets only, so "password: changeme" stays intact
    findings: list[Finding]
    warnings: list[str]
    system: str
    user: str

    def needs(self) -> TaskNeeds:
        return TaskNeeds(
            kind="ask",
            tier=self.request.tier or 1,
            privacy="local_only" if self.request.local_only else "normal",
            provider=self.request.provider,
            model=self.request.model,
            prompt_chars=len(self.system) + len(self.user),
            has_secrets=bool(blocking(self.findings)),
            allow_secrets=self.request.allow_secrets,
        )


def _prepare(
    request: AskRequest, config: Config, env: Mapping[str, str], cwd: Path | None
) -> _Prepared:
    schema = _load_schema(request.schema)
    context = collect_context(request.context, max_bytes=config.security.max_context_bytes, cwd=cwd)
    known = configured_secrets(config, env)
    findings = _scan(request.prompt, context, known)
    warnings = [t("context.warning.binary", path=p) for p in context.skipped_binary]
    warnings += [
        t("secrets.warning.found_prompt", line=f.line, kind=f.kind)
        if f.path == PROMPT_SOURCE
        else t("secrets.warning.found", path=f.path, line=f.line, kind=f.kind)
        for f in findings
    ]
    system, user = build_ask_messages(request.prompt, context, schema)
    return _Prepared(
        request, config, env, schema, context, Redactor(known), Redactor(known, passwords=False),
        findings, warnings, system, user,
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
    if needs.provider is not None and needs.provider not in prep.config.providers:
        return route(needs, prep.config, Snapshot(moment), profile=prep.request.profile)  # error
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
    return route(needs, prep.config, snapshot, profile=prep.request.profile)


async def plan_ask(
    request: AskRequest,
    config: Config,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    now: db.Clock = db.local_now,
    conn: sqlite3.Connection | None = None,
) -> DryRun:
    """``ask --dry-run``: the route only, no request, no budget, no run directory."""
    env = os.environ if environ is None else environ
    prep = _prepare(request, config, env, cwd)
    state = db.connect() if conn is None else conn
    try:
        planned = await _route(prep, state, now(), fetch_prices=False)
        return DryRun(planned, tuple(prep.warnings))
    finally:
        if conn is None:
            state.close()


async def run_ask(
    request: AskRequest,
    config: Config,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    now: db.Clock = db.local_now,
    conn: sqlite3.Connection | None = None,
    sleep: Sleep | None = None,
    rand: Callable[[], float] = random.random,
    policy: retry.RetryPolicy | None = None,
) -> AskOutcome:
    env = os.environ if environ is None else environ
    prep = _prepare(request, config, env, cwd)
    state = db.connect() if conn is None else conn
    try:
        started_at = now()
        planned = await _route(prep, state, started_at, fetch_prices=True)
        if not planned.candidates:
            raise planned.error()
        runner = _AskRun(prep, state, planned, started_at, now, clock, sleep or _sleep, rand,
                         policy or retry.RetryPolicy())  # fmt: skip
        return await runner.run()
    finally:
        if conn is None:
            state.close()


class _AskRun:
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
        # daily_runs is per provider: one run each, however many requests it takes there.
        self.run_counted: set[str] = set()
        self.cannot_do: str | None = None  # last CANNOT_DO reason from a worker
        self.failovers: list[Failover] = []
        self.escalations: list[Escalation] = []
        self.log = logging.getLogger("orkestra")
        self.started = clock()

    def _write(self, path: Path, text: str, *, answer: bool = False) -> None:
        """Write a run record, redacted. ``answer``: the worker's output (secrets only)."""
        redact = self.prep.redact_output if answer else self.prep.redact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(redact(text).encode("utf-8"))  # bytes: no newline translation

    def _max_output(self, candidate: Candidate) -> int:
        return candidate.model.max_output_tokens or self.prep.config.defaults.max_output_tokens

    def _completion(self, candidate: Candidate) -> CompletionRequest:
        return CompletionRequest(
            model=candidate.model.id,
            system=self.prep.system,
            user=self.prep.user,
            max_output_tokens=self._max_output(candidate),
            json_mode=self.prep.schema is not None,
            timeout_s=request_timeout(candidate.config, self.prep.config.defaults),
        )

    async def run(self) -> AskOutcome:
        db.record_run_start(
            self.conn, run_id=self.run_id, task_id=ASK_TASK_ID, kind="ask",
            started_at=self.started_at,
        )  # fmt: skip
        with run_log(self.run_dir, self.prep.redact) as log:
            self.log = log
            try:
                return await self._run()
            except BaseException as exc:
                # Ctrl+C or a bug: still close the run row and leave an envelope behind.
                self._crashed(exc)
                raise

    async def _run(self) -> AskOutcome:
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
            if isinstance(outcome, AskOutcome):
                return outcome
            action = outcome
            if action is retry.Action.SKIP_PROVIDER:
                skipped_providers.add(candidate.provider)
            elif action is retry.Action.BIGGER_CONTEXT:
                window = candidate.model.context_window
                remaining = [c for c in remaining if c.model.context_window > window]
            elif action is retry.Action.ESCALATE:
                remaining = [c for c in remaining if c.tier > candidate.tier]
        if self.cannot_do is not None:
            return self._escalate()
        return self._all_failed()

    def _write_task(self) -> None:
        req = self.prep.request
        self._write(
            self.run_dir / "task.yaml",
            dump_yaml(
                {
                    "id": ASK_TASK_ID,
                    "kind": "ask",
                    "tier": req.tier or 1,
                    "prompt": req.prompt,
                    "context": {"files": [f.display for f in self.prep.context.files]},
                    "output": {
                        "format": "json" if self.prep.schema is not None else "text",
                        "schema": str(req.schema) if req.schema else None,
                    },
                    "provider": req.provider,
                    "model": req.model,
                    "privacy": "local_only" if req.local_only else "normal",
                    "profile": self.route.profile,
                }
            ),
        )

    def _prompt_chars(self) -> int:
        return len(self.prep.system) + len(self.prep.user)

    async def _try(self, candidate: Candidate) -> AskOutcome | retry.Action:
        """One candidate, with transport retries. Returns the outcome or what to do next."""
        provider = create_chat_provider(candidate.provider, candidate.config, self.prep.env)
        completion = self._completion(candidate)
        if candidate.config.budget.daily_usd is not None and candidate.price is None:
            self.prep.warnings.append(
                t("budget.warning.no_price", provider=candidate.provider, model=candidate.model.id)
            )
        tries = 0
        while True:
            amount = budget.estimate(
                self._prompt_chars(), completion.max_output_tokens, candidate.price,
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
                action = retry.classify(exc)
                if action is retry.Action.RETRY and not state.is_open(self.now()):
                    wait = retry.delay(tries, exc, self.policy, self.rand)
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
            usage = self._actual_usage(candidate, result)
            budget.settle(
                self.conn, reservation, prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens, cost_usd=usage.cost_usd,
                estimated=usage.estimated, now=self.now(),
            )  # fmt: skip
            health.record_success(self.conn, candidate.provider)
            reason = _cannot_do(result.text)
            if reason is not None:
                self._write(attempt_dir / "response.txt", result.text, answer=True)
                self.cannot_do = reason
                return self._fail(candidate, None, tries, retry.Action.ESCALATE, reason=reason)
            return self._succeed(candidate, completion, result, usage, attempt_dir)

    def _actual_usage(self, candidate: Candidate, result: CompletionResult) -> Usage:
        """What the request used, for the budget and the envelope.

        Tokens the provider did not report are estimated from the text; a cost it did not
        report is priced with the model's resolved price (config, price list or history).
        """
        reported = result.usage
        estimated = reported.estimated
        prompt = reported.prompt_tokens
        completion = reported.completion_tokens
        if prompt is None:
            prompt, estimated = estimate_tokens(self._prompt_chars()), True
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
    ) -> retry.Action:
        """Record an abandoned candidate. ``exc`` is ``None`` for a worker's CANNOT_DO."""
        error = type(exc).__name__ if exc is not None else "CannotDo"
        message = exc.message if exc is not None else t("ask.cannot_do", reason=reason or "-")
        self.failovers.append(
            Failover(
                provider=candidate.provider,
                model=candidate.model.id,
                tier=candidate.tier,
                error=error,
                reason=self.prep.redact(message),
                attempts=tries,
            )
        )
        self.log.warning("giving up on %s: %s → %s", candidate.label, error, action.value)
        return action

    def _base(self, candidate: Candidate | None) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": ASK_TASK_ID,
            "provider": candidate.provider if candidate else None,
            "model": candidate.model.id if candidate else None,
            "tier": candidate.tier if candidate else None,
            "attempts": self.attempts,
            "escalations": self.escalations,
            "failovers": self.failovers,
        }

    def _succeed(
        self,
        candidate: Candidate,
        completion: CompletionRequest,
        result: CompletionResult,
        usage: Usage,
        attempt_dir: Path,
    ) -> AskOutcome:
        # Files and the terminal get the answer with real secrets masked; the schema check
        # sees the answer itself, so masking can never break valid JSON.
        text = self.prep.redact_output(result.text)
        output_path = self.run_dir / "output.md"
        self._write(attempt_dir / "response.txt", text, answer=True)
        self._write(output_path, text, answer=True)
        if result.raw_finish_reason == "length":
            self.prep.warnings.append(
                t("ask.warning.truncated", tokens=completion.max_output_tokens)
            )
            self.log.warning("output hit max_output_tokens=%d", completion.max_output_tokens)
        schema = self.prep.schema
        verification = [_check_json(result.text, schema)] if schema is not None else []
        ok = all(v.ok for v in verification)
        envelope = ResultEnvelope(
            **self._base(candidate),
            status="ok" if ok else "failed",
            summary=summarize_text(self.prep.redact(text), str(output_path)),
            verification=verification,
            output_path=str(output_path),
            usage=EnvelopeUsage(
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                cost_usd=usage.cost_usd,
            ),
            duration_s=self._duration(),
        )
        return self._finish(envelope, text, 0 if ok else int(ExitCode.TASK_FAILED))

    def _duration(self) -> float:
        return round(self.clock() - self.started, 3)

    def _escalate(self) -> AskOutcome:
        """Workers said CANNOT_DO and no higher tier was left (or answered): exit code 1."""
        reason = t("ask.cannot_do", reason=self.cannot_do or "-")
        envelope = ResultEnvelope(
            **self._base(None),
            status="escalate",
            summary=self.prep.redact(reason),
            duration_s=self._duration(),
        )
        return self._finish(envelope, None, int(ExitCode.TASK_FAILED))

    def _all_failed(self) -> AskOutcome:
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

    def _finish(self, envelope: ResultEnvelope, output: str | None, code: int) -> AskOutcome:
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
        return AskOutcome(envelope, output, code, tuple(self.prep.warnings))
