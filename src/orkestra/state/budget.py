"""Daily budgets with reservation → reconciliation (Mimari §6.1).

Before a request a pessimistic estimate is reserved inside ``BEGIN IMMEDIATE``, so parallel
processes cannot overspend together. Afterwards the reservation is replaced by the actual usage.
Reservations older than one hour (crashed processes) no longer count.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from orkestra.config.schema import Budget
from orkestra.errors import BudgetExhausted
from orkestra.i18n import t
from orkestra.providers.base import estimate_tokens
from orkestra.state.db import transaction

if TYPE_CHECKING:
    from orkestra.providers.pricing import Price

STALE_RESERVATION = timedelta(hours=1)

LIMITS = ("daily_tokens", "daily_usd", "daily_requests", "daily_runs")


@dataclass(frozen=True)
class Amount:
    tokens: int = 0
    cost_usd: float = 0.0
    requests: int = 0
    runs: int = 0

    def get(self, limit: str) -> float:
        return {
            "daily_tokens": self.tokens,
            "daily_usd": self.cost_usd,
            "daily_requests": self.requests,
            "daily_runs": self.runs,
        }[limit]

    def __add__(self, other: Amount) -> Amount:
        return Amount(
            self.tokens + other.tokens,
            self.cost_usd + other.cost_usd,
            self.requests + other.requests,
            self.runs + other.runs,
        )


def estimate(
    prompt_chars: int, max_output_tokens: int, price: Price | None, *, runs: int = 1
) -> Amount:
    """Pessimistic estimate for one request (Mimari §6.1 step 1).

    Without a price the cost estimate is 0 (see ``providers.pricing`` for where prices come
    from); the actual cost is still recorded when the request is settled.
    """
    prompt_tokens = estimate_tokens(prompt_chars)
    cost = price.cost(prompt_tokens, max_output_tokens) if price else 0.0
    return Amount(prompt_tokens + max_output_tokens, cost, requests=1, runs=runs)


def _day(now: datetime) -> str:
    return now.date().isoformat()


def used(
    conn: sqlite3.Connection, provider: str, now: datetime, *, reservations: bool = True
) -> Amount:
    """Today's actual usage plus fresh reservations.

    ``reservations=False``: actual usage only. The router uses it: a reservation belongs to a
    request in flight (in a batch, one waiting for the same provider) that settles before this
    task sends; ``reserve`` still counts it when this task's request goes out (D-054).
    """
    rows = conn.execute(
        "SELECT kind, prompt_tokens, completion_tokens, cost_usd, requests, runs, created_at "
        "FROM usage WHERE provider = ? AND day = ?",
        (provider, _day(now)),
    ).fetchall()
    total = Amount()
    for row in rows:
        if row["kind"] == "reservation":
            if not reservations:
                continue
            created = datetime.fromisoformat(row["created_at"])
            if now - created > STALE_RESERVATION:
                continue
        total = total + Amount(
            (row["prompt_tokens"] or 0) + (row["completion_tokens"] or 0),
            row["cost_usd"] or 0.0,
            row["requests"] or 0,
            row["runs"] or 0,
        )
    return total


def exceeded(budget: Budget, current: Amount, extra: Amount) -> str | None:
    """Name of the first limit that ``current + extra`` would exceed, else ``None``."""
    for limit in LIMITS:
        value = getattr(budget, limit)
        if value is not None and current.get(limit) + extra.get(limit) > value:
            return limit
    return None


def reserve(
    conn: sqlite3.Connection,
    *,
    provider: str,
    model: str,
    run_id: str,
    budget: Budget,
    amount: Amount,
    now: datetime,
) -> int:
    """Reserve ``amount`` or raise ``BudgetExhausted``. Returns the reservation id."""
    with transaction(conn):
        limit = exceeded(budget, used(conn, provider, now), amount)
        if limit is not None:
            raise BudgetExhausted(t("budget.exhausted", provider=provider, limit=limit))
        cursor = conn.execute(
            "INSERT INTO usage (run_id, provider, model, day, prompt_tokens, completion_tokens, "
            "cost_usd, requests, runs, estimated, kind, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 1, 'reservation', ?)",
            (
                run_id,
                provider,
                model,
                _day(now),
                amount.tokens,
                amount.cost_usd,
                amount.requests,
                amount.runs,
                now.isoformat(),
            ),
        )
    return int(cursor.lastrowid or 0)


def settle(
    conn: sqlite3.Connection,
    reservation_id: int,
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cost_usd: float | None,
    estimated: bool,
    now: datetime,
) -> None:
    """Replace a reservation with the actual usage (a failed request still counts)."""
    with transaction(conn):
        row = conn.execute(
            "SELECT run_id, provider, model, day, requests, runs FROM usage "
            "WHERE id = ? AND kind = 'reservation'",
            (reservation_id,),
        ).fetchone()
        if row is None:
            return
        conn.execute("DELETE FROM usage WHERE id = ?", (reservation_id,))
        conn.execute(
            "INSERT INTO usage (run_id, provider, model, day, prompt_tokens, completion_tokens, "
            "cost_usd, requests, runs, estimated, kind, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'actual', ?)",
            (
                row["run_id"],
                row["provider"],
                row["model"],
                row["day"],
                prompt_tokens or 0,
                completion_tokens or 0,
                cost_usd or 0.0,
                row["requests"],
                row["runs"],
                int(estimated),
                now.isoformat(),
            ),
        )


def settle_as_reserved(conn: sqlite3.Connection, reservation_id: int, *, now: datetime) -> None:
    """Keep the reserved estimate as (estimated) actual usage.

    For a timed-out request: the provider may have processed and billed it, but reported
    nothing back. Counting the pessimistic estimate keeps daily limits on the safe side.
    """
    with transaction(conn):
        conn.execute(
            "UPDATE usage SET kind = 'actual', estimated = 1, created_at = ? "
            "WHERE id = ? AND kind = 'reservation'",
            (now.isoformat(), reservation_id),
        )


def release(conn: sqlite3.Connection, reservation_id: int) -> None:
    """Drop a reservation without usage (request never sent, or interrupted)."""
    with transaction(conn):
        conn.execute("DELETE FROM usage WHERE id = ? AND kind = 'reservation'", (reservation_id,))


def stale_reservations(conn: sqlite3.Connection, now: datetime) -> list[int]:
    """Ids of reservations older than one hour (left behind by crashed processes)."""
    rows = conn.execute("SELECT id, created_at FROM usage WHERE kind = 'reservation'").fetchall()
    return [
        r["id"] for r in rows if now - datetime.fromisoformat(r["created_at"]) > STALE_RESERVATION
    ]


def purge_stale_reservations(conn: sqlite3.Connection, now: datetime) -> int:
    """Delete reservations older than one hour (used by ``gc``)."""
    with transaction(conn):
        stale = stale_reservations(conn, now)
        conn.executemany("DELETE FROM usage WHERE id = ?", [(i,) for i in stale])
    return len(stale)


@dataclass(frozen=True)
class LimitStatus:
    limit: str
    value: float
    used: float

    @property
    def remaining(self) -> float:
        return max(self.value - self.used, 0)


def status(
    conn: sqlite3.Connection, provider: str, budget: Budget, now: datetime
) -> tuple[Amount, list[LimitStatus]]:
    current = used(conn, provider, now)
    limits = [
        LimitStatus(limit, getattr(budget, limit), current.get(limit))
        for limit in LIMITS
        if getattr(budget, limit) is not None
    ]
    return current, limits
