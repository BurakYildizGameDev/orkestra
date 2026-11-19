"""Old ``runs``, ``usage`` and ``queue`` rows, removed by ``gc`` (düzeltme-fable a, D-104).

Rows are kept at least ``MIN_KEEP``: learned routing (``routing.adaptive.WINDOW``), the quota
forecast and ``stats`` read the last 30 days, so a shorter ``gc --older-than`` removes old
files but never rows those readers still need. A run whose worktree is still on disk keeps
its row: its change may not have been applied yet.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from orkestra.state.db import transaction
from orkestra.state.stats import OFFSET_MARGIN, parse_started

MIN_KEEP = timedelta(days=35)  # >= the 30-day learning windows, with a margin
QUEUE_DONE = ("done", "failed", "removed")


@dataclass(frozen=True)
class Pruned:
    runs: int
    usage: int
    queue: int


NOTHING = Pruned(0, 0, 0)


def row_cutoff(now: datetime, keep: timedelta) -> datetime:
    """Rows older than this go; never closer to ``now`` than ``MIN_KEEP``."""
    return now - max(keep, MIN_KEEP)


def _old_runs(conn: sqlite3.Connection, cutoff: datetime, removing: frozenset[Path]) -> list[str]:
    rows = conn.execute(
        "SELECT run_id, started_at, worktree FROM runs WHERE started_at < ? OR started_at IS NULL",
        ((cutoff + OFFSET_MARGIN).isoformat(),),
    ).fetchall()
    chosen: list[str] = []
    for run_id, started_at, worktree in rows:
        started = parse_started(started_at)
        if started is not None and started >= cutoff:
            continue
        if worktree and Path(worktree).exists() and Path(worktree) not in removing:
            continue  # its change may still be applied
        chosen.append(run_id)
    return chosen


def _old_queue(conn: sqlite3.Connection, cutoff: datetime) -> list[int]:
    rows = conn.execute(
        "SELECT id, COALESCE(finished_at, started_at, added_at) FROM queue "
        f"WHERE status IN ({', '.join('?' for _ in QUEUE_DONE)})",
        QUEUE_DONE,
    ).fetchall()
    return [
        item_id for item_id, at in rows
        if (when := parse_started(at)) is None or when < cutoff
    ]  # fmt: skip


def _old_usage(conn: sqlite3.Connection, cutoff: datetime, runs: list[str]) -> list[int]:
    """Settled usage of the removed runs, and run-less usage of days before the cutoff.
    Reservations are ``budget.purge_stale_reservations``' job."""
    gone = set(runs)
    kept_runs = {row[0] for row in conn.execute("SELECT run_id FROM runs")} - gone
    rows = conn.execute("SELECT id, run_id, day FROM usage WHERE kind = 'actual'").fetchall()
    first_day = cutoff.date().isoformat()
    return [
        usage_id for usage_id, run_id, day in rows
        if run_id in gone or (run_id not in kept_runs and (day or "") < first_day)
    ]  # fmt: skip


def prune(
    conn: sqlite3.Connection,
    cutoff: datetime,
    *,
    dry_run: bool,
    removing: frozenset[Path] = frozenset(),
) -> Pruned:
    """Remove (or, with ``dry_run``, count) rows older than ``cutoff``.

    ``removing``: worktrees this ``gc`` removes; in a dry run they are still on disk but
    count as gone.
    """
    with transaction(conn):
        runs = _old_runs(conn, cutoff, removing)
        usage = _old_usage(conn, cutoff, runs)
        queue = _old_queue(conn, cutoff)
        if not dry_run:
            conn.executemany("DELETE FROM usage WHERE id = ?", [(i,) for i in usage])
            conn.executemany("DELETE FROM runs WHERE run_id = ?", [(r,) for r in runs])
            conn.executemany("DELETE FROM queue WHERE id = ?", [(i,) for i in queue])
    return Pruned(runs=len(runs), usage=len(usage), queue=len(queue))
