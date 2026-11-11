"""Run records and their worktrees: ``show``, ``apply`` (one run or a batch), ``discard``,
``gc`` (Mimari §3, §9, §12).

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
from orkestra.errors import OrkestraError, UsageError, WorkspaceConflict
from orkestra.i18n import t
from orkestra.state import budget, db
from orkestra.workspace import git_worktree as gw

RUN_ID = re.compile(r"^(\d{8}-\d{6})-[0-9a-f]{4}$")
PATCH_FILE = "changes.patch"
DEFAULT_KEEP = timedelta(days=30)
# A worktree without a run record may belong to a run that is still starting (D-041).
RECORDLESS_GRACE = timedelta(days=1)

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


def show(run_id: str, part: Part, *, redact: Callable[[str], str] = str) -> Any:
    """The envelope (as data), the diff, the full output or the log of a run.

    ``diff`` is ``""`` when the run has no changes; it goes through ``redact``.
    """
    run_dir = run_dir_for(run_id)
    if part == "diff":
        return _diff_text(run_dir, redact)
    path = run_dir / _PART_FILES[part]
    if not path.is_file():
        raise UsageError(t("show.missing", run_id=run_id, file=path.name))
    text = path.read_bytes().decode("utf-8", errors="replace")
    return json.loads(text) if part == "envelope" else text


def _diff_text(run_dir: Path, redact: Callable[[str], str]) -> str:
    """The live worktree diff while the run is open, else the patch saved by ``apply``."""
    record = gw.load_record(run_dir)
    if record is not None and record.state == "active" and record.worktree.path.is_dir():
        return redact(gw.diff(record.worktree).patch.decode("utf-8", errors="replace"))
    saved = run_dir / PATCH_FILE
    if saved.is_file():
        return saved.read_bytes().decode("utf-8", errors="replace")  # redacted when saved
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


def _status(run_dir: Path) -> str | None:
    """The run's status from its envelope (``None`` when there is none)."""
    try:
        data = json.loads((run_dir / _PART_FILES["envelope"]).read_bytes())
    except (OSError, ValueError):
        return None
    status = data.get("status") if isinstance(data, dict) else None
    return status if isinstance(status, str) else None


def apply_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    redact: Callable[[str], str] = str,
    force: bool = False,
) -> Applied:
    """Apply a run's change to the user's working tree, then remove its worktree.

    A run that did not pass its checks is applied only with ``force``.

    A conflict raises ``WorkspaceConflict`` (exit code 5) and keeps the worktree; nothing is
    saved then. After a successful apply ``changes.patch`` (redacted, for ``show --diff``)
    stays in the run directory.
    """
    run_dir = run_dir_for(run_id)
    wt = _active(run_id, run_dir)
    status = _status(run_dir)
    if status not in (None, "ok") and not force:
        raise UsageError(t("apply.error.not_ok", run_id=run_id, status=status))
    change = gw.diff(wt)
    result = gw.apply(wt, change)
    (run_dir / PATCH_FILE).write_bytes(
        redact(change.patch.decode("utf-8", errors="replace")).encode("utf-8")
    )
    gw.save_record(run_dir, wt, state="applied")
    db.update_run(conn, run_id, applied=1)
    gw.remove(wt)
    return Applied(run_id, wt.repo, result.files, result.merged)


@dataclass(frozen=True)
class BatchRun:
    run_id: str
    task_id: str


@dataclass(frozen=True)
class Skipped:
    run: BatchRun
    reason: str


@dataclass(frozen=True)
class Conflict:
    run: BatchRun
    message: str
    details: tuple[str, ...]


@dataclass(frozen=True)
class BatchApplied:
    batch_id: str
    applied: tuple[tuple[BatchRun, Applied], ...]
    skipped: tuple[Skipped, ...]
    conflict: Conflict | None = None
    not_tried: tuple[BatchRun, ...] = ()


def _batch_rows(conn: sqlite3.Connection, batch_id: str) -> list[sqlite3.Row]:
    """The batch's edit runs in the order they started (dependencies before dependents,
    edit tasks on the same files one after the other: Faz 7a)."""
    rows = conn.execute(
        "SELECT run_id, task_id, kind, status, applied FROM runs WHERE batch_id = ? "
        "ORDER BY started_at, run_id",
        (batch_id,),
    ).fetchall()
    if not rows:
        raise UsageError(t("apply.error.unknown_batch", batch_id=batch_id))
    return [row for row in rows if row["kind"] == "edit"]


