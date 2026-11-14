"""Queue rows and the single-runner lock in ``state.db`` (Faz 12a, Mimari §21, D-072).

An item keeps the file's absolute path, its kind (task or batch), the directory it was added
from (relative paths and the project config are read from there when it runs) and the
file's hash, so ``queue run`` can say that the file changed since it was queued.

Only one ``queue run`` works at a time: the ``queue_lock`` row holds the owner's pid and
process start time. A row whose process is gone (or whose pid now belongs to another
process) is a crash's leftover and is replaced.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import psutil

from orkestra.errors import QueueBusy, UsageError
from orkestra.i18n import t
from orkestra.state.db import transaction
from orkestra.tasks import batch, spec

Kind = Literal["task", "batch"]
Owner = tuple[int, float | None]  # pid, process start time
Alive = Callable[[int, "float | None"], bool]
FINISHED = ("done", "failed")
_CREATE_TIME_SLACK_S = 1.0


@dataclass(frozen=True)
class QueueItem:
    id: int
    path: str
    kind: Kind
    profile: str | None
    status: str
    added_at: str | None
    started_at: str | None
    finished_at: str | None
    result_ref: str | None
    workdir: str
    file_hash: str | None
    note: str | None

    @property
    def name(self) -> str:
        return Path(self.path).name


@dataclass(frozen=True)
class LockOwner:
    pid: int
    created: float | None
    started_at: str | None


def _item(row: sqlite3.Row) -> QueueItem:
    return QueueItem(
        id=row["id"],
        path=row["path"],
        kind=row["kind"],
        profile=row["profile"],
        status=row["status"],
        added_at=row["added_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        result_ref=row["result_ref"],
        workdir=row["workdir"],
        file_hash=row["file_hash"],
        note=row["note"],
    )


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def detect_kind(path: Path) -> Kind:
    """Read and check the file like ``run``/``batch`` would; a batch has ``tasks:``."""
    if not path.is_file():
        raise UsageError(t("queue.error.no_file", path=path))
    data = spec.read_document(path)
    if isinstance(data, dict) and "tasks" in data:
        batch.load_batch(path)
        return "batch"
    spec.load_task(path)
    return "task"


# --- items ------------------------------------------------------------------------------


def add(
    conn: sqlite3.Connection,
    path: Path,
    *,
    now: datetime,
    profile: str | None = None,
    workdir: Path | None = None,
) -> QueueItem:
    """Queue a task or batch file; a file that ``run``/``batch`` would refuse is refused."""
    where = (workdir or Path.cwd()).resolve()
    absolute = (where / path).resolve()
    kind = detect_kind(absolute)
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO queue (path, kind, profile, status, added_at, workdir, file_hash) "
            "VALUES (?, ?, ?, 'pending', ?, ?, ?)",
            (str(absolute), kind, profile, now.isoformat(), str(where), file_hash(absolute)),
        )
    return get(conn, int(cursor.lastrowid or 0))


def get(conn: sqlite3.Connection, item_id: int) -> QueueItem:
    row = conn.execute("SELECT * FROM queue WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise UsageError(t("queue.error.unknown", id=item_id))
    return _item(row)


def items(conn: sqlite3.Connection) -> list[QueueItem]:
    """Every item that was not removed, oldest first."""
    rows = conn.execute("SELECT * FROM queue WHERE status != 'removed' ORDER BY id").fetchall()
    return [_item(row) for row in rows]


def remove(conn: sqlite3.Connection, item_id: int) -> QueueItem:
    """Hide an item from the queue; a running one is left alone (its run owns it)."""
    item = get(conn, item_id)
    if item.status == "removed":
        raise UsageError(t("queue.error.unknown", id=item_id))
    if item.status == "running":
        raise UsageError(t("queue.error.remove_running", id=item_id))
    with transaction(conn):
        conn.execute("UPDATE queue SET status = 'removed' WHERE id = ?", (item_id,))
    return get(conn, item_id)


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    found: dict[str, int] = dict.fromkeys(("pending", "running", "failed", "done"), 0)
    for row in conn.execute("SELECT status, COUNT(*) FROM queue GROUP BY status"):
        if row[0] in found:
            found[row[0]] = int(row[1])
    return found


def next_pending(conn: sqlite3.Connection, after_id: int) -> QueueItem | None:
    row = conn.execute(
        "SELECT * FROM queue WHERE status = 'pending' AND id > ? ORDER BY id LIMIT 1",
        (after_id,),
    ).fetchone()
    return None if row is None else _item(row)


def recover(conn: sqlite3.Connection) -> int:
    """Items a killed run left ``running`` go back to ``pending`` (call with the lock held)."""
    with transaction(conn):
        cursor = conn.execute(
            "UPDATE queue SET status = 'pending', started_at = NULL WHERE status = 'running'"
        )
    return cursor.rowcount


def mark_running(conn: sqlite3.Connection, item_id: int, now: datetime) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE queue SET status = 'running', started_at = ?, note = NULL WHERE id = ?",
            (now.isoformat(), item_id),
        )


def mark_finished(
    conn: sqlite3.Connection,
    item_id: int,
    status: str,
    now: datetime,
    *,
    result_ref: str | None = None,
    note: str | None = None,
) -> None:
    if status not in FINISHED:
        raise ValueError(f"not a finished status: {status}")
    with transaction(conn):
        conn.execute(
            "UPDATE queue SET status = ?, finished_at = ?, result_ref = ?, note = ? WHERE id = ?",
            (status, now.isoformat(), result_ref, note, item_id),
        )


def mark_skipped(conn: sqlite3.Connection, item_id: int, note: str | None) -> None:
    """Back to ``pending`` with the reason; a later run tries it again."""
    with transaction(conn):
        conn.execute(
            "UPDATE queue SET status = 'pending', started_at = NULL, note = ? WHERE id = ?",
            (note, item_id),
        )


# --- the lock ---------------------------------------------------------------------------


def process_alive(pid: int, created: float | None) -> bool:
    """Is ``pid`` still the process that took the lock (same start time)?"""
    try:
        process = psutil.Process(pid)
        if created is None:
            return process.is_running()
        return abs(process.create_time() - created) <= _CREATE_TIME_SLACK_S
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:  # it exists; we just may not look at it
        return True
    except (psutil.Error, OverflowError, ValueError):
        return False


def current_owner() -> Owner:
    return os.getpid(), psutil.Process().create_time()


def lock_owner(conn: sqlite3.Connection) -> LockOwner | None:
    row = conn.execute("SELECT pid, created, started_at FROM queue_lock WHERE id = 1").fetchone()
    return None if row is None else LockOwner(int(row[0]), row[1], row[2])


def acquire_lock(
    conn: sqlite3.Connection,
    now: datetime,
    *,
    owner: Owner | None = None,
    alive: Alive = process_alive,
) -> None:
    """Take the queue lock or raise ``QueueBusy``; a dead owner's lock is replaced."""
    pid, created = owner or current_owner()
    with transaction(conn):
        row = conn.execute(
            "SELECT pid, created, started_at FROM queue_lock WHERE id = 1"
        ).fetchone()
        if row is not None and (int(row[0]), row[1]) != (pid, created) and alive(row[0], row[1]):
            raise QueueBusy(t("queue.error.busy", pid=row[0], since=row[2] or "-"))
        conn.execute(
            "INSERT OR REPLACE INTO queue_lock (id, pid, created, started_at) VALUES (1, ?, ?, ?)",
            (pid, created, now.isoformat()),
        )


def release_lock(conn: sqlite3.Connection, owner: Owner | None = None) -> None:
    pid, created = owner or current_owner()
    with transaction(conn):
        conn.execute(
            "DELETE FROM queue_lock WHERE id = 1 AND pid = ? AND created IS ?", (pid, created)
        )
