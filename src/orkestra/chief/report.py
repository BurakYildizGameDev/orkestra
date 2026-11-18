"""``orkestra show RUN --report``: the run as a short report to the chief (Faz 13m, D-098).

A few lines instead of the diff: what was done, what was checked, how much changed, what an
independent review said, where to look, and the one command to run next. The chief reads
the diff only when the report sends it there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from orkestra.envelope import ResultEnvelope
from orkestra.errors import UsageError
from orkestra.i18n import t

SUMMARY_CHARS = 120
REASON_CHARS = 60
SHOWN_POINTERS = 5
REVIEW_FILE = "review.json"


def build(run_id: str, run_dir: Path) -> dict[str, Any]:
    """The report as data (``--json``)."""
    try:
        envelope = ResultEnvelope.model_validate_json((run_dir / "envelope.json").read_bytes())
    except (OSError, ValidationError) as exc:
        raise UsageError(t("show.missing", run_id=run_id, file="envelope.json")) from exc
    first = next((line.strip() for line in envelope.summary.splitlines() if line.strip()), "")
    review = envelope.review
    changes = envelope.changes
    return {
        "run_id": run_id,
        "status": envelope.status,
        "done": first[:SUMMARY_CHARS],
        "verified": [f"{v.type} {'ok' if v.ok else 'failed'}" for v in envelope.verification],
        "changes": None
        if changes is None or not changes.files
        else {
            "files": changes.files,
            "insertions": changes.insertions,
            "deletions": changes.deletions,
        },
        "risk": review.risk if review is not None else None,
        "by": review.by if review is not None else None,
        "independent": review.independent if review is not None else None,
        "pointers": _pointers(run_dir) if review is not None else [],
        "next": _next(run_id, envelope),
    }


def _pointers(run_dir: Path) -> list[str]:
    try:
        flags = json.loads((run_dir / REVIEW_FILE).read_bytes()).get("flags") or []
    except (OSError, ValueError, AttributeError):
        return []
    found: list[str] = []
    for flag in flags[:SHOWN_POINTERS]:
        if not isinstance(flag, dict):
            continue
        start, end = flag.get("start_line", 1), flag.get("end_line", 1)
        lines = f"{start}" if end in (None, start) else f"{start}-{end}"
        reason = " ".join(str(flag.get("reason", "")).split())[:REASON_CHARS]
        found.append(f"{flag.get('file', '?')}:{lines} {reason}".rstrip())
    return found


def _next(run_id: str, envelope: ResultEnvelope) -> str:
    """The one command the chief runs next."""
    if envelope.status != "ok":
        return f"orkestra show {run_id} --log"
    if envelope.changes is None or not envelope.changes.files:
        return f"orkestra show {run_id} --output"
    review = envelope.review
    if review is None:
        return f"orkestra review {run_id} --json"
    if review.risk == "low" and review.independent:
        return f"orkestra apply {run_id} --max-risk low"
    if review.flags_count:
        return f"orkestra show {run_id} --diff --only-flagged"
    return f"orkestra show {run_id} --diff"


def render(report: dict[str, Any]) -> str:
    lines = [t("report.done", summary=report["done"] or "-")]
    verified = report["verified"]
    lines.append(t("report.verified", checks=", ".join(verified)) if verified
                 else t("report.verified_none"))  # fmt: skip
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
    lines.append(t("report.next", command=report["next"]))
    return "\n".join(lines)
