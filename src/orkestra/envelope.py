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

ENVELOPE_VERSION = 4  # 2: failovers (Faz 4); 3: edit_format (Faz 9c); 4: review (Faz 8b)
SUMMARY_CHARS = 400

Status = Literal["ok", "failed", "escalate", "error"]


class EnvelopeReview(BaseModel):
    risk: str
    flags_count: int


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
    envelope_version: Literal[2, 3, 4] = ENVELOPE_VERSION  # stored version-2/3 envelopes still load
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
    review: EnvelopeReview | None = None
    error: str | None = None


BATCH_VERSION = 1
BatchStatus = Literal["ok", "failed", "escalate", "error", "skipped"]


class BatchItem(BaseModel):
    """One task of a batch: its envelope, or why it has none (skipped, failed to start)."""

    task_id: str
    status: BatchStatus
    exit_code: int
    run_id: str | None = None
    envelope: ResultEnvelope | None = None
    error: str | None = None  # skipped: why; error: what went wrong


class BatchTotals(BaseModel):
    ok: int = 0
    failed: int = 0
    escalate: int = 0
    error: int = 0
    skipped: int = 0
    cost_usd: float | None = None  # None when no task reported a cost


class BatchEnvelope(BaseModel):
    """``orkestra batch --json``: one document for the whole batch (Mimari §13)."""

    batch_version: Literal[1] = BATCH_VERSION
    batch_id: str
    results: list[BatchItem] = Field(default_factory=list)
    totals: BatchTotals = Field(default_factory=BatchTotals)
    warnings: list[str] = Field(default_factory=list)
    duration_s: float = 0.0


ESTIMATE_VERSION = 1


class EstimateItem(BaseModel):
    """One task of ``batch --estimate``: its first request, or why it cannot run."""

    task_id: str
    provider: str | None = None
    model: str | None = None
    tier: int | None = None
    prompt_tokens: int = 0
    max_output_tokens: int | None = None  # None: a code agent
    cost_usd: float | None = None  # None: no price (code agent, model without a price)
    agent: bool = False  # a code agent: no USD price (the user's own quota)
    exit_code: int = 0  # the task's exit code if it cannot run
    error: str | None = None


class EstimateTotals(BaseModel):
    tasks: int = 0
    tokens: int = 0  # prompt + output limit of every task that can run
    cost_usd: float = 0.0  # tasks with a price only
    unpriced: int = 0
    unpriced_remote: int = 0  # paid models without a known price: need confirmation
    cannot_run: int = 0


class BatchEstimate(BaseModel):
    """``orkestra batch --estimate --json`` (and a batch stopped for its cost) (Faz 7b)."""

    estimate_version: Literal[1] = ESTIMATE_VERSION
    results: list[EstimateItem] = Field(default_factory=list)
    totals: EstimateTotals = Field(default_factory=EstimateTotals)
    confirm_above_usd: float | None = None
    needs_confirmation: bool = False  # the total is above confirm_above_usd
    warnings: list[str] = Field(default_factory=list)


def to_json(envelope: ResultEnvelope | BatchEnvelope | BatchEstimate) -> str:
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


def batch_line(item: BatchItem) -> str:
    """One task of a batch, for humans (progress on stderr, and the final list)."""
    env = item.envelope
    where = f"{env.provider}/{env.model}" if env is not None and env.provider else "-"
    detail = item.error or (env.summary if env is not None else "") or ""
    return t(
        "batch.line", status=item.status, id=item.task_id, where=where,
        run_id=item.run_id or "-", detail=" ".join(detail.split())[:120],
    ).rstrip()  # fmt: skip


def _usd(cost: float | None) -> str:
    return "-" if cost is None else f"${cost:.4f}"


def estimate_summary(document: BatchEstimate) -> str:
    """``batch --estimate`` for humans: one line per task, then the total."""
    lines = [t("batch.estimate.header", count=document.totals.tasks)]
    for item in document.results:
        if item.error is not None:
            lines.append(t("batch.estimate.line_error", id=item.task_id, error=item.error))
            continue
        tokens = item.prompt_tokens + (item.max_output_tokens or 0)
        lines.append(t(
            "batch.estimate.line", id=item.task_id, where=f"{item.provider}/{item.model}",
            tokens=tokens, cost=_usd(item.cost_usd),
        ))  # fmt: skip
    totals = document.totals
    lines.append(t("batch.estimate.totals", tokens=totals.tokens, cost=_usd(totals.cost_usd)))
    if totals.unpriced:
        lines.append(t("batch.estimate.unpriced", count=totals.unpriced))
    if totals.unpriced_remote:
        lines.append(t("batch.estimate.unpriced_remote", count=totals.unpriced_remote))
    return "\n".join(lines)


def batch_summary(document: BatchEnvelope) -> str:
    """The whole batch for humans: one line per task, then the totals."""
    totals = document.totals
    cost = "-" if totals.cost_usd is None else f"${totals.cost_usd:.4f}"
    lines = [t("batch.header", batch_id=document.batch_id)]
    lines += [batch_line(item) for item in document.results]
    lines.append(
        t(
            "batch.totals", ok=totals.ok, failed=totals.failed, escalate=totals.escalate,
            error=totals.error, skipped=totals.skipped, cost=cost,
            seconds=f"{document.duration_s:.1f}",
        )
    )  # fmt: skip
    return "\n".join(lines)


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
    if envelope.review is not None:
        lines.append(
            t("envelope.review", risk=envelope.review.risk, count=envelope.review.flags_count)
        )
    if envelope.error:
        lines.append(t("errors.prefix", message=envelope.error))
    return "\n".join(lines)


def stored_summary(data: Any) -> str:
    """``human_summary`` of a stored envelope; an older or damaged one is shown as JSON."""
    try:
        return human_summary(ResultEnvelope.model_validate(data))
    except ValidationError:
        return json.dumps(data, indent=2, ensure_ascii=False)
