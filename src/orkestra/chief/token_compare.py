"""Measure what the chief spent per phase of a project (Faz 13r-c, item 6).

Reads Claude Code transcripts and matches them against git commit history
to compute raw and weighted tokens spent per project phase.
"""

from __future__ import annotations

import bisect
import math
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from orkestra.chief import tokens
from orkestra.config.schema import TokensCfg
from orkestra.errors import UsageError
from orkestra.i18n import t
from orkestra.state import stats

# ``feat(faz-13r): ...`` -> 13r; a hyphenated sub-phase ``fix(faz-13i-a): ...`` -> 13i-a (D-138).
PHASE_RE = re.compile(r"^\w+\(faz-([0-9]+[a-z]*(?:-[a-z0-9]+)*)\)")


@dataclass
class PhaseCommit:
    commit_hash: str
    timestamp: int  # %ct epoch seconds
    subject: str
    phase: str
    added_lines: int = 0


@dataclass
class RequestRecord:
    timestamp: datetime
    usage: tokens.Usage


@dataclass
class CompareRow:
    phase: str
    commits: int
    added_lines: int
    requests: int
    raw_tokens: int
    weighted: float
    weighted_per_1k_lines: float | None = None


@dataclass
class CompareReport:
    phases: list[CompareRow]
    total: CompareRow
    skipped: int
    warnings: list[str] = field(default_factory=list)


def find_transcript_files(folder: Path) -> list[Path]:
    """Find all session and subagent transcripts in the project folder."""
    files: list[Path] = []
    if not folder.is_dir():
        return files
    for p in sorted(folder.glob("*.jsonl")):
        files.append(p)
        sub_dir = p.with_suffix("") / "subagents"
        if sub_dir.is_dir():
            files.extend(sorted(sub_dir.glob("*.jsonl")))
    for sub in sorted(folder.glob("*/subagents/*.jsonl")):
        if sub not in files:
            files.append(sub)
    return files


def extract_requests(project_folder: Path) -> tuple[list[RequestRecord], int]:
    """Find all requests in project's Claude Code transcripts and subagent transcripts.

    A request is an assistant entry with usage that passes tokens._real. A ``message.id`` is
    counted once across all files, the last entry's usage wins: one request spans several
    entries, and a resumed session copies the earlier messages into its new file.
    Requests without a valid timestamp are skipped and counted in skipped.
    """
    found: dict[str, tuple[datetime | None, tokens.Usage]] = {}
    session_dummy = tokens.Session("")

    for n, file_path in enumerate(find_transcript_files(project_folder)):
        for entry in tokens._entries(file_path, session_dummy):
            if entry.get("type") != "assistant":
                continue
            message = entry.get("message")
            if not isinstance(message, dict) or not tokens._real(message):
                continue
            msg_id = str(message.get("id") or f"#{n}:{len(found)}")
            usage = tokens._usage(message.get("usage"))
            found[msg_id] = (_timestamp(entry.get("timestamp")), usage)

    requests = [RequestRecord(ts, usage) for ts, usage in found.values() if ts is not None]
    return requests, len(found) - len(requests)


def _timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def extract_commits(project: Path) -> list[PhaseCommit]:
    """Extract phase commits with added lines from git repository."""
    cmd = ["git", "log", "--all", "--no-merges", "--format=%H\t%ct\t%s", "--numstat"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (FileNotFoundError, OSError):
        raise UsageError(t("tokens.compare.error.not_git")) from None

    if proc.returncode != 0:
        raise UsageError(t("tokens.compare.error.not_git"))

    commits: list[PhaseCommit] = []
    current_commit: PhaseCommit | None = None
    is_phase = False

    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) >= 3 and len(parts[0]) >= 40 and parts[1].isdigit():
            commit_hash = parts[0]
            ct_str = parts[1]
            subject = parts[2]
            match = PHASE_RE.match(subject)
            if match:
                phase = match.group(1)
                current_commit = PhaseCommit(
                    commit_hash=commit_hash,
                    timestamp=int(ct_str),
                    subject=subject,
                    phase=phase,
                    added_lines=0,
                )
                commits.append(current_commit)
                is_phase = True
            else:
                current_commit = None
                is_phase = False
        elif is_phase and current_commit is not None:
            added_str = parts[0]
            if added_str.isdigit():
                current_commit.added_lines += int(added_str)

    return commits


