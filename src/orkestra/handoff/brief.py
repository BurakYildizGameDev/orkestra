"""The brief for the next chief: rule based, redacted and never over ``brief_max_lines``.

No model is called. The order is Mimari §17: the handoff sections first, then the last entries
of ``Done`` and ``Decisions``, then what git and the database know (branch, dirty files, recent
commits, unapplied runs, remaining budget), then the staleness warning, then the fixed Orkestra
guide. A line that does not fit is dropped and the last line says how many (``… (+N)``).
Outside a git repository (or without ``git``) the brief still works and says so in one line.
"""

from __future__ import annotations

import sqlite3
import subprocess
import textwrap
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path

from orkestra.config.schema import Config
from orkestra.handoff import model
from orkestra.i18n import t
from orkestra.providers import registry
from orkestra.security.redact import Redactor, configured_secrets
from orkestra.workspace.service import Unapplied, unapplied_runs

Git = Callable[[list[str], Path], tuple[bool, str]]
GIT_STATUS_LINES = 15
RECENT_COMMITS = 5
RECENT_ITEMS = 5
WRAP_WIDTH = 120  # a hand-written paragraph becomes display lines, so the limit means lines


@dataclass(frozen=True)
class Staleness:
    commit: str | None
    count: int | None  # commits after the last update; None when the commit is unknown
    stale: bool
    no_git: bool = False  # there is no repository to compare against

    @property
    def unknown_commit(self) -> bool:
        return self.commit is not None and self.count is None and not self.no_git


@dataclass(frozen=True)
class Brief:
    text: str
    lines: list[str]
    staleness: Staleness | None


def default_git(args: list[str], cwd: Path) -> tuple[bool, str]:
    """Run ``git`` with no shell; a missing or failing ``git`` is a ``False``, not a crash."""
    try:
        done = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=cwd,
            shell=False,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return False, str(exc)
    return done.returncode == 0, done.stdout.decode("utf-8", errors="replace")


def staleness(document: model.Document, config: Config, cwd: Path, git: Git) -> Staleness | None:
    updated = model.parse_last_updated(document)
    if updated is None or updated.commit is None:
        return None
    inside, output = git(["rev-parse", "--is-inside-work-tree"], cwd)
    if not inside or output.strip() != "true":
        return Staleness(updated.commit, None, False, no_git=True)
    ok, output = git(["rev-list", "--count", f"{updated.commit}..HEAD"], cwd)
    if not ok:
        return Staleness(updated.commit, None, True)
    try:
        count = int(output.strip())
    except ValueError:
        return Staleness(updated.commit, None, True)
    return Staleness(updated.commit, count, count > config.handoff.stale_after_commits)


def warning_lines(state: Staleness | None, keys: Mapping[str, str]) -> list[str]:
    """The one place that decides what a staleness state warns about (GLM B5)."""
    if state is None:
        return []
    if state.no_git:
        return [t(keys["no_git"])] if "no_git" in keys else []
    if state.unknown_commit:
        return [t(keys["unknown_commit"], commit=state.commit)]
    if state.stale and state.count is not None:
        return [t(keys["stale"], count=state.count)]
    return []


BRIEF_WARNING_KEYS: dict[str, str] = {
    "unknown_commit": "handoff.brief.unknown_commit",
    "stale": "handoff.brief.stale",
}
# ``_git_lines`` already prints the no-git note, so the brief must not repeat it.


def head_commit(cwd: Path, git: Git | None = None) -> str | None:
    """The short hash of HEAD, or ``None`` outside a repository."""
    run_git = default_git if git is None else git
    ok, output = run_git(["rev-parse", "--short", "HEAD"], cwd)
    return output.strip() if ok and output.strip() else None


