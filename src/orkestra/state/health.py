"""Circuit breaker per provider (Mimari §6.2).

Three transient failures in a row (timeouts, 5xx, rate limits, no connection) open the circuit
for 5 minutes, so an offline or broken provider is skipped instead of being waited on every
time. An authentication failure opens it for an hour. A used-up quota (Faz 13f) opens it at
once until the quota resets: the reset time in the provider's message, else its
``quota_pause_s`` (at least a minute, at most a week). Any success, or ``providers enable``,
closes it. A missing model (``ProviderModelNotFound``) is about the request and not counted.

``reason`` says why it is paused (``quota``, ``auth``, ``errors``), for what users read.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from orkestra.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderQuotaExhausted,
    ProviderRateLimit,
    ProviderTransient,
    ProviderUnavailable,
)
from orkestra.state.db import transaction

FAILURE_THRESHOLD = 3
TRANSIENT_OPEN = timedelta(minutes=5)
AUTH_OPEN = timedelta(hours=1)
QUOTA_MIN_OPEN = timedelta(minutes=1)
QUOTA_MAX_OPEN = timedelta(days=7)

Reason = Literal["quota", "auth", "errors"]

_TRANSIENT = (ProviderTransient, ProviderRateLimit, ProviderUnavailable)


@dataclass(frozen=True)
class Health:
    provider: str
    consecutive_failures: int = 0
    open_until: datetime | None = None
    last_error: str | None = None
    reason: Reason | None = None

    def is_open(self, now: datetime) -> bool:
        return self.open_until is not None and now < self.open_until


def get(conn: sqlite3.Connection, provider: str) -> Health:
    row = conn.execute(
        "SELECT consecutive_failures, open_until, last_error, open_reason FROM health "
        "WHERE provider = ?",
        (provider,),
    ).fetchone()
    if row is None:
        return Health(provider)
    open_until = datetime.fromisoformat(row["open_until"]) if row["open_until"] else None
    return Health(
        provider, row["consecutive_failures"] or 0, open_until, row["last_error"],
        row["open_reason"],
    )  # fmt: skip


def _store(conn: sqlite3.Connection, health: Health) -> None:
    conn.execute(
        "INSERT INTO health (provider, consecutive_failures, open_until, last_error, "
        "open_reason) VALUES (?, ?, ?, ?, ?) ON CONFLICT(provider) DO UPDATE SET "
        "consecutive_failures = excluded.consecutive_failures, "
        "open_until = excluded.open_until, last_error = excluded.last_error, "
        "open_reason = excluded.open_reason",
        (
            health.provider,
            health.consecutive_failures,
            health.open_until.isoformat() if health.open_until else None,
            health.last_error,
            health.reason,
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
        failures = current.consecutive_failures + 1
        if isinstance(error, ProviderQuotaExhausted):
            pause = min(max(timedelta(seconds=error.pause_s), QUOTA_MIN_OPEN), QUOTA_MAX_OPEN)
            updated = Health(provider, failures, now + pause, message, "quota")
        elif isinstance(error, ProviderAuthError):
            updated = Health(provider, failures, now + AUTH_OPEN, message, "auth")
        elif isinstance(error, _TRANSIENT):
            if failures >= FAILURE_THRESHOLD:
                updated = Health(provider, failures, now + TRANSIENT_OPEN, message, "errors")
            else:
                updated = Health(provider, failures, current.open_until, message, current.reason)
        else:  # ContextTooLong, ProviderBadOutput, other 4xx: the provider itself is fine
            return current
        _store(conn, updated)
    return updated


def quota_paused(conn: sqlite3.Connection, now: datetime) -> list[Health]:
    """Providers paused right now because their quota is used up, by name."""
    rows = conn.execute(
        "SELECT provider FROM health WHERE open_reason = 'quota' ORDER BY provider"
    ).fetchall()
    return [h for row in rows if (h := get(conn, row["provider"])).is_open(now)]


def until_text(until: datetime, now: datetime) -> str:
    """``14:30`` today; with the date when the pause ends on another day (a weekly quota)."""
    return f"{until:%H:%M}" if until.date() == now.date() else f"{until:%Y-%m-%d %H:%M}"
