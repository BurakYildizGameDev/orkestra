"""Circuit breaker per provider (Mimari §6.2).

Three transient failures in a row (timeouts, 5xx, rate limits, no connection) open the circuit
for 5 minutes, so an offline or broken provider is skipped instead of being waited on every
time. An authentication failure opens it for an hour. A used-up quota (Faz 13f) opens it at
once until the quota resets: the reset time in the provider's message, else its
``quota_pause_s`` (at least a minute, at most a week). Any success, or ``providers enable``,
closes it. A used-up quota is also kept in ``quota_events`` (Faz 13k), so
``state.forecast`` can learn a limit nobody wrote down. A missing model
(``ProviderModelNotFound``) is about the request and not counted.

``reason`` says why it is paused (``quota``, ``auth``, ``errors``), for what users read.
"""

from __future__ import annotations

import math
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
from orkestra.state import forecast
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
        "SELECT provider, consecutive_failures, open_until, last_error, open_reason "
        "FROM health WHERE provider = ?",
        (provider,),
    ).fetchone()
    return Health(provider) if row is None else _health(row)


def _health(row: sqlite3.Row) -> Health:
    open_until = datetime.fromisoformat(row["open_until"]) if row["open_until"] else None
    return Health(
        row["provider"], row["consecutive_failures"] or 0, open_until, row["last_error"],
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
        if isinstance(error, ProviderQuotaExhausted) and error.model_only:
            return current  # one model's quota: the provider's other models still work
        if isinstance(error, ProviderQuotaExhausted):
            updated = Health(
                provider, failures, now + _quota_pause(error.pause_s), message, "quota"
            )
            forecast.record_event(conn, provider, now, updated.open_until)  # Faz 13k: learn
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


def _quota_pause(seconds: float) -> timedelta:
    """Clamped before ``timedelta`` is built: ``inf`` or ``nan`` from a header must not crash."""
    if math.isnan(seconds):
        return QUOTA_MAX_OPEN
    low, high = QUOTA_MIN_OPEN.total_seconds(), QUOTA_MAX_OPEN.total_seconds()
    return timedelta(seconds=min(max(seconds, low), high))


def quota_paused(conn: sqlite3.Connection, now: datetime) -> list[Health]:
    """Providers paused right now because their quota is used up, by name."""
    rows = conn.execute(
        "SELECT provider, consecutive_failures, open_until, last_error, open_reason "
        "FROM health WHERE open_reason = 'quota' ORDER BY provider"
    ).fetchall()
    return [h for row in rows if (h := _health(row)).is_open(now)]


def paused_names(conn: sqlite3.Connection, now: datetime) -> set[str]:
    """Providers paused right now, for any reason."""
    rows = conn.execute(
        "SELECT provider, consecutive_failures, open_until, last_error, open_reason FROM health"
    ).fetchall()
    return {h.provider for row in rows if (h := _health(row)).is_open(now)}


def quota_snapshot(conn: sqlite3.Connection, now: datetime) -> dict[str, datetime | None]:
    """The quota pauses before a batch or queue run: only new ones are announced after it."""
    return {h.provider: h.open_until for h in quota_paused(conn, now)}


def new_quota_pauses(
    conn: sqlite3.Connection, before: dict[str, datetime | None], now: datetime
) -> list[Health]:
    """Quota pauses that started (or were renewed) since ``before`` was taken."""
    return [
        h for h in quota_paused(conn, now)
        if h.provider not in before or before[h.provider] != h.open_until
    ]  # fmt: skip


def pause_kind(reason: str | None) -> str:
    """Why a paused provider is paused, as the message key suffix (and router code):
    ``quota_paused`` or ``circuit_open``. ``providers.*``, ``select.reason.*`` and ``doctor.*``
    have both, so every place that shows a pause says the same thing."""
    return "quota_paused" if reason == "quota" else "circuit_open"


def until_text(until: datetime, now: datetime) -> str:
    """``14:30`` today; with the date when the pause ends on another day (a weekly quota)."""
    return f"{until:%H:%M}" if until.date() == now.date() else f"{until:%Y-%m-%d %H:%M}"
