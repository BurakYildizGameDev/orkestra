"""``orkestra show RUN --report``: the run as a short report to the chief (Faz 13m, D-098).

A few lines instead of the diff: what was done, what was checked, how much changed, what an
independent review said, where to look, and the one command to run next. The chief reads
the diff only when the report sends it there. ``next`` suggests ``apply --max-risk low``
only when that command would apply it: checks passed, an independent review, low risk and no
flags (``workspace.service.risk_problem``); nothing for a run already applied or discarded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from orkestra.envelope import ResultEnvelope
from orkestra.errors import UsageError
from orkestra.i18n import t
from orkestra.workspace import git_worktree as gw
from orkestra.workspace import service

SUMMARY_CHARS = 120
REASON_CHARS = 60
SHOWN_POINTERS = 5


def build(run_id: str, run_dir: Path) -> dict[str, Any]:
    """The report as data (``--json``)."""
    try:
        envelope = ResultEnvelope.model_validate(service.envelope_data(run_dir))
    except ValidationError as exc:
        raise UsageError(t("show.missing", run_id=run_id, file="envelope.json")) from exc
    first = next((line.strip() for line in envelope.summary.splitlines() if line.strip()), "")
    review = envelope.review
    changes = envelope.changes
    record = gw.load_record(run_dir)
    state = record.state if record is not None else None
    return {
        "run_id": run_id,
        "status": envelope.status,
        "state": state,
        "done": first[:SUMMARY_CHARS],
        "verified": [{"type": v.type, "ok": v.ok} for v in envelope.verification],
        "changes": None if changes is None or not changes.files else {
            "files": changes.files, "insertions": changes.insertions,
            "deletions": changes.deletions,
        },
        "risk": review.risk if review is not None else None,
        "by": review.by if review is not None else None,
        "independent": review.independent if review is not None else None,
        "pointers": _pointers(run_id, run_dir) if review is not None else [],
        "next": _next(run_id, run_dir, envelope, state),
    }  # fmt: skip


def _pointers(run_id: str, run_dir: Path) -> list[str]:
    from orkestra.chief import review  # chief.review imports the router stack

    try:
        flags = review.load_flags(run_id, run_dir)
    except UsageError:
        return []
    found: list[str] = []
    for flag in flags[:SHOWN_POINTERS]:
        if flag.end_line == flag.start_line:
            lines = f"{flag.start_line}"
        else:
            lines = f"{flag.start_line}-{flag.end_line}"
        reason = " ".join(flag.reason.split())[:REASON_CHARS]
        found.append(f"{flag.file}:{lines} {reason}".rstrip())
    return found


def _next(run_id: str, run_dir: Path, envelope: ResultEnvelope, state: str | None) -> str | None:
    """The one command the chief runs next; None when the run is applied or discarded."""
    if state in ("applied", "discarded"):
        return None
    if envelope.status != "ok":
        return f"orkestra show {run_id} --log"
    if envelope.changes is None or not envelope.changes.files:
        return f"orkestra show {run_id} --output"
    review = envelope.review
    if review is None:
        return f"orkestra review {run_id} --json"
    if service.risk_problem(run_id, run_dir, "low") is None:
        return f"orkestra apply {run_id} --max-risk low"
    if review.flags_count:
        return f"orkestra show {run_id} --diff --only-flagged"
    return f"orkestra show {run_id} --diff"


def render(report: dict[str, Any]) -> str:
    lines = [t("report.done", summary=report["done"] or "-")]
    checks = [
        f"{c['type']} {t('envelope.verify.ok' if c['ok'] else 'envelope.verify.fail')}"
        for c in report["verified"]
    ]
    if checks:
        lines.append(t("report.verified", checks=", ".join(checks)))
    else:
        lines.append(t("report.verified_none"))
    changes = report["changes"]
    lines.append(t("report.changes", **changes) if changes else t("report.no_changes"))
    if report["risk"] is None:
        lines.append(t("report.not_reviewed"))
    else:
        independence = t("report.independent") if report["independent"] else t("report.self_review")
        lines.append(t("report.risk", risk=report["risk"], by=report["by"] or "-",
                       independence=independence))  # fmt: skip
    if report["pointers"]:
        lines.append(t("report.pointers", pointers="; ".join(report["pointers"])))
    if report["next"] is None:
        lines.append(t("report.finished", state=report["state"] or "-"))
    else:
        lines.append(t("report.next", command=report["next"]))
    return "\n".join(lines)
