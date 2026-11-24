"""Run records and their worktrees: ``show``, ``apply`` (one run or a batch), ``discard``,
``gc`` (Mimari §3, §9, §12).

A run with a worktree has ``runs/<run_id>/worktree.json`` (repository, worktree path,
baseline commit, state) and the ``workspace``/``worktree`` columns of its ``runs`` row.
"""

from __future__ import annotations

import hashlib
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
from orkestra.state import budget, db, retention
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


def show(
    run_id: str,
    part: Part,
    *,
    only_flagged: bool = False,
    redact: Callable[[str], str] = str,
) -> Any:
    """The envelope (as data), the diff, the full output or the log of a run.

    ``diff`` is ``""`` when the run has no changes; it goes through ``redact``.
    ``only_flagged`` filters the diff to flagged hunks with ±5 lines of context.
    """
    run_dir = run_dir_for(run_id)
    if part == "diff":
        patch = _diff_text(run_dir, redact)
        if not only_flagged:
            return patch
        from orkestra.chief import review  # chief.review uses this module

        flags = review.load_flags(run_id, run_dir)
        return review.extract_flagged_lines(patch, flags, context_lines=5)
    path = run_dir / _PART_FILES[part]
    if not path.is_file():
        if part == "envelope":  # stopped (Ctrl+C, killed) or still running (B-21)
            raise UsageError(t("show.unfinished", run_id=run_id))
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


def envelope_data(run_dir: Path) -> dict[str, Any]:
    """The run's stored envelope as data; ``{}`` when it is missing or unreadable. The one
    reader for ``_status``, ``apply --max-risk`` and ``review`` (Faz 13m)."""
    try:
        data = json.loads((run_dir / _PART_FILES["envelope"]).read_bytes())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _status(run_dir: Path) -> str | None:
    """The run's status from its envelope (``None`` when there is none)."""
    status = envelope_data(run_dir).get("status")
    return status if isinstance(status, str) else None


def apply_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    redact: Callable[[str], str] = str,
    force: bool = False,
    max_risk: str | None = None,
) -> Applied:
    """Apply a run's change to the user's working tree, then remove its worktree.

    A run that did not pass its checks is applied only with ``force``. With ``max_risk``
    only a run whose review by another provider is at most that risky (Faz 13m).

    A conflict raises ``WorkspaceConflict`` (exit code 5) and keeps the worktree; nothing is
    saved then. After a successful apply ``changes.patch`` (redacted, for ``show --diff``)
    stays in the run directory.
    """
    run_dir = run_dir_for(run_id)
    if max_risk is not None:
        check_max_risk(max_risk)
        if problem := risk_problem(run_id, run_dir, max_risk):
            raise UsageError(problem)
    wt = _active(run_id, run_dir)
    status = _status(run_dir)
    if status not in (None, "ok") and not force:
        raise UsageError(t("apply.error.not_ok", run_id=run_id, status=status))
    change = gw.diff(wt)
    review = envelope_data(run_dir).get("review")
    if max_risk is not None and not patch_matches(
        review if isinstance(review, dict) else {},
        change.patch.decode("utf-8", errors="replace"),
    ):
        raise UsageError(t("apply.error.changed_since_review", run_id=run_id))
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
    conflict: Conflict | None = None  # stopped at a conflict (exit code 5)
    error: Conflict | None = None  # stopped at another error (its exit code)
    error_code: int = 0
    not_tried: tuple[BatchRun, ...] = ()


def _batch_rows(conn: sqlite3.Connection, batch_id: str) -> list[sqlite3.Row]:
    """The batch's edit runs in the order they started (dependencies before dependents,
    edit tasks on the same files one after the other: Faz 7a). Times are compared as
    instants: a stored UTC offset may differ from today's (daylight saving)."""
    rows = conn.execute(
        "SELECT run_id, task_id, kind, status, applied, started_at FROM runs WHERE batch_id = ?",
        (batch_id,),
    ).fetchall()
    if not rows:
        raise UsageError(t("apply.error.unknown_batch", batch_id=batch_id))
    edits = [row for row in rows if row["kind"] == "edit"]
    return sorted(edits, key=lambda row: (datetime.fromisoformat(row["started_at"]), row["run_id"]))


def _has_change(run_id: str) -> bool:
    """The run still has a worktree to apply (not discarded, applied or removed)."""
    record = gw.load_record(run_dir_for(run_id))
    return record is not None and record.state == "active"


def _would_apply(row: sqlite3.Row, *, only_ok: bool) -> bool:
    return not row["applied"] and (row["status"] == "ok" or not only_ok)


RISKS = ("low", "medium", "high")


def check_max_risk(max_risk: str) -> None:
    """A wrong ``--max-risk`` is a usage error at once, never "nothing qualified"."""
    if max_risk not in RISKS:
        raise UsageError(t("apply.error.bad_max_risk", value=max_risk, allowed=", ".join(RISKS)))