def compare(
    *,
    project: Path,
    since: timedelta | str | None = None,
    config_flag: Path | None = None,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> CompareReport:
    """Measure tokens spent per phase from git history and Claude transcripts."""
    config, warnings = tokens.load(config_flag, project=project)
    cfg = config.tokens if config is not None else TokensCfg()
    weights = cfg.weights

    folder = tokens.project_folder(project, tokens.claude_home(environ))
    if not folder.is_dir() or not list(folder.glob("*.jsonl")):
        raise UsageError(t("tokens.error.none", folder=folder.name))

    commits = extract_commits(project)
    requests, skipped = extract_requests(folder)

    if since is not None:
        window = stats.parse_since(since) if isinstance(since, str) else since
        ref_now = now or datetime.now().astimezone()
        threshold = ref_now - window
        requests = [r for r in requests if r.timestamp >= threshold]

    sorted_commits = sorted(commits, key=lambda c: c.timestamp)

    phase_order: list[str] = []
    phase_commits_map: dict[str, list[PhaseCommit]] = {}
    for c in sorted_commits:
        if c.phase not in phase_commits_map:
            phase_commits_map[c.phase] = []
            phase_order.append(c.phase)
        phase_commits_map[c.phase].append(c)

    phase_requests: dict[str, list[RequestRecord]] = {p: [] for p in phase_order}
    uncommitted_requests: list[RequestRecord] = []

    times = [c.timestamp for c in sorted_commits]
    for req in requests:
        # %ct has whole seconds: a request within the commit's second still belongs to it.
        at = bisect.bisect_left(times, math.floor(req.timestamp.timestamp()))
        if at < len(sorted_commits):
            phase_requests[sorted_commits[at].phase].append(req)
        else:
            uncommitted_requests.append(req)

    rows: list[CompareRow] = []
    for phase in phase_order:
        c_list = phase_commits_map[phase]
        c_count = len(c_list)
        added_lines = sum(c.added_lines for c in c_list)
        reqs = phase_requests[phase]
        req_count = len(reqs)
        raw_tokens = sum(r.usage.raw for r in reqs)
        weighted_cost = sum(r.usage.weighted(weights) for r in reqs)
        per_1k = (weighted_cost / added_lines * 1000) if added_lines > 0 else None
        rows.append(
            CompareRow(
                phase=phase,
                commits=c_count,
                added_lines=added_lines,
                requests=req_count,
                raw_tokens=raw_tokens,
                weighted=weighted_cost,
                weighted_per_1k_lines=per_1k,
            )
        )

    if uncommitted_requests:
        req_count = len(uncommitted_requests)
        raw_tokens = sum(r.usage.raw for r in uncommitted_requests)
        weighted_cost = sum(r.usage.weighted(weights) for r in uncommitted_requests)
        rows.append(
            CompareRow(
                phase="uncommitted",
                commits=0,
                added_lines=0,
                requests=req_count,
                raw_tokens=raw_tokens,
                weighted=weighted_cost,
                weighted_per_1k_lines=None,
            )
        )

    tot_commits = sum(r.commits for r in rows)
    tot_added_lines = sum(r.added_lines for r in rows)
    tot_requests = sum(r.requests for r in rows)
    tot_raw = sum(r.raw_tokens for r in rows)
    tot_weighted = sum(r.weighted for r in rows)
    tot_per_1k = (tot_weighted / tot_added_lines * 1000) if tot_added_lines > 0 else None

    total_row = CompareRow(
        phase="total",
        commits=tot_commits,
        added_lines=tot_added_lines,
        requests=tot_requests,
        raw_tokens=tot_raw,
        weighted=tot_weighted,
        weighted_per_1k_lines=tot_per_1k,
    )

    return CompareReport(phases=rows, total=total_row, skipped=skipped, warnings=warnings)


def to_dict(report: CompareReport) -> dict[str, Any]:
    """Serialize report for --json."""
    return {
        "phases": [
            {
                "phase": r.phase,
                "commits": r.commits,
                "added_lines": r.added_lines,
                "requests": r.requests,
                "raw_tokens": r.raw_tokens,
                "weighted": round(r.weighted, 2),
                "weighted_per_1k_lines": (
                    round(r.weighted_per_1k_lines, 1)
                    if r.weighted_per_1k_lines is not None
                    else None
                ),
            }
            for r in report.phases
        ],
        "total": {
            "commits": report.total.commits,
            "added_lines": report.total.added_lines,
            "requests": report.total.requests,
            "raw_tokens": report.total.raw_tokens,
            "weighted": round(report.total.weighted, 2),
            "weighted_per_1k_lines": (
                round(report.total.weighted_per_1k_lines, 1)
                if report.total.weighted_per_1k_lines is not None
                else None
            ),
        },
        "skipped": report.skipped,
        "warnings": list(report.warnings),
    }


def render(report: CompareReport) -> str:
    """Format report as an aligned table for humans."""
    headers = [
        t("tokens.compare.header.phase"),
        t("tokens.compare.header.commits"),
        t("tokens.compare.header.added_lines"),
        t("tokens.compare.header.requests"),
        t("tokens.compare.header.raw_tokens"),
        t("tokens.compare.header.weighted"),
        t("tokens.compare.header.weighted_per_1k"),
    ]

    def format_row(r: CompareRow, label: str) -> list[str]:
        per_1k = (
            f"{round(r.weighted_per_1k_lines):,}" if r.weighted_per_1k_lines is not None else "-"
        )
        return [
            label,
            f"{r.commits:,}",
            f"{r.added_lines:,}",
            f"{r.requests:,}",
            f"{r.raw_tokens:,}",
            f"{round(r.weighted):,}",
            per_1k,
        ]

    table_data: list[list[str]] = [headers]
    for row in report.phases:
        table_data.append(format_row(row, row.phase))

    total_cells = format_row(report.total, t("tokens.compare.total"))
    table_data.append(total_cells)

    num_cols = len(headers)
    col_widths = [
        max(len(table_data[r][c]) for r in range(len(table_data))) for c in range(num_cols)
    ]

    def render_cells(cells: list[str]) -> str:
        # First column left-aligned, remaining numeric columns right-aligned
        parts = [cells[0].ljust(col_widths[0])]
        for i in range(1, num_cols):
            parts.append(cells[i].rjust(col_widths[i]))
        return "  ".join(parts)

    lines: list[str] = [render_cells(headers)]
    lines.append("  ".join("-" * w for w in col_widths))
    for row in report.phases:
        lines.append(render_cells(format_row(row, row.phase)))
    lines.append("  ".join("-" * w for w in col_widths))
    lines.append(render_cells(total_cells))

    if report.skipped > 0:
        lines.append("")
        lines.append(t("tokens.compare.skipped", count=report.skipped))
    lines.extend(report.warnings)

    return "\n".join(lines)
