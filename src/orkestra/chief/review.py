"""Automated code review (Mimari §19).

Reviews changes in a run's worktree or patch against the task prompt using a tier-2 model.
Produces a structured JSON report (risk, flags, summary).
On schema-invalid output, retries once, then falls back to ``risk: unknown``.
Results are saved to ``runs/<run_id>/review.json`` and envelope's ``review`` field is populated.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from orkestra.chief.call import query_chief_model
from orkestra.config.schema import Config
from orkestra.envelope import ENVELOPE_VERSION
from orkestra.errors import OrkestraError
from orkestra.i18n import t
from orkestra.workspace import service

REVIEW_FILE_NAME = "review.json"
LARGE_DIFF_LINES = 400


class ReviewFormatError(OrkestraError):
    """Raised when review model returns invalid or schema-violating JSON."""


class ReviewFlag(BaseModel):
    file: str
    start_line: int = 1
    end_line: int = 1
    reason: str = ""
    severity: Literal["low", "medium", "high"] = "medium"


class ReviewReport(BaseModel):
    risk: Literal["low", "medium", "high", "unknown"]
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
    """Parse and validate review JSON response from model."""
    cleaned = _extract_json_block(raw)
    try:
        data = json.loads(cleaned)
    except Exception as exc:
        raise ReviewFormatError(f"Output is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ReviewFormatError("Output JSON is not an object")

    try:
        return ReviewReport.model_validate(data)
    except ValidationError as exc:
        raise ReviewFormatError(f"Output does not conform to review schema: {exc}") from exc


def _split_patch_by_files(patch: str) -> list[tuple[str, str]]:
    """Split unified diff patch into (file_path, file_patch) pairs."""
    blocks: list[tuple[str, str]] = []
    current_file = ""
    current_lines: list[str] = []

    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git ") or line.startswith("--- "):
            if current_lines and current_file:
                blocks.append((current_file, "".join(current_lines)))
                current_lines = []
            if line.startswith("diff --git "):
                parts = line.strip().split()
                if len(parts) >= 4:
                    current_file = parts[3].removeprefix("b/")
            elif line.startswith("--- ") and not current_file:
                current_file = line.strip().split()[-1].removeprefix("a/")
        current_lines.append(line)

    if current_lines and current_file:
        blocks.append((current_file, "".join(current_lines)))
    elif current_lines:
        blocks.append(("diff", "".join(current_lines)))

    return blocks


async def _review_patch_text(
    patch: str,
    task_prompt: str,
    config: Config,
    run_id: str,
) -> tuple[ReviewReport, str | None]:
    """Query model with retry for a patch segment."""
    user_prompt = f"Task:\n{task_prompt}\n\nDiff:\n{patch}"
    label: str | None = None

    try:
        resp, label = await query_chief_model(
            config,
            tier=config.review.tier,
            system=_SYSTEM_PROMPT,
            user=user_prompt,
            json_mode=True,
            run_id=run_id,
        )
        report = parse_review_response(resp)
        report.model = label
        return report, label
    except ReviewFormatError as exc:
        # Retry ONCE with feedback (Mimari §19)
        feedback_user = (
            f"Your previous response did not match the required JSON schema: {exc}.\n"
            f"Please respond strictly with valid JSON.\n\nTask:\n{task_prompt}\n\nDiff:\n{patch}"
        )
        try:
            resp, label = await query_chief_model(
                config,
                tier=config.review.tier,
                system=_SYSTEM_PROMPT,
                user=feedback_user,
                json_mode=True,
                run_id=run_id,
            )
            report = parse_review_response(resp)
            report.model = label
            return report, label
        except Exception:
            # Second failure: fall back to risk: unknown
            return (
                ReviewReport(
                    risk="unknown",
                    flags=[],
                    summary=t("review.unknown_fallback"),
                    model=label,
                ),
                label,
            )
    except Exception as exc:
        return (
            ReviewReport(
                risk="unknown",
                flags=[],
                summary=f"Review failed: {exc}",
                model=label,
            ),
            label,
        )


async def review_run(run_id: str, config: Config) -> ReviewReport:
    """Run code review for ``run_id``, save review.json, and update envelope."""
    run_dir = service.run_dir_for(run_id)

    # Read task prompt
    task_prompt = ""
    task_yaml = run_dir / "task.yaml"
    if task_yaml.is_file():
        try:
            task_data = json.loads(task_yaml.read_bytes()) if task_yaml.suffix == ".json" else {}
            if not task_data:
                from orkestra.config.loader import read_yaml

                task_data = read_yaml(task_yaml)
            task_prompt = str(task_data.get("prompt", ""))
        except Exception:
            task_prompt = ""

    # Read patch
    patch = service._diff_text(run_dir, redact=str)
    if not patch.strip():
        report = ReviewReport(risk="low", flags=[], summary=t("review.no_changes"))
        _save_review(run_dir, report)
        _update_envelope(run_dir, report)
        return report

    # Split if large
    patch_lines = patch.count("\n")
    if patch_lines > LARGE_DIFF_LINES:
        file_blocks = _split_patch_by_files(patch)
        if len(file_blocks) > 1:
            all_flags: list[ReviewFlag] = []
            summaries: list[str] = []
            risks: list[str] = []
            model_label: str | None = None

            for file_name, file_patch in file_blocks:
                sub_report, m = await _review_patch_text(file_patch, task_prompt, config, run_id)
                model_label = m or model_label
                all_flags.extend(sub_report.flags)
                if sub_report.summary:
                    summaries.append(f"{file_name}: {sub_report.summary}")
                risks.append(sub_report.risk)

            highest_risk: Literal["low", "medium", "high", "unknown"] = "low"
            if "unknown" in risks:
                highest_risk = "unknown"
            elif "high" in risks:
                highest_risk = "high"
            elif "medium" in risks:
                highest_risk = "medium"

            combined_report = ReviewReport(
                risk=highest_risk,
                flags=all_flags,
                summary="; ".join(summaries),
                model=model_label,
            )
            _save_review(run_dir, combined_report)
            _update_envelope(run_dir, combined_report)
            return combined_report

    report, model_label = await _review_patch_text(patch, task_prompt, config, run_id)
    report.model = model_label
    _save_review(run_dir, report)
    _update_envelope(run_dir, report)
    return report


def _save_review(run_dir: Path, report: ReviewReport) -> None:
    path = run_dir / REVIEW_FILE_NAME
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    data = report.model_dump(mode="json")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _update_envelope(run_dir: Path, report: ReviewReport) -> None:
    env_path = run_dir / "envelope.json"
    if not env_path.is_file():
        return
    try:
        data = json.loads(env_path.read_text(encoding="utf-8"))
        data["envelope_version"] = ENVELOPE_VERSION
        data["review"] = {"risk": report.risk, "flags_count": len(report.flags)}
        tmp = env_path.with_name(f"{env_path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, env_path)
    except Exception:
        pass


def extract_flagged_lines(patch: str, flags: Sequence[ReviewFlag], context_lines: int = 5) -> str:
    """Extract flagged line ranges from unified diff with +-context_lines of context."""
    if not flags:
        return ""

    flags_by_file: dict[str, list[tuple[int, int]]] = {}
    for flag in flags:
        # Standardize file path
        norm = flag.file.replace("\\", "/").removeprefix("a/").removeprefix("b/")
        flags_by_file.setdefault(norm, []).append(
            (max(1, flag.start_line - context_lines), flag.end_line + context_lines)
        )

    output_lines: list[str] = []
    current_file = ""
    current_hunk_new_line = 0
    in_target_file = False
    file_ranges: list[tuple[int, int]] = []

    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git ") or line.startswith("+++ "):
            if line.startswith("diff --git "):
                parts = line.strip().split()
                current_file = (
                    parts[3].removeprefix("b/").replace("\\", "/") if len(parts) >= 4 else ""
                )
            elif line.startswith("+++ "):
                current_file = line.strip().split()[-1].removeprefix("b/").replace("\\", "/")
            in_target_file = current_file in flags_by_file
            file_ranges = flags_by_file.get(current_file, [])
            if in_target_file:
                output_lines.append(line)
            continue

        if not in_target_file:
            continue

        if line.startswith("@@ "):
            output_lines.append(line)
            # Parse @@ -a,b +start,len @@
            match = re.search(r"\+(\d+)", line)
            current_hunk_new_line = int(match.group(1)) if match else 1
            continue

        prefix = line[:1]
        line_num = current_hunk_new_line
        if prefix in (" ", "+"):
            current_hunk_new_line += 1

        # Check if line_num matches any flagged range
        matches = any(start <= line_num <= end for start, end in file_ranges)
        if matches:
            output_lines.append(line)

    return "".join(output_lines)