def risk_problem(run_id: str, run_dir: Path, max_risk: str) -> str | None:
    """Why ``apply --max-risk`` does not apply this run unread; None when it does: its checks
    ran and passed, a provider other than the author reviewed it, found nothing to flag and
    at most ``max_risk`` (``unknown`` never is). The patch itself is compared in
    ``apply_run`` (``patch_matches``)."""
    data = envelope_data(run_dir)
    checks = data.get("verification")
    if (
        not isinstance(checks, list)
        or not checks
        or not all(isinstance(c, dict) and c.get("ok") is True for c in checks)
    ):
        return t("apply.error.unchecked", run_id=run_id)
    review = data.get("review")
    if not isinstance(review, dict):
        return t("apply.error.not_reviewed", run_id=run_id)
    risk = review.get("risk")
    if risk not in RISKS or RISKS.index(risk) > RISKS.index(max_risk):
        return t("apply.error.too_risky", run_id=run_id, risk=risk, max_risk=max_risk)
    if review.get("independent") is not True:
        return t("apply.error.not_independent", run_id=run_id)
    if review.get("flags_count"):
        return t("apply.error.flagged", run_id=run_id, count=review.get("flags_count"))
    return None


def patch_digest(patch: str) -> str:
    return hashlib.sha256(patch.encode("utf-8", errors="surrogateescape")).hexdigest()


def patch_matches(review: dict[str, Any], patch: str) -> bool:
    """The review read exactly this patch (nothing changed in the worktree since)."""
    digest = review.get("patch_sha256")
    return isinstance(digest, str) and digest == patch_digest(patch)


def apply_batch(
    conn: sqlite3.Connection,
    batch_id: str,
    *,
    only_ok: bool,
    redact: Callable[[str], str] = str,
    force: bool = False,
    max_risk: str | None = None,
) -> BatchApplied:
    """Apply a batch's edit runs one by one (Mimari §12); stop at the first conflict.

    Without ``only_ok`` (and ``force``) a batch with a failed run that still has a change is
    refused before anything is applied (a failed run that was discarded, or never got a
    worktree, has nothing to apply and does not count). Runs applied already, and with
    ``only_ok`` runs that did not pass, are skipped; so is a run with nothing to apply. The
    first conflict, or any other error, stops: what was applied so far is still reported,
    with the run that stopped it and the later runs that would have been applied.
    """
    if max_risk is not None:
        check_max_risk(max_risk)
    rows = _batch_rows(conn, batch_id)
    failed = [
        r for r in rows if not r["applied"] and r["status"] != "ok" and _has_change(r["run_id"])
    ]
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
            applied.append((run, apply_run(conn, run.run_id, redact=redact, force=force,
                                           max_risk=max_risk)))  # fmt: skip
        except UsageError as exc:  # nothing to apply, discarded, worktree gone
            skipped.append(Skipped(run, exc.message))
        except OrkestraError as exc:  # a conflict, or git failing: stop, keep the report
            later = tuple(
                BatchRun(r["run_id"], r["task_id"])
                for r in rows[index + 1 :]
                if _would_apply(r, only_ok=only_ok) and _has_change(r["run_id"])
            )
            stop = Conflict(run, exc.message, tuple(exc.details))
            done = (batch_id, tuple(applied), tuple(skipped))
            if isinstance(exc, WorkspaceConflict):
                return BatchApplied(*done, conflict=stop, not_tried=later)
            return BatchApplied(*done, error=stop, error_code=int(exc.exit_code), not_tried=later)
    return BatchApplied(batch_id, tuple(applied), tuple(skipped))


@dataclass(frozen=True)
class Unapplied:
    run_id: str
    task_id: str
    summary: str
    status: str = "ok"


def unapplied_runs(conn: sqlite3.Connection) -> list[Unapplied]:
    """Edit runs with changes that still wait for ``apply`` or ``discard``, newest first
    (``status``, Faz 8a). Failed runs are included and require ``apply --force``."""
    rows = conn.execute(
        "SELECT run_id, task_id, status, started_at FROM runs "
        "WHERE kind = 'edit' AND status IN ('ok', 'error') AND applied = 0 "
        "AND worktree IS NOT NULL"
    ).fetchall()
    waiting: list[tuple[datetime, Unapplied]] = []
    for row in rows:
        if not _has_change(row["run_id"]):
            continue
        try:
            data = json.loads((run_dir_for(row["run_id"]) / _PART_FILES["envelope"]).read_bytes())
        except (OSError, ValueError):
            data = {}
        summary = data.get("summary") if isinstance(data, dict) else None
        started = datetime.fromisoformat(row["started_at"])
        item = Unapplied(
            row["run_id"], row["task_id"], summary if isinstance(summary, str) else "",
            row["status"],
        )
        waiting.append((started, item))
    waiting.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in waiting]


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
    rows: retention.Pruned = retention.NOTHING  # old state.db rows (D-104)


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
    """Remove abandoned worktrees, run directories older than ``keep``, stale reservations
    and old ``runs``/``usage``/``queue`` rows.

    Rows go only after ``retention.MIN_KEEP`` (statistics and learned routing read them),
    and a run whose worktree could not be removed keeps its row (D-104).
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
    row_cutoff = retention.row_cutoff(now, keep)
    if dry_run:
        stale = len(budget.stale_reservations(conn, now))
        rows = retention.prune(conn, row_cutoff, dry_run=True, removing=frozenset(worktrees))
        return GcReport(worktrees, old_runs, stale, dry_run=True, rows=rows)
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
    rows = retention.prune(conn, row_cutoff, dry_run=False)
    return GcReport(tuple(removed), old_runs, stale, dry_run=False, failed=tuple(failed), rows=rows)