def build(
    config: Config,
    conn: sqlite3.Connection,
    now: datetime,
    *,
    path: Path,
    cwd: Path,
    git: Git | None = None,
    unapplied: list[Unapplied] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Brief:
    """Build the brief from the file, git and the database."""
    run_git = default_git if git is None else git
    document = model.parse(path.read_bytes().decode("utf-8"))
    state = staleness(document, config, cwd, run_git)
    lines: list[str] = []

    for slug in ("goal", "status", "open_questions", "watch_out"):
        _section(lines, document, slug)

    for slug in ("done", "decisions"):
        text = model.section_text(document, slug) or ""
        items = [line for line in text.splitlines() if line.strip()]
        if items:
            lines.append(t(f"handoff.brief.{slug}"))
            lines.extend(f"  {line}" for line in items[-RECENT_ITEMS:])

    lines.extend(_git_lines(cwd, run_git))
    lines.extend(_unapplied_lines(conn, unapplied))
    lines.extend(_budget_lines(config, conn, now, environ))
    lines.extend(warning_lines(state, BRIEF_WARNING_KEYS))
    lines.extend(_guide())

    redact = Redactor(configured_secrets(config, environ))
    lines = [redact(line) for line in lines]
    lines = _limit(_wrap(lines), config.handoff.brief_max_lines)
    return Brief("\n".join(lines), lines, state)


def _section(lines: list[str], document: model.Document, slug: str) -> None:
    text = model.section_text(document, slug) or ""
    body = [line for line in text.splitlines() if line.strip()]
    if not body:
        return
    lines.append(t(f"handoff.brief.{slug}"))
    lines.extend(body)


def _git_lines(cwd: Path, git: Git) -> list[str]:
    ok, branch = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if not ok:
        return [t("handoff.brief.no_git")]
    lines = [t("handoff.brief.branch", branch=branch.strip())]
    ok, status = git(["status", "--short"], cwd)
    if ok:
        changed = [line for line in status.splitlines() if line.strip()]
        if changed:
            lines.append(t("handoff.brief.git_status"))
            lines.extend(f"  {line}" for line in changed[:GIT_STATUS_LINES])
    ok, log = git(["log", "--pretty=format:%s", "-n", str(RECENT_COMMITS)], cwd)
    if ok:
        commits = [line for line in log.splitlines() if line.strip()][:RECENT_COMMITS]
        if commits:
            lines.append(t("handoff.brief.commits"))
            lines.extend(f"  {line}" for line in commits)
    return lines


def _unapplied_lines(conn: sqlite3.Connection, unapplied: list[Unapplied] | None) -> list[str]:
    runs = unapplied_runs(conn) if unapplied is None else unapplied
    if not runs:
        return []
    lines = [t("handoff.brief.unapplied", count=len(runs))]
    for run in runs:
        summary = " ".join(run.summary.split())
        lines.append(t("handoff.brief.unapplied_run", run_id=run.run_id, summary=summary or "-"))
    return lines


def _budget_lines(
    config: Config, conn: sqlite3.Connection, now: datetime, environ: Mapping[str, str] | None
) -> list[str]:
    lines: list[str] = []
    for row in registry.provider_overview(config, conn, now, environ):
        if not row.enabled or not row.limits:
            continue
        parts = [
            f"{limit.limit.removeprefix('daily_')} {limit.remaining:g}" for limit in row.limits
        ]
        lines.append(t("handoff.brief.budget", name=row.name, text=", ".join(parts)))
    return lines


def _guide() -> list[str]:
    text = (
        resources.files("orkestra")
        .joinpath("prompts")
        .joinpath("chief_guide.md")
        .read_text(encoding="utf-8")
    )
    return [t("handoff.brief.guide"), *[line for line in text.splitlines() if line.strip()]]


def _wrap(lines: list[str]) -> list[str]:
    """Wrap over-long lines so ``brief_max_lines`` counts what the reader sees."""
    wrapped: list[str] = []
    for line in lines:
        if len(line) <= WRAP_WIDTH:
            wrapped.append(line)
            continue
        indent = line[: len(line) - len(line.lstrip())]
        parts = textwrap.wrap(
            line.strip(),
            width=WRAP_WIDTH,
            initial_indent=indent,
            subsequent_indent=indent,
            break_long_words=False,
            break_on_hyphens=False,
        )
        wrapped.extend(parts or [line])
    return wrapped


def _limit(lines: list[str], limit: int) -> list[str]:
    if len(lines) <= limit:
        return lines
    kept = lines[: max(limit - 1, 0)]
    return [*kept, t("handoff.brief.more", count=len(lines) - len(kept))]
