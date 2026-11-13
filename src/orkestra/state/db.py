"""SQLite connection, migrations and the ``runs`` table (Mimari §6).

WAL mode and a busy timeout let several ``orkestra`` processes share the database; writes go
through ``transaction()`` (``BEGIN IMMEDIATE``). Each process opens its own connection.
Migrations are numbered SQL files in ``state/migrations``; existing files are never edited.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

from orkestra import paths

BUSY_TIMEOUT_MS = 5000
_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

Clock = Callable[[], datetime]


def local_now() -> datetime:
    """Timezone-aware local time; budgets reset at local midnight."""
    return datetime.now().astimezone()


def migrations() -> list[tuple[int, str]]:
    folder = resources.files("orkestra.state").joinpath("migrations")
    found: list[tuple[int, str]] = []
    for entry in folder.iterdir():
        match = _MIGRATION_NAME.match(entry.name)
        if match:
            found.append((int(match.group(1)), entry.read_text(encoding="utf-8")))
    return sorted(found)


def _statements(script: str) -> Iterator[str]:
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                yield buffer
            buffer = ""


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` … ``COMMIT``; rolls back on any exception."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; safe when several processes start at once."""
    with transaction(conn):
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
        for number, script in migrations():
            if number <= current:
                continue
            for statement in _statements(script):
                conn.execute(statement)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (number,))
            current = number
    return current


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = paths.state_db_path() if path is None else path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


# --- runs ------------------------------------------------------------------------------


def record_run_start(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    task_id: str,
    kind: str,
    started_at: datetime,
    tags: Sequence[str] = (),
    batch_id: str | None = None,
) -> None:
    with transaction(conn):
        conn.execute(
            "INSERT INTO runs (run_id, task_id, kind, status, started_at, attempts, tags, "
            "batch_id) VALUES (?, ?, ?, 'running', ?, 0, ?, ?)",
            (run_id, task_id, kind, started_at.isoformat(), json.dumps(list(tags)), batch_id),
        )


def record_run_end(conn: sqlite3.Connection, run_id: str, **fields: Any) -> None:
    update_run(conn, run_id, **fields)


def update_run(conn: sqlite3.Connection, run_id: str, **fields: Any) -> None:
    """Set columns of a ``runs`` row (only known columns; values are bound parameters)."""
    allowed = {
        "status", "provider", "model", "tier", "attempts", "finished_at", "duration_s",
        "worker_output_tokens", "envelope_chars", "workspace", "worktree", "applied",
    }  # fmt: skip
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unknown runs columns: {sorted(unknown)}")
    values = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in fields.items()}
    assignments = ", ".join(f"{column} = ?" for column in values)
    with transaction(conn):
        conn.execute(f"UPDATE runs SET {assignments} WHERE run_id = ?", (*values.values(), run_id))


# --- handoffs ---------------------------------------------------------------------------


def record_handoff(
    conn: sqlite3.Connection,
    *,
    from_chief: str | None,
    to_chief: str,
    at: datetime,
    commit: str | None,
    brief_path: str | None,
) -> int:
    """Write one handoff row (Faz 10b); it is stored before the next chief starts."""
    with transaction(conn):
        cursor = conn.execute(
            'INSERT INTO handoffs (from_chief, to_chief, at, "commit", brief_path) '
            "VALUES (?, ?, ?, ?, ?)",
            (from_chief, to_chief, at.isoformat(), commit, brief_path),
        )
    return int(cursor.lastrowid or 0)
