"""Machine-wide slots for local models (Faz 13l, Mimari §12, D-096, D-097).

``ProviderSlots`` keeps a provider's ``concurrency`` inside one process. On one computer a
batch in a terminal, ``orkestra exec`` from the chief and the night queue are separate
processes; without this each would start its own request and a second heavy local model
would load next to the first. For a ``local`` provider a slot is therefore also a row in
``local_slots``, keyed by the local server (``ollama`` and ``ollama-small`` on the same
``localhost:11434`` share it): at most ``concurrency`` rows; a process waits (polling, off the
event loop) until a row is free.

- A row whose process is gone (crash, kill) is taken back; one older than six hours as well;
  and one of this very process that it no longer holds (a release that failed).
- A busy or locked database is waited for like a taken slot: the limit is never skipped
  because several processes compete. Only a database that cannot be opened at all skips it
  (the per-process limit still holds).
- ``wait_s``: a chief tool waits only a moment and then gives the work to the next candidate
  (``TimeoutError``) instead of waiting behind another process's long task.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Awaitable, Callable
from contextlib import closing
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from orkestra.state import db
from orkestra.state.process import Alive, Owner, current_owner, process_alive

STALE_AFTER = timedelta(hours=6)
POLL_S = 0.5
RELEASE_TRIES = 3
BUSY = 0  # ``_try``: all slots taken (or the database busy): wait and try again
_HELD: set[int] = set()  # slot ids this process holds, across all MachineSlots instances

Sleep = Callable[[float], Awaitable[None]]


def _busy(error: sqlite3.Error) -> bool:
    text = str(error).lower()
    return isinstance(error, sqlite3.OperationalError) and ("locked" in text or "busy" in text)


class MachineSlots:
    """Take and give back slots in ``local_slots``."""

    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection] | None = None,
        *,
        poll_s: float = POLL_S,
        owner: Owner | None = None,
        alive: Alive = process_alive,
        now: Callable[[], datetime] = db.local_now,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._connect_fn = connect
        self._migrated = False
        self._poll_s = poll_s
        self._owner = owner
        self._alive = alive
        self._now = now
        self._sleep = sleep
        self._clock = clock

    def _connect(self) -> sqlite3.Connection:
        if self._connect_fn is not None:
            return self._connect_fn()
        # The schema is brought up to date once; the polls only read and write one table.
        conn = db.connect(migrate_schema=not self._migrated)
        self._migrated = True
        return conn

    def _me(self) -> Owner:
        if self._owner is None:
            self._owner = current_owner()
        return self._owner

    async def acquire(self, key: str, limit: int, *, wait_s: float | None = None) -> int | None:
        """Wait for a free slot; its id, or None when state.db cannot be used at all.
        ``wait_s``: give up after that long (``TimeoutError``)."""
        deadline = None if wait_s is None else self._clock() + wait_s
        while True:
            found = await asyncio.to_thread(self._try, key, limit)
            if found != BUSY:
                return found
            if deadline is not None and self._clock() >= deadline:
                raise TimeoutError(key)
            await self._sleep(self._poll_s)

    def _try(self, key: str, limit: int) -> int | None:
        """A new slot's id; ``BUSY`` when all are taken or the database is busy; None when
        state.db cannot be used."""
        me = self._me()
        now = self._now()
        try:
            with closing(self._connect()) as conn, db.transaction(conn):
                rows = conn.execute(
                    "SELECT id, pid, created, acquired_at FROM local_slots WHERE provider = ?",
                    (key,),
                ).fetchall()
                held = 0
                for row in rows:
                    if self._stale(row, now, me):
                        conn.execute("DELETE FROM local_slots WHERE id = ?", (row["id"],))
                    else:
                        held += 1
                if held >= limit:
                    return BUSY
                cursor = conn.execute(
                    "INSERT INTO local_slots (provider, pid, created, acquired_at) "
                    "VALUES (?, ?, ?, ?)",
                    (key, me[0], me[1], now.isoformat()),
                )
                slot = int(cursor.lastrowid or 0)
        except sqlite3.Error as exc:
            return BUSY if _busy(exc) else None
        except OSError:
            return None
        if not slot:
            return None
        _HELD.add(slot)
        return slot

    def _stale(self, row: sqlite3.Row, now: datetime, me: Owner) -> bool:
        try:
            acquired = datetime.fromisoformat(row["acquired_at"])
        except (TypeError, ValueError):
            return True
        if now - acquired > STALE_AFTER:
            return True
        if (int(row["pid"]), row["created"]) == me:
            return int(row["id"]) not in _HELD  # ours, but given up: a release that failed
        return not self._alive(int(row["pid"]), row["created"])

    def release(self, slot_id: int | None) -> None:
        """Give the slot back; a few tries when the database is busy. If it still fails the
        row is not ours any more (``_HELD``), so the next acquire here takes it back."""
        if slot_id is None:
            return
        _HELD.discard(slot_id)
        for _ in range(RELEASE_TRIES):
            try:
                with closing(self._connect()) as conn, db.transaction(conn):
                    conn.execute("DELETE FROM local_slots WHERE id = ?", (slot_id,))
                return
            except sqlite3.Error as exc:
                if not _busy(exc):
                    return
            except OSError:
                return


def server_key(name: str, provider: object) -> str:
    """Which local server a provider talks to: providers on the same host and port share
    its slots (``localhost`` and ``127.0.0.1`` are the same). Without a URL: its name."""
    url = getattr(provider, "base_url", None)
    if not isinstance(url, str):
        return name
    parts = urlsplit(url if "//" in url else f"//{url}")
    host = (parts.hostname or "").lower()
    if host in ("127.0.0.1", "::1", "0.0.0.0"):
        host = "localhost"
    try:
        port = parts.port
    except ValueError:
        port = None
    return f"{host}:{port or ''}" if host else name
