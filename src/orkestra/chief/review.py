"""Automated code review (Mimari §19).

Reviews changes in a run's worktree or patch against the task prompt using a tier-2 model.
Produces a structured JSON report (risk, flags, summary).
On schema-invalid output, retries once, then falls back to ``risk: unknown``.
Results are saved to ``runs/<run_id>/review.json`` and envelope's ``review`` field is populated.

After the code review (D-062): a provider or routing error is raised (``orkestra review``
exits with its code; ``review.auto`` leaves the run without a review), the diff is masked
before it is sent, and large diffs are split on real file boundaries (``patchparse``).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from orkestra.chief import patchparse
from orkestra.chief.call import query_chief_model
from orkestra.config.loader import read_yaml
from orkestra.config.schema import Config
from orkestra.envelope import ENVELOPE_VERSION, EnvelopeReview, ResultEnvelope, to_json
from orkestra.errors import OrkestraError, UsageError
from orkestra.i18n import t
from orkestra.security.redact import Redactor, configured_secrets
from orkestra.tasks.runner import ProviderSlots
from orkestra.workspace import service

REVIEW_FILE_NAME = "review.json"
LARGE_DIFF_LINES = 400

Risk = Literal["low", "medium", "high", "unknown"]
_RISK_ORDER: tuple[Risk, ...] = ("unknown", "high", "medium", "low")  # the first one wins


class ReviewFormatError(OrkestraError):
    """Raised when review model returns invalid or schema-violating JSON."""


class ReviewFlag(BaseModel):
    file: str
    start_line: int = 1
    end_line: int = 1
    reason: str = ""
    severity: Literal["low", "medium", "high"] = "medium"


class ReviewReport(BaseModel):
    risk: Risk
    flags: list[ReviewFlag] = Field(default_factory=list)
    summary: str = ""
    model: str | None = None


_SYSTEM_PROMPT = """\
You are an automated code review assistant. Inspect the git diff against the task prompt.
Assess the risk of the changes: "low", "medium", or "high".
Highlight specific suspicious, risky, bug-prone, or breaking changes in flags
with line numbers relative to the new file, reason, and severity.
Respond ONLY with a JSON object matching this schema:
{
  "risk": "low" | "medium" | "high",
  "flags": [
    {
      "file": "path/to/file",
      "start_line": 10,
      "end_line": 12,
      "reason": "explanation of risk",
      "severity": "low" | "medium" | "high"
    }
  ],
  "summary": "1-2 sentence overview of the review"
}
"""


def _extract_json_block(text: str) -> str:
    stripped = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped)
    if match:
        return match.group(1).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


def parse_review_response(raw: str) -> ReviewReport:
    """Parse and validate review JSON response from model.

    The messages go back to the model as feedback, so they are English (worker prompts).
    """
    cleaned = _extract_json_block(raw)
    try:
        data = json.loads(cleaned)
    except ValueError as exc:
        raise ReviewFormatError(f"Output is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ReviewFormatError("Output JSON is not an object")

    try:
        return ReviewReport.model_validate(data)
    except ValidationError as exc:
        raise ReviewFormatError(f"Output does not conform to review schema: {exc}") from exc


class _Reviewer:
    def __init__(
        self,
        config: Config,
        run_id: str,
        task_prompt: str,
        slots: ProviderSlots | None,
        conn: sqlite3.Connection | None,
    ) -> None:
        self.config = config
        self.run_id = run_id
        self.task_prompt = task_prompt
        self.slots = slots
        self.conn = conn

    async def _ask(self, user: str) -> tuple[str, str]:
        return await query_chief_model(
            self.config,
            tier=self.config.review.tier,
            system=_SYSTEM_PROMPT,
            user=user,
            json_mode=True,
            run_id=self.run_id,
            slots=self.slots,
            conn=self.conn,
        )

    async def review(self, patch: str) -> ReviewReport:
        """One patch: a bad answer gets one retry with feedback, then ``risk: unknown``.
        Provider and routing errors are raised."""
        user = f"Task:\n{self.task_prompt}\n\nDiff:\n{patch}"
        answer, label = await self._ask(user)
        try:
            report = parse_review_response(answer)
        except ReviewFormatError as exc:
            feedback = (
                f"Your previous response did not match the required JSON schema: {exc}.\n"
                f"Please respond strictly with valid JSON.\n\n{user}"
            )
            answer, label = await self._ask(feedback)
            try:
                report = parse_review_response(answer)
            except ReviewFormatError:
                return ReviewReport(
                    risk="unknown", summary=t("review.unknown_fallback"), model=label
                )
        return report.model_copy(update={"model": label})


async def review_run(
    run_id: str,
    config: Config,
    *,
    slots: ProviderSlots | None = None,
    conn: sqlite3.Connection | None = None,
) -> ReviewReport:
    """Run code review for ``run_id``, save review.json, and update envelope.

    ``slots`` and ``conn`` are the running task's when ``review.auto`` calls it, so the
    review waits for the same provider limits (D-062).
    """
    run_dir = service.run_dir_for(run_id)
    redact = Redactor(configured_secrets(config), passwords=False)
    # A saved patch was masked when it was written; mask again with today's keys anyway.
    patch = redact(service.show(run_id, "diff"))
    if not patch.strip():
        report = ReviewReport(risk="low", summary=t("review.no_changes"))
    else:
        reviewer = _Reviewer(config, run_id, _task_prompt(run_dir), slots, conn)
        report = await _review_patch(reviewer, patch)
    _save_review(run_dir, report)
    _update_envelope(run_dir, report)
    return report


def _task_prompt(run_dir: Path) -> str:
    task_yaml = run_dir / "task.yaml"
    if not task_yaml.is_file():
        return ""
    prompt = read_yaml(task_yaml).get("prompt", "")
    return prompt if isinstance(prompt, str) else str(prompt)


async def _review_patch(reviewer: _Reviewer, patch: str) -> ReviewReport:
    """A large diff with several files is reviewed file by file and the results merged."""
    files = patchparse.parse_patch(patch)
    if patch.count("\n") <= LARGE_DIFF_LINES or len(files) < 2:
        return await reviewer.review(patch)
    reports = [(f.path, await reviewer.review(f.text)) for f in files]
    risks = {report.risk for _path, report in reports}
    return ReviewReport(
        risk=next(r for r in _RISK_ORDER if r in risks),
        flags=[flag for _path, report in reports for flag in report.flags],
        summary="; ".join(f"{path}: {r.summary}" for path, r in reports if r.summary),
        model=next((r.model for _path, r in reversed(reports) if r.model), None),
    )


def _save_review(run_dir: Path, report: ReviewReport) -> None:
    _write_atomic(run_dir / REVIEW_FILE_NAME, json.dumps(report.model_dump(mode="json"), indent=2))


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _update_envelope(run_dir: Path, report: ReviewReport) -> None:
    """Add ``review`` to a finished run's envelope (``review.auto`` adds it before the
    envelope is written)."""
    env_path = run_dir / "envelope.json"
    if not env_path.is_file():
        return
    try:
        envelope = ResultEnvelope.model_validate_json(env_path.read_bytes())
    except (OSError, ValidationError) as exc:
        raise UsageError(t("review.error.envelope", path=env_path.name, reason=exc)) from exc
    updated = envelope.model_copy(
        update={
            "envelope_version": ENVELOPE_VERSION,
            "review": EnvelopeReview(risk=report.risk, flags_count=len(report.flags)),
        }
    )
    _write_atomic(env_path, to_json(updated))


def load_flags(run_id: str, run_dir: Path) -> list[ReviewFlag]:
    """The flags in ``review.json`` (``show --only-flagged``); missing or unreadable → 2."""
    path = run_dir / REVIEW_FILE_NAME
    if not path.is_file():
        raise UsageError(t("show.no_review", run_id=run_id))
    try:
        return ReviewReport.model_validate_json(path.read_bytes()).flags
    except (OSError, ValidationError) as exc:
        raise UsageError(
            t("show.error.review_unreadable", run_id=run_id, path=path.name, reason=exc)
        ) from exc


def extract_flagged_lines(patch: str, flags: Sequence[ReviewFlag], context_lines: int = 5) -> str:
    """The flagged line ranges of the diff with ±``context_lines`` of context: each flagged
    file's header, and only the hunks that have a line in a range."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    for flag in flags:
        span = (max(1, flag.start_line - context_lines), flag.end_line + context_lines)
        path = flag.file.replace("\\", "/").removeprefix("./")
        ranges.setdefault(path, []).append(span)
        if path.startswith(("a/", "b/")):  # a model may copy the diff's side prefix
            ranges.setdefault(path[2:], []).append(span)

    out: list[str] = []
    for file in patchparse.parse_patch(patch):
        wanted = ranges.get(file.path)
        if not wanted:
            continue
        shown = _flagged_hunks(file.hunks, wanted)
        if shown:
            out.extend(file.header)
            out.extend(shown)
    return "".join(out)


def _flagged_hunks(hunks: Sequence[patchparse.Hunk], wanted: list[tuple[int, int]]) -> list[str]:
    def inside(line_no: int) -> bool:
        return any(start <= line_no <= end for start, end in wanted)

    out: list[str] = []
    for hunk in hunks:
        lines = [line for line_no, line in patchparse.numbered(hunk) if inside(line_no)]
        if lines:
            out.append(hunk.header)
            out.extend(lines)
    return out
