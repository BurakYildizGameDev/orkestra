"""Result envelope (Mimari §13): the short JSON the chief reads instead of the full output.

This model is the single source of truth for the envelope schema. Changing it means bumping
``ENVELOPE_VERSION``.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from orkestra.config.schema import EditFormat
from orkestra.i18n import t

ENVELOPE_VERSION = 3  # 2: failovers (Faz 4); 3: edit_format (Faz 9c)
SUMMARY_CHARS = 400

Status = Literal["ok", "failed", "escalate", "error"]


class Escalation(BaseModel):
    provider: str
    model: str
    tier: int
    reason: str


class Failover(BaseModel):
    """A candidate that failed at runtime; the run moved on to the next one."""

    provider: str
    model: str
    tier: int
    error: str  # error class, e.g. ProviderTransient
    reason: str  # human message, selected language
    attempts: int


class VerificationResult(BaseModel):
    type: str
    ok: bool
    detail: str = ""


class Changes(BaseModel):
    files: int
    insertions: int
    deletions: int
    patch_path: str | None = None


class EnvelopeUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None


class ResultEnvelope(BaseModel):
    envelope_version: Literal[2, 3] = ENVELOPE_VERSION  # stored version-2 envelopes still load
    run_id: str
    task_id: str
    status: Status
    provider: str | None = None
    model: str | None = None
    tier: int | None = None
    edit_format: EditFormat | None = None  # API edits only (Faz 9c)
    attempts: int = 0
    escalations: list[Escalation] = Field(default_factory=list)
    failovers: list[Failover] = Field(default_factory=list)
    summary: str = ""
    verification: list[VerificationResult] = Field(default_factory=list)
    changes: Changes | None = None
    output_path: str | None = None
    usage: EnvelopeUsage = Field(default_factory=EnvelopeUsage)
    duration_s: float = 0.0
    cached: bool = False
    review: dict[str, Any] | None = None
    error: str | None = None


def to_json(envelope: ResultEnvelope) -> str:
    # ASCII escapes keep the document intact on non-UTF-8 Windows pipes.
    return json.dumps(envelope.model_dump(mode="json"), indent=2)


def summarize_text(text: str, output_path: str | None, limit: int = SUMMARY_CHARS) -> str:
    """First ``limit`` characters cut at a word boundary, plus where the full text is."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    suffix = t("envelope.full_text", path=output_path) if output_path else ""
    return f"{cut}… {suffix}".rstrip()


def human_summary(envelope: ResultEnvelope) -> str:
    """Short status lines for humans (stderr)."""
    usage = envelope.usage
    cost = "-" if usage.cost_usd is None else f"${usage.cost_usd:.4f}"
    lines = [
        t(
            "envelope.line",
            status=envelope.status,
            run_id=envelope.run_id,
            provider=envelope.provider or "-",
            model=envelope.model or "-",
            tier=envelope.tier if envelope.tier is not None else "-",
        ),
        t(
            "envelope.usage",
            prompt=usage.prompt_tokens if usage.prompt_tokens is not None else "-",
            completion=usage.completion_tokens if usage.completion_tokens is not None else "-",
            cost=cost,
            seconds=f"{envelope.duration_s:.1f}",
        ),
    ]
    lines.extend(
        t(
            "envelope.verify",
            type=v.type,
            result=t("envelope.verify.ok" if v.ok else "envelope.verify.fail"),
            detail=v.detail,
        ).rstrip()
        for v in envelope.verification
    )
    lines.extend(
        t("envelope.failover", provider=f.provider, model=f.model, reason=f.reason)
        for f in envelope.failovers
    )
    if envelope.changes is not None and envelope.changes.files:
        # Only a change that passed its checks gets the apply hint.
        key = "envelope.changes" if envelope.status == "ok" else "envelope.changes_unverified"
        lines.append(
            t(key, files=envelope.changes.files, insertions=envelope.changes.insertions,
              deletions=envelope.changes.deletions, run_id=envelope.run_id)
        )  # fmt: skip
    if envelope.error:
        lines.append(t("errors.prefix", message=envelope.error))
    return "\n".join(lines)


def stored_summary(data: Any) -> str:
    """``human_summary`` of a stored envelope; an older or damaged one is shown as JSON."""
    try:
        return human_summary(ResultEnvelope.model_validate(data))
    except ValidationError:
        return json.dumps(data, indent=2, ensure_ascii=False)
