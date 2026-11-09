"""Circuit breaker per provider (Mimari §6.2).

Three transient failures in a row (timeouts, 5xx, rate limits, no connection) open the circuit
for 5 minutes, so an offline or broken provider is skipped instead of being waited on every
time. An authentication failure opens it for an hour. Any success, or ``providers enable``,
closes it. A missing model (``ProviderModelNotFound``) is about the request and not counted.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from orkestra.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimit,
    ProviderTransient,
    ProviderUnavailable,
)
from orkestra.state.db import transaction

FAILURE_THRESHOLD = 3
TRANSIENT_OPEN = timedelta(minutes=5)
AUTH_OPEN = timedelta(hours=1)

_TRANSIENT = (ProviderTransient, ProviderRateLimit, ProviderUnavailable)


@dataclass(frozen=True)
class Health:
    provider: str
    consecutive_failures: int = 0
    open_until: datetime | None = None
    last_error: str | None = None

    def is_open(self, now: datetime) -> bool:
        return self.open_until is not None and now < self.open_until


def get(conn: sqlite3.Connection, provider: str) -> Health:
    row = conn.execute(
        "SELECT consecutive_failures, open_until, last_error FROM health WHERE provider = ?",
        (provider,),
    ).fetchone()
    if row is None:
        return Health(provider)
    open_until = datetime.fromisoformat(row["open_until"]) if row["open_until"] else None
    return Health(provider, row["consecutive_failures"] or 0, open_until, row["last_error"])


def _store(conn: sqlite3.Connection, health: Health) -> None:
    conn.execute(
        "INSERT INTO health (provider, consecutive_failures, open_until, last_error) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(provider) DO UPDATE SET "
        "consecutive_failures = excluded.consecutive_failures, "
        "open_until = excluded.open_until, last_error = excluded.last_error",
        (
            health.provider,
            health.consecutive_failures,
            health.open_until.isoformat() if health.open_until else None,
            health.last_error,
        ),
    )


def record_success(conn: sqlite3.Connection, provider: str) -> None:
    with transaction(conn):
        _store(conn, Health(provider))


def reset(conn: sqlite3.Connection, provider: str) -> None:
    """Close the circuit by hand (``providers enable``): e.g. after fixing a wrong API key,
    which otherwise keeps the provider paused for an hour with no request to prove it works."""
    record_success(conn, provider)


def record_failure(
    conn: sqlite3.Connection, provider: str, error: ProviderError, now: datetime
) -> Health:
    """Count a failure. Errors that are about the request, not the provider, are ignored."""
    with transaction(conn):
        current = get(conn, provider)
        message = error.message[:300]
        if isinstance(error, ProviderAuthError):
            updated = Health(provider, current.consecutive_failures + 1, now + AUTH_OPEN, message)
        elif isinstance(error, _TRANSIENT):
            failures = current.consecutive_failures + 1
            open_until = (
                now + TRANSIENT_OPEN if failures >= FAILURE_THRESHOLD else current.open_until
            )
            updated = Health(provider, failures, open_until, message)
        else:  # ContextTooLong, ProviderBadOutput, other 4xx: the provider itself is fine
            return current
        _store(conn, updated)
    return updated