def apply_batch(
    conn: sqlite3.Connection,
    batch_id: str,
    *,
    only_ok: bool,
    redact: Callable[[str], str] = str,
    force: bool = False,
) -> BatchApplied:
    """Apply a batch's edit runs one by one (Mimari §12); stop at the first conflict.

    Without ``only_ok`` (and ``force``) a batch with runs that did not pass is refused
    before anything is applied. Runs applied already, and with ``only_ok`` runs that did
    not pass, are skipped; so is a run with nothing to apply. A conflict keeps that run's
    worktree, reports it and leaves the later runs untried.
    """
    rows = _batch_rows(conn, batch_id)
    pending = [row for row in rows if not row["applied"]]
    failed = [row for row in pending if row["status"] != "ok"]
    if failed and not only_ok and not force:
        runs = ", ".join(f"{row['task_id']} ({row['run_id']}, {row['status']})" for row in failed)
        raise UsageError(t("apply.error.batch_not_ok", batch_id=batch_id, runs=runs))
    applied: list[tuple[BatchRun, Applied]] = []
    skipped: list[Skipped] = []
    for index, row in enumerate(rows):
        run = BatchRun(row["run_id"], row["task_id"])
        if row["applied"]:
            skipped.append(Skipped(run, t("apply.batch.reason.already")))
            continue
        if row["status"] != "ok" and only_ok:
            skipped.append(Skipped(run, t("apply.batch.reason.status", status=row["status"])))
            continue
        try:
            applied.append((run, apply_run(conn, run.run_id, redact=redact, force=force)))
        except WorkspaceConflict as exc:
            later = tuple(BatchRun(r["run_id"], r["task_id"]) for r in rows[index + 1 :]
                          if not r["applied"])  # fmt: skip
            conflict = Conflict(run, exc.message, tuple(exc.details))
            return BatchApplied(batch_id, tuple(applied), tuple(skipped), conflict, later)
        except UsageError as exc:  # nothing to apply, discarded, worktree gone
            skipped.append(Skipped(run, exc.message))
    return BatchApplied(batch_id, tuple(applied), tuple(skipped))


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
    worktrees: tuple[Path, ...]  # removed (or, in a dry run, to be removed)
    runs: tuple[str, ...]
    reservations: int
    dry_run: bool
    failed: tuple[tuple[Path, str], ...] = ()  # worktrees that could not be removed, and why


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


def _abandoned(path: Path, cutoff: datetime, now: datetime) -> bool:
    """A worktree nothing will apply: no run, a finished record, a repository missing for a
    day, or the run is old.

    Without a record the run may still be starting, so only older ones count.
    """
    run_id = path.name
    record = gw.load_record(paths.run_dir(run_id))
    if record is None:
        started = run_started(run_id)
        return started is None or started < now - RECORDLESS_GRACE
    if record.state != "active":
        return True
    if record.worktree.path.resolve() != path.resolve():
        return True
    if not record.worktree.repo.is_dir():
        # Deleted or moved, or only an unplugged drive: the unapplied change lives only in
        # this worktree, so give the repository a day to come back (D-048).
        started = run_started(run_id)
        return started is None or started < now - RECORDLESS_GRACE
    return _is_old(run_id, cutoff)


def _remove_worktree(path: Path) -> str | None:
    """Remove one worktree; the reason it failed, or ``None``."""
    try:
        gw.remove_path(path)
    except (OrkestraError, OSError) as exc:
        return str(exc)
    return None


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
    naive_now = now.replace(tzinfo=None)
    cutoff = naive_now - keep
    worktrees = tuple(p for p in _worktree_dirs() if _abandoned(p, cutoff, naive_now))
    runs_root = paths.runs_dir()
    old_runs = tuple(
        sorted(d.name for d in runs_root.iterdir() if d.is_dir() and _is_old(d.name, cutoff))
        if runs_root.is_dir()
        else ()
    )
    if dry_run:
        stale = len(budget.stale_reservations(conn, now))
        return GcReport(worktrees, old_runs, stale, dry_run=True)
    removed: list[Path] = []
    failed: list[tuple[Path, str]] = []
    for path in worktrees:  # one stuck worktree must not stop the rest
        reason = _remove_worktree(path)
        if reason is None:
            removed.append(path)
        else:
            failed.append((path, reason))
    for run_id in old_runs:
        shutil.rmtree(paths.run_dir(run_id), ignore_errors=True)
    stale = budget.purge_stale_reservations(conn, now)
    return GcReport(tuple(removed), old_runs, stale, dry_run=False, failed=tuple(failed))
