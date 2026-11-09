"""Run lifecycle. First version (Faz 2): a single ``ask`` attempt, no router, no retries.

Every run gets ``runs/<run_id>/`` with ``task.yaml``, ``attempts/1/request.json``,
``attempts/1/response.txt``, ``output.md`` and ``envelope.json`` (Mimari §3).
"""

from __future__ import annotations

import json
import os
import secrets
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
from orkestra.config.schema import Config
from orkestra.envelope import (
    EnvelopeUsage,
    ResultEnvelope,
    VerificationResult,
    summarize_text,
)
from orkestra.errors import ExitCode, ProviderError, UsageError, exit_code_for
from orkestra.i18n import t
from orkestra.providers.base import CompletionRequest
from orkestra.providers.registry import select_chat_target
from orkestra.tasks.context import collect_context
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


@dataclass(frozen=True)
class AskOutcome:
    envelope: ResultEnvelope
    output: str | None
    exit_code: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))  # bytes: no newline translation on Windows


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


async def run_ask(
    request: AskRequest,
    config: Config,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> AskOutcome:
    env = os.environ if environ is None else environ
    schema = _load_schema(request.schema)
    context = collect_context(request.context, max_bytes=config.security.max_context_bytes, cwd=cwd)
    target = select_chat_target(
        config, provider=request.provider, model=request.model, tier=request.tier, environ=env
    )
    warnings = [t("context.warning.binary", path=p) for p in context.skipped_binary]
    system, user = build_ask_messages(request.prompt, context, schema)

    run_id = new_run_id()
    run_dir = paths.run_dir(run_id)
    output_path = run_dir / "output.md"
    _write(
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
            }
        ),
    )
    completion = CompletionRequest(
        model=target.model.id,
        system=system,
        user=user,
        max_output_tokens=target.model.max_output_tokens or config.defaults.max_output_tokens,
        json_mode=schema is not None,
        timeout_s=target.config.timeout_s or config.defaults.timeout_s,
    )
    attempt_dir = run_dir / "attempts" / "1"
    _write(attempt_dir / "request.json", json.dumps(asdict(completion), indent=2))

    base = {
        "run_id": run_id,
        "task_id": ASK_TASK_ID,
        "provider": target.name,
        "model": target.model.id,
        "tier": target.model.tier,
        "attempts": 1,
    }
    started = clock()
    try:
        result = await target.provider.complete(completion)
    except ProviderError as exc:
        envelope = ResultEnvelope(
            **base, status="error", error=exc.message, duration_s=round(clock() - started, 3)
        )
        _write(run_dir / "envelope.json", envelope.model_dump_json(indent=2))
        return AskOutcome(envelope, None, exit_code_for(exc), tuple(warnings))
    duration = round(clock() - started, 3)

    _write(attempt_dir / "response.txt", result.text)
    _write(output_path, result.text)
    if result.raw_finish_reason == "length":
        warnings.append(t("ask.warning.truncated", tokens=completion.max_output_tokens))

    verification = [_check_json(result.text, schema)] if schema is not None else []
    ok = all(v.ok for v in verification)
    envelope = ResultEnvelope(
        **base,
        status="ok" if ok else "failed",
        summary=summarize_text(result.text, str(output_path)),
        verification=verification,
        output_path=str(output_path),
        usage=EnvelopeUsage(
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            cost_usd=result.usage.cost_usd,
        ),
        duration_s=duration,
    )
    _write(run_dir / "envelope.json", envelope.model_dump_json(indent=2))
    return AskOutcome(
        envelope, result.text, 0 if ok else int(ExitCode.TASK_FAILED), tuple(warnings)
    )
