"""Quota forecast (Faz 13k, Mimari §6.2, D-094): how soon a provider runs out.

13f pauses a provider once its quota is used up. This module looks ahead: it sets the pace of
the last ``forecast.window_s`` seconds against the provider's limit and says when the limit
will be reached, so ``status``, ``doctor``, notifications and the status line can warn, and
the router can try the provider last in its tier before it is used up.

Two kinds of limit:

- **known**: the provider's ``budget`` (``daily_runs`` …). It resets at local midnight, so a
  limit that the pace would reach only after midnight has no time left to show.
- **learned**: for a limit nobody wrote down (an agent's subscription quota). Every used-up
  quota records how much was used since its window began (``quota_events``, migration 5);
  the median of the last ``learn_events`` is the limit. A window begins at local midnight or
  when the previous pause ended, whichever is later. Only runs and requests are learned:
  code agents' tokens are estimates. A quota that is not daily (5-hourly, weekly) makes the
  learned value rougher; it only orders and warns, it never blocks a request.

Usage counts only settled (``actual``) rows, like the router (D-054).
"""

from __future__ import annotations

import math
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from orkestra.i18n import t
from orkestra.state.budget import LIMITS, Amount

if TYPE_CHECKING:
    from orkestra.config.schema import Budget, ForecastCfg

LEARNED_LIMITS = ("daily_runs", "daily_requests")
LEARN_DAYS = 30
MIN_HOURS_TEXT = 120 * 60  # below two hours the time left is told in minutes


@dataclass(frozen=True)
class Forecast:
    provider: str
    limit: str  # daily_runs, daily_requests …
    value: float  # the limit
    used: float
    learned: bool
    rate_per_h: float  # use of the last window, per hour
    eta_s: float | None  # seconds until the limit; None: no recent use, or it resets first
    low: bool  # runs out soon, or little is left

    @property
    def remaining(self) -> float:
        return max(self.value - self.used, 0.0)


# --- recording used-up quotas -------------------------------------------------------------


def _midnight(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def window_start(conn: sqlite3.Connection, provider: str, now: datetime) -> datetime:
    """Where the current quota window began: local midnight, or the end of the last pause
    today (when the provider was opened early by hand, the moment the quota ran out)."""
    start = _midnight(now)
    row = conn.execute(
        "SELECT at, resumes_at FROM quota_events WHERE provider = ? ORDER BY id DESC LIMIT 1",
        (provider,),
    ).fetchone()
    if row is None:
        return start
    at = datetime.fromisoformat(row["at"])
    resumes = datetime.fromisoformat(row["resumes_at"]) if row["resumes_at"] else at
    began = resumes if resumes <= now else at
    return max(start, began)


def usage_between(
    conn: sqlite3.Connection, provider: str, since: datetime, now: datetime
) -> Amount:
    """Settled usage of ``provider`` from ``since`` up to ``now``."""
    rows = conn.execute(
        "SELECT prompt_tokens, completion_tokens, cost_usd, requests, runs, created_at "
        "FROM usage WHERE provider = ? AND kind = 'actual' AND day >= ?",
        (provider, since.date().isoformat()),
    ).fetchall()
    total = Amount()
    for row in rows:
        created = datetime.fromisoformat(row["created_at"])
        if not since <= created <= now:
            continue
        total = total + Amount(
            (row["prompt_tokens"] or 0) + (row["completion_tokens"] or 0),
            row["cost_usd"] or 0.0,
            row["requests"] or 0,
            row["runs"] or 0,
        )
    return total


def record_event(
    conn: sqlite3.Connection, provider: str, now: datetime, resumes_at: datetime | None
) -> None:
    """Remember a used-up quota and the use that led to it. The caller holds the transaction
    (``health.record_failure``)."""
    since = window_start(conn, provider, now)
    used = usage_between(conn, provider, since, now)
    conn.execute(
        "INSERT INTO quota_events (provider, at, since, resumes_at, runs, requests, tokens) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            provider, now.isoformat(), since.isoformat(),
            resumes_at.isoformat() if resumes_at else None,
            used.runs, used.requests, used.tokens,
        ),
    )  # fmt: skip


