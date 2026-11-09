"""Run records and their worktrees: ``show``, ``apply``, ``discard``, ``gc`` (Mimari §3, §9).

A run with a worktree has ``runs/<run_id>/worktree.json`` (repository, worktree path,
baseline commit, state) and the ``workspace``/``worktree`` columns of its ``runs`` row.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from orkestra import paths
from orkestra.errors import UsageError
from orkestra.i18n import t
from orkestra.state import budget, db
from orkestra.workspace import git_worktree as gw

RUN_ID = re.compile(r"^(\d{8}-\d{6})-[0-9a-f]{4}$")
PATCH_FILE = "changes.patch"
DEFAULT_KEEP = timedelta(days=30)

Part = Literal["envelope", "diff", "output", "log"]
_PART_FILES = {"envelope": "envelope.json", "output": "output.md", "log": "orkestra.log"}


def run_started(run_id: str) -> datetime | None:
    match = RUN_ID.match(run_id)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def run_dir_for(run_id: str) -> Path:
    """The run's directory; an invalid or unknown id is a usage error (exit code 2)."""
    if run_started(run_id) is None:
        raise UsageError(t("run.error.bad_id", run_id=run_id))
    path = paths.run_dir(run_id)
    if not path.is_dir():
        raise UsageError(t("run.error.not_found", run_id=run_id, path=paths.runs_dir()))
    return path


def attach_worktree(conn: sqlite3.Connection, run_id: str, wt: gw.Worktree) -> None:
    """Remember a run's worktree (the edit runner calls this when it creates one)."""
    gw.save_record(paths.run_dir(run_id), wt)
    db.update_run(conn, run_id, workspace=str(wt.repo), worktree=str(wt.path))


# --- show ------------------------------------------------------------------------------


def show(run_id: str, part: Part) -> Any:
    """The envelope (as data), the diff, the full output or the log of a run.

    ``diff`` is ``""`` when the run has no changes.
    """
    run_dir = run_dir_for(run_id)
    if part == "diff":
        return _diff_text(run_dir)
    path = run_dir / _PART_FILES[part]
    if not path.is_file():
        raise UsageError(t("show.missing", run_id=run_id, file=path.name))
    text = path.read_bytes().decode("utf-8", errors="replace")
    return json.loads(text) if part == "envelope" else text


def _diff_text(run_dir: Path) -> str:
    saved = run_dir / PATCH_FILE
    if saved.is_file():
        return saved.read_bytes().decode("utf-8", errors="replace")
    record = gw.load_record(run_dir)
    if record is not None and record.state == "active" and record.worktree.path.is_dir():
        return gw.diff(record.worktree).patch.decode("utf-8", errors="replace")
    return ""


# --- apply and discard -----------------------------------------------------------------


@dataclass(frozen=True)
class Applied:
    run_id: str
    repo: Path
    files: tuple[str, ...]
    merged: tuple[str, ...]


def _active(run_id: str, run_dir: Path) -> gw.Worktree:
    record = gw.load_record(run_dir)
    if record is None:
        raise UsageError(t("apply.error.no_changes", run_id=run_id))
    if record.state == "applied":
        raise UsageError(t("apply.error.already", run_id=run_id))
    if record.state == "discarded":
        raise UsageError(t("apply.error.discarded", run_id=run_id))
    if not record.worktree.path.is_dir():
        raise UsageError(
            t("apply.error.worktree_missing", run_id=run_id, path=record.worktree.path)
        )
    return record.worktree


def apply_run(
    conn: sqlite3.Connection, run_id: str, *, redact: Callable[[str], str] = str
) -> Applied:
    """Apply a run's change to the user's working tree, then remove its worktree.

    A conflict raises ``WorkspaceConflict`` (exit code 5) and keeps the worktree.
    ``changes.patch`` (redacted, for ``show --diff``) stays in the run directory.
    """
    run_dir = run_dir_for(run_id)
    wt = _active(run_id, run_dir)
    change = gw.diff(wt)
    (run_dir / PATCH_FILE).write_bytes(
        redact(change.patch.decode("utf-8", errors="replace")).encode("utf-8")
    )
    result = gw.apply(wt, change)
    gw.save_record(run_dir, wt, state="applied")
    db.update_run(conn, run_id, applied=1)
    gw.remove(wt)
    return Applied(run_id, wt.repo, result.files, result.merged)


def discard_run(run_id: str) -> bool:
    """Remove a run's worktree without applying it. ``False``: there was nothing to remove."""
    run_dir = run_dir_for(run_id)
    record = gw.load_record(run_dir)
    if record is None or record.state != "active":
        return False
    gw.remove(record.worktree)
    gw.save_record(run_dir, record.worktree, state="discarded")
    return True


# --- gc --------------------------------------------------------------------------------


@dataclass(frozen=True)
class GcReport:
    worktrees: tuple[Path, ...]
    runs: tuple[str, ...]
    reservations: int
    dry_run: bool


def _worktree_dirs() -> list[Path]:
    root = paths.worktrees_dir()
    if not root.is_dir():
        return []
    return sorted(
        run for repo in root.iterdir() if repo.is_dir() and not repo.name.startswith(".")
        for run in repo.iterdir() if run.is_dir()
    )  # fmt: skip


def _is_old(run_id: str, cutoff: datetime) -> bool:
    started = run_started(run_id)
    return started is not None and started < cutoff


def _abandoned(path: Path, cutoff: datetime) -> bool:
    """A worktree nothing will apply: no run, a finished record, or the run is old."""
    run_id = path.name
    record = gw.load_record(paths.run_dir(run_id))
    if record is None or record.state != "active":
        return True
    if record.worktree.path.resolve() != path.resolve():
        return True
    return _is_old(run_id, cutoff)


def _remove_worktree(path: Path) -> None:
    repo = gw.main_repo_of(path)
    if repo is not None:
        gw.remove(gw.Worktree(repo, path, "", path.name))
    else:  # the repository is gone: just delete the directory
        gw.remove_directory(path)
    parent = path.parent
    if parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()


def gc(
    conn: sqlite3.Connection,
    now: datetime,
    *,
    keep: timedelta = DEFAULT_KEEP,
    dry_run: bool = False,
) -> GcReport:
    """Remove abandoned worktrees, run directories older than ``keep`` and stale reservations.

    ``runs`` rows stay (statistics); only files are removed.
    """
    cutoff = now.replace(tzinfo=None) - keep
    worktrees = tuple(p for p in _worktree_dirs() if _abandoned(p, cutoff))
    runs_root = paths.runs_dir()
    old_runs = tuple(
        sorted(d.name for d in runs_root.iterdir() if d.is_dir() and _is_old(d.name, cutoff))
        if runs_root.is_dir()
        else ()
    )
    if dry_run:
        stale = len(budget.stale_reservations(conn, now))
        return GcReport(worktrees, old_runs, stale, dry_run=True)
    for path in worktrees:
        _remove_worktree(path)
    for run_id in old_runs:
        shutil.rmtree(paths.run_dir(run_id), ignore_errors=True)
    stale = budget.purge_stale_reservations(conn, now)
    return GcReport(worktrees, old_runs, stale, dry_run=False)
