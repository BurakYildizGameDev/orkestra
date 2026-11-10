"""Run lifecycle. Current version (Faz 3): a single ``ask`` attempt, no router, no retries.

Before a provider is chosen every candidate must have consent, a closed circuit, room in its
daily budget and, if it is remote, a context without secrets. The request is paid for through
a budget reservation that is settled afterwards; the outcome updates the circuit breaker.

Every run gets ``runs/<run_id>/`` with ``task.yaml``, ``attempts/1/request.json``,
``attempts/1/response.txt``, ``output.md``, ``envelope.json`` and ``orkestra.log``
(Mimari §3, §14). Everything written there is redacted.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from orkestra import paths
from orkestra.config.loader import dump_yaml
from orkestra.config.schema import Config, ModelSpec
from orkestra.envelope import (
    EnvelopeUsage,
    ResultEnvelope,
    VerificationResult,
    summarize_text,
    to_json,
)
from orkestra.errors import BudgetExhausted, ExitCode, ProviderError, UsageError, exit_code_for
from orkestra.i18n import t
from orkestra.logging_setup import run_log
from orkestra.providers import pricing
from orkestra.providers.base import CompletionRequest
from orkestra.providers.registry import CandidateCheck, ChatConfig, Rejection, select_chat_target
from orkestra.security.redact import Redactor, configured_secrets
from orkestra.security.secrets_scan import Finding, blocking, scan_text
from orkestra.state import budget, consent, db, health
from orkestra.tasks.context import Context, collect_context
from orkestra.tasks.prompts import build_ask_messages

ASK_TASK_ID = "ask"


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
    context: Sequence[Path] = ()
    schema: Path | None = None
    allow_secrets: bool = False


@dataclass(frozen=True)
class AskOutcome:
    envelope: ResultEnvelope
    output: str | None
    exit_code: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _load_schema(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as exc:
        raise UsageError(t("ask.error.schema", path=path, reason=exc)) from exc
    if not isinstance(schema, dict):
        raise UsageError(t("ask.error.schema", path=path, reason="not an object"))
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


# --- candidate checks ------------------------------------------------------------------


def _max_output(config: Config, model: ModelSpec) -> int:
    return model.max_output_tokens or config.defaults.max_output_tokens


def state_checks(
    conn: sqlite3.Connection,
    config: Config,
    *,
    now: datetime,
    prompt_chars: int,
    secret_findings: Sequence[Finding],
    allow_secrets: bool,
    price_cache: Mapping[str, Any],
) -> list[CandidateCheck]:
    """Consent, circuit breaker, secrets (remote only) and budget, in that order."""
    blockers = blocking(secret_findings)

    def needs_consent(name: str, cfg: ChatConfig, _: ModelSpec) -> Rejection | None:
        current = consent.state(conn, name, cfg)
        if current == "granted":
            return None
        key = "select.reason.consent_changed" if current == "changed" else "select.reason.consent"
        return Rejection(t(key, name=name), consent=True)

    def circuit_open(name: str, _cfg: ChatConfig, _model: ModelSpec) -> Rejection | None:
        state = health.get(conn, name)
        if not state.is_open(now):
            return None
        until = state.open_until.strftime("%H:%M") if state.open_until else "?"
        return Rejection(
            t("select.reason.circuit_open", name=name, until=until, error=state.last_error or "-")
        )

    def secrets_to_remote(name: str, cfg: ChatConfig, _: ModelSpec) -> Rejection | None:
        if not blockers or cfg.local or allow_secrets:
            return None
        files = ", ".join(sorted({f.path for f in blockers}))
        return Rejection(t("select.reason.secrets", name=name, files=files))

    def over_budget(name: str, cfg: ChatConfig, model: ModelSpec) -> Rejection | None:
        price = pricing.resolve(name, cfg, model, conn=conn, cache=price_cache)
        amount = budget.estimate(prompt_chars, _max_output(config, model), price)
        limit = budget.check(conn, name, cfg.budget, amount, now)
        return Rejection(t("select.reason.budget", name=name, limit=limit)) if limit else None

    return [needs_consent, circuit_open, secrets_to_remote, over_budget]


def _scan(context: Context, known: Sequence[str]) -> list[Finding]:
    findings: list[Finding] = []
    for f in context.files:
        findings.extend(scan_text(f.display, f.text, known))
    return findings


# --- run -------------------------------------------------------------------------------


async def run_ask(
    request: AskRequest,
    config: Config,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    now: db.Clock = db.local_now,
    conn: sqlite3.Connection | None = None,
) -> AskOutcome:
    env = os.environ if environ is None else environ
    schema = _load_schema(request.schema)
    context = collect_context(request.context, max_bytes=config.security.max_context_bytes, cwd=cwd)
    known = configured_secrets(config, env)
    redact = Redactor(known)
    findings = _scan(context, known)
    warnings = [t("context.warning.binary", path=p) for p in context.skipped_binary]
    warnings += [
        t("secrets.warning.found", path=f.path, line=f.line, kind=f.kind) for f in findings
    ]
    system, user = build_ask_messages(request.prompt, context, schema)

    own_conn = conn is None
    state = db.connect() if conn is None else conn
    try:
        return await _run(
            request, config, state, env, now, clock, redact, findings, warnings, context,
            schema, system, user,
        )  # fmt: skip
    finally:
        if own_conn:
            state.close()


async def _run(
    request: AskRequest,
    config: Config,
    conn: sqlite3.Connection,
    env: Mapping[str, str],
    now: db.Clock,
    clock: Callable[[], float],
    redact: Redactor,
    findings: list[Finding],
    warnings: list[str],
    context: Context,
    schema: dict[str, Any] | None,
    system: str,
    user: str,
) -> AskOutcome:
    started_at = now()
    price_cache = await pricing.refresh(config, started_at, environ=env)
    target = select_chat_target(
        config,
        provider=request.provider,
        model=request.model,
        tier=request.tier,
        environ=env,
        checks=state_checks(
            conn,
            config,
            now=started_at,
            prompt_chars=len(system) + len(user),
            secret_findings=findings,
            allow_secrets=request.allow_secrets,
            price_cache=price_cache,
        ),
    )
    price = pricing.resolve(target.name, target.config, target.model, conn=conn, cache=price_cache)
    if target.config.budget.daily_usd is not None and price is None:
        warnings.append(t("budget.warning.no_price", provider=target.name, model=target.model.id))
    run_id = new_run_id(started_at.replace(tzinfo=None))
    run_dir = paths.run_dir(run_id)
    output_path = run_dir / "output.md"
    attempt_dir = run_dir / "attempts" / "1"

    def write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(redact(text).encode("utf-8"))  # bytes: no newline translation

    db.record_run_start(conn, run_id=run_id, task_id=ASK_TASK_ID, kind="ask", started_at=started_at)
    completion = CompletionRequest(
        model=target.model.id,
        system=system,
        user=user,
        max_output_tokens=_max_output(config, target.model),
        json_mode=schema is not None,
        timeout_s=target.config.timeout_s or config.defaults.timeout_s,
    )
    base: dict[str, Any] = {
        "run_id": run_id,
        "task_id": ASK_TASK_ID,
        "provider": target.name,
        "model": target.model.id,
        "tier": target.model.tier,
        "attempts": 1,
    }

    def finish(envelope: ResultEnvelope, output: str | None, code: int) -> AskOutcome:
        text = to_json(envelope)
        write(run_dir / "envelope.json", text)
        db.record_run_end(
            conn,
            run_id,
            status=envelope.status,
            provider=envelope.provider,
            model=envelope.model,
            tier=envelope.tier,
            attempts=envelope.attempts,
            finished_at=now(),
            duration_s=envelope.duration_s,
            worker_output_tokens=envelope.usage.completion_tokens,
            envelope_chars=len(text),
        )
        log.info("finished status=%s exit=%s", envelope.status, code)
        return AskOutcome(envelope, output, code, tuple(warnings))

    with run_log(run_dir, redact) as log:
        log.info(
            "run %s: provider=%s model=%s tier=%s",
            run_id,
            target.name,
            target.model.id,
            target.model.tier,
        )
        if findings:
            log.warning(
                "secret findings in context: %d (blocking %d)",
                len(findings),
                len(blocking(findings)),
            )
        write(
            run_dir / "task.yaml",
            dump_yaml(
                {
                    "id": ASK_TASK_ID,
                    "kind": "ask",
                    "tier": target.model.tier,
                    "prompt": request.prompt,
                    "context": {"files": [f.display for f in context.files]},
                    "output": {
                        "format": "json" if schema is not None else "text",
                        "schema": str(request.schema) if request.schema else None,
                    },
                    "provider": target.name,
                    "model": target.model.id,
                    "privacy": "normal",
                }
            ),
        )
        write(attempt_dir / "request.json", json.dumps(asdict(completion), indent=2))

        amount = budget.estimate(len(system) + len(user), completion.max_output_tokens, price)
        log.info(
            "estimate: %d tokens, $%.6f (price source: %s)",
            amount.tokens, amount.cost_usd, price.source if price else "none",
        )  # fmt: skip
        try:
            reservation = budget.reserve(
                conn, provider=target.name, model=target.model.id, run_id=run_id,
                budget=target.config.budget, amount=amount, now=now(),
            )  # fmt: skip
        except BudgetExhausted as exc:
            log.warning("budget exhausted: %s", exc.message)
            return finish(
                ResultEnvelope(**base, status="error", error=exc.message), None, exit_code_for(exc)
            )

        started = clock()
        try:
            result = await target.provider.complete(completion)
        except ProviderError as exc:
            budget.settle(
                conn, reservation, prompt_tokens=0, completion_tokens=0, cost_usd=0.0,
                estimated=False, now=now(),
            )  # fmt: skip
            state_after = health.record_failure(conn, target.name, exc, now())
            log.warning(
                "provider error %s: %s (consecutive failures: %d)",
                type(exc).__name__, exc.message, state_after.consecutive_failures,
            )  # fmt: skip
            envelope = ResultEnvelope(
                **base,
                status="error",
                error=redact(exc.message),
                duration_s=round(clock() - started, 3),
            )
            return finish(envelope, None, exit_code_for(exc))
        except BaseException:
            budget.release(conn, reservation)  # interrupted: nothing to pay for
            log.warning("interrupted; reservation released")
            raise
        duration = round(clock() - started, 3)
        budget.settle(
            conn, reservation, prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens, cost_usd=result.usage.cost_usd,
            estimated=result.usage.estimated, now=now(),
        )  # fmt: skip
        health.record_success(conn, target.name)

        text = redact(result.text)
        write(attempt_dir / "response.txt", text)
        write(output_path, text)
        if result.raw_finish_reason == "length":
            warnings.append(t("ask.warning.truncated", tokens=completion.max_output_tokens))
            log.warning("output hit max_output_tokens=%d", completion.max_output_tokens)

        verification = [_check_json(text, schema)] if schema is not None else []
        ok = all(v.ok for v in verification)
        envelope = ResultEnvelope(
            **base,
            status="ok" if ok else "failed",
            summary=summarize_text(text, str(output_path)),
            verification=verification,
            output_path=str(output_path),
            usage=EnvelopeUsage(
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                cost_usd=result.usage.cost_usd,
            ),
            duration_s=duration,
        )
        return finish(envelope, text, 0 if ok else int(ExitCode.TASK_FAILED))