def learned_limits(
    conn: sqlite3.Connection, provider: str, now: datetime, *, events: int
) -> dict[str, float]:
    """The median use at the last ``events`` used-up quotas of the last 30 days, per limit.
    A zero says nothing (a weekly quota hit on the first run of a day) and is skipped."""
    oldest = (now - timedelta(days=LEARN_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT at, runs, requests FROM quota_events WHERE provider = ? ORDER BY id DESC LIMIT ?",
        (provider, events),
    ).fetchall()
    recent = [r for r in rows if datetime.fromisoformat(r["at"]) >= datetime.fromisoformat(oldest)]
    found: dict[str, float] = {}
    for limit, column in (("daily_runs", "runs"), ("daily_requests", "requests")):
        values = [r[column] for r in recent if r[column]]
        if values:
            found[limit] = float(statistics.median(values))
    return found


# --- the forecast -------------------------------------------------------------------------


@dataclass(frozen=True)
class _Limit:
    name: str
    value: float
    used: float
    learned: bool
    resets_in_s: float | None  # known limits reset at midnight; learned ones: unknown


def provider_forecast(
    conn: sqlite3.Connection, provider: str, cfg: Any, now: datetime, settings: ForecastCfg
) -> Forecast | None:
    """The most pressing limit of ``provider``; None when it has none (or forecasts are off).

    ``cfg`` is the provider's config: only its ``budget`` is read.
    """
    if not settings.enabled:
        return None
    candidates = _limits(conn, provider, cfg.budget, now, settings)
    if not candidates:
        return None
    window = timedelta(seconds=settings.window_s)
    recent = usage_between(conn, provider, now - window, now)
    found = [_forecast(provider, limit, recent, settings) for limit in candidates]
    # Low ones first, then the soonest, then the smallest share left; ties keep config order.
    return min(
        found,
        key=lambda f: (
            not f.low,
            f.eta_s if f.eta_s is not None else math.inf,
            f.remaining / f.value if f.value else 0.0,
        ),
    )


def _limits(
    conn: sqlite3.Connection, provider: str, budget: Budget, now: datetime, settings: ForecastCfg
) -> list[_Limit]:
    found: list[_Limit] = []
    configured = {name for name in LIMITS if getattr(budget, name) is not None}
    if configured:
        today = usage_between(conn, provider, _midnight(now), now)
        resets_in = (_midnight(now) + timedelta(days=1) - now).total_seconds()
        for name in LIMITS:
            if name in configured:
                found.append(_Limit(name, getattr(budget, name), today.get(name), False, resets_in))
    learned = {
        name: value
        for name, value in learned_limits(conn, provider, now, events=settings.learn_events).items()
        if name not in configured
    }
    if learned:
        window = usage_between(conn, provider, window_start(conn, provider, now), now)
        found += [_Limit(name, value, window.get(name), True, None)
                  for name, value in learned.items()]  # fmt: skip
    return found


def _forecast(provider: str, limit: _Limit, recent: Amount, settings: ForecastCfg) -> Forecast:
    remaining = max(limit.value - limit.used, 0.0)
    rate = recent.get(limit.name) * 3600 / settings.window_s
    eta: float | None = remaining / rate * 3600 if rate > 0 else None
    if eta is not None and limit.resets_in_s is not None and eta >= limit.resets_in_s:
        eta = None  # the count resets before the pace reaches the limit
    share = remaining / limit.value if limit.value else 0.0
    low = share <= settings.low_share or (eta is not None and eta <= settings.warn_within_s)
    return Forecast(provider, limit.name, limit.value, limit.used, limit.learned, rate, eta, low)


def forecasts(
    conn: sqlite3.Connection,
    config: Any,
    now: datetime,
    *,
    skip: set[str] | frozenset[str] = frozenset(),
) -> list[Forecast]:
    """Forecasts of the enabled providers that have a limit, in config order; ``skip``: names
    to leave out (paused providers: they already say when they come back)."""
    found: list[Forecast] = []
    for name, cfg in config.providers.items():
        if not cfg.enabled or name in skip:
            continue
        result = provider_forecast(conn, name, cfg, now, config.forecast)
        if result is not None:
            found.append(result)
    return found


def low_now(conn: sqlite3.Connection, config: Any, now: datetime) -> list[Forecast]:
    """Providers running low that are not paused (notifications, the status line)."""
    paused = {
        row["provider"]
        for row in conn.execute("SELECT provider, open_until FROM health").fetchall()
        if row["open_until"] and now < datetime.fromisoformat(row["open_until"])
    }
    return [f for f in forecasts(conn, config, now, skip=paused) if f.low]


# --- text ---------------------------------------------------------------------------------


def eta_text(seconds: float) -> str:
    """``~40 min`` below two hours, else ``~3 h``."""
    if seconds < MIN_HOURS_TEXT:
        return t("forecast.minutes", count=max(1, round(seconds / 60)))
    return t("forecast.hours", count=round(seconds / 3600))


def describe(found: Forecast) -> str:
    """``agy: ~10 min (runs 8/10, learned)``; without a time: ``api: requests 95/100``."""
    usage = t(
        "forecast.usage",
        limit=found.limit.removeprefix("daily_"),
        used=f"{found.used:g}",
        value=f"{found.value:g}",
        learned=t("forecast.learned") if found.learned else "",
    )
    if found.eta_s is None:
        return t("forecast.item", name=found.provider, usage=usage)
    return t("forecast.item_eta", name=found.provider, eta=eta_text(found.eta_s), usage=usage)


def to_dict(found: Forecast) -> dict[str, Any]:
    return {
        "provider": found.provider,
        "limit": found.limit,
        "value": found.value,
        "used": found.used,
        "learned": found.learned,
        "rate_per_h": round(found.rate_per_h, 3),
        "eta_s": round(found.eta_s) if found.eta_s is not None else None,
        "low": found.low,
    }
