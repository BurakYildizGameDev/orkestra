"""Machine-wide slots for local models (Faz 13l, Mimari §12, D-096).

``ProviderSlots`` keeps a provider's ``concurrency`` inside one process. On one computer a
batch in a terminal, ``orkestra exec`` from the chief and the night queue are separate
processes; without this each would start its own request and a second heavy local model
would load next to the first. For a ``local`` provider a slot is therefore also a row in
``local_slots``: at most ``concurrency`` rows per provider; a process waits (polling) until a
row is free. A row whose process is gone (crash, kill) is taken back; one older than six
hours as well, whatever its owner.

When state.db cannot be used the machine-wide limit is skipped: the work goes on with the
per-process limit only.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import closing
from datetime import datetime, timedelta

from orkestra.state import db
from orkestra.state.process import Alive, Owner, current_owner, process_alive

STALE_AFTER = timedelta(hours=6)
POLL_S = 0.5

Sleep = Callable[[float], Awaitable[None]]


class MachineSlots:
    """Take and give back slots in ``local_slots``."""

    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection] = db.connect,
        *,
        poll_s: float = POLL_S,
        owner: Owner | None = None,
        alive: Alive = process_alive,
        now: Callable[[], datetime] = db.local_now,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._connect = connect
        self._poll_s = poll_s
        self._owner = owner
        self._alive = alive
        self._now = now
        self._sleep = sleep

    def _me(self) -> Owner:
        if self._owner is None:
            self._owner = current_owner()
        return self._owner

    async def acquire(self, provider: str, limit: int) -> int | None:
        """Wait for a free slot; its id, or None when state.db cannot be used."""
        while True:
            found = self._try(provider, limit)
            if found != 0:
                return found
            await self._sleep(self._poll_s)

    def _try(self, provider: str, limit: int) -> int | None:
        """A new slot's id; 0 when all are taken; None when state.db cannot be used."""
        pid, created = self._me()
        now = self._now()
        try:
            with closing(self._connect()) as conn, db.transaction(conn):
                rows = conn.execute(
                    "SELECT id, pid, created, acquired_at FROM local_slots WHERE provider = ?",
                    (provider,),
                ).fetchall()
                held = 0
                for row in rows:
                    if _stale(row, now, self._alive):
                        conn.execute("DELETE FROM local_slots WHERE id = ?", (row["id"],))
                    else:
                        held += 1
                if held >= limit:
                    return 0
                cursor = conn.execute(
                    "INSERT INTO local_slots (provider, pid, created, acquired_at) "
                    "VALUES (?, ?, ?, ?)",
                    (provider, pid, created, now.isoformat()),
                )
                return int(cursor.lastrowid or 0) or None
        except (sqlite3.Error, OSError):
            return None

    def release(self, slot_id: int | None) -> None:
        if slot_id is None:
            return
        try:
            with closing(self._connect()) as conn, db.transaction(conn):
                conn.execute("DELETE FROM local_slots WHERE id = ?", (slot_id,))
        except (sqlite3.Error, OSError):
            return  # taken back later: the process is gone, or six hours pass


def _stale(row: sqlite3.Row, now: datetime, alive: Alive) -> bool:
    try:
        acquired = datetime.fromisoformat(row["acquired_at"])
    except (TypeError, ValueError):
        return True
    return now - acquired > STALE_AFTER or not alive(int(row["pid"]), row["created"])
