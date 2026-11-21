"""Advanced configuration, queue, budgets and circuit breakers (Faz 11c-e, Mimari §19)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from orkestra.config.schema import Config
from orkestra.queue import store
from orkestra.state import health


def advanced_summary(
    config: Config,
    conn: sqlite3.Connection,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Inspect advanced settings, profiles, night queue, and circuit breakers."""
    current_time = datetime.now(UTC) if now is None else now

    # Budgets
    provider_budgets: dict[str, Any] = {}
    for name, p in config.providers.items():
        b = getattr(p, "budget", None)
        if b is not None:
            provider_budgets[name] = {
                "daily_usd": b.daily_usd,
                "daily_tokens": b.daily_tokens,
                "daily_requests": b.daily_requests,
                "daily_runs": b.daily_runs,
            }

    cfg_budget = getattr(config, "budget", None)
    budgets_data = {
        "daily": float(cfg_budget.daily_usd)
        if cfg_budget and getattr(cfg_budget, "daily_usd", None) is not None
        else None,
        "providers": provider_budgets,
    }

    # Profiles
    profiles_data = {
        "active": getattr(config.defaults, "profile", "balanced"),
        "available": list(config.profiles.keys()) if config.profiles else ["balanced"],
        "definitions": {
            name: {"min_tier": p.min_tier, "max_tier": p.max_tier}
            for name, p in (config.profiles or {}).items()
        },
    }

    # Queue
    queue_items = [
        {
            "id": it.id,
            "kind": it.kind,
            "path": str(it.path),
            "status": it.status,
            "note": it.note,
        }
        for it in store.items(conn)
    ]
    queue_counts = store.counts(conn)

    # Circuit breakers
    breakers = []
    for name in config.providers:
        h = health.get(conn, name)
        breakers.append(
            {
                "provider": name,
                "is_open": h.is_open(current_time),
                "consecutive_failures": h.consecutive_failures,
                "open_until": h.open_until.isoformat() if h.open_until else None,
                "last_error": h.last_error,
                "reason": h.reason,
            }
        )

    # Settings
    cb = getattr(config, "circuit_breaker", None)
    settings_data = {
        "language": config.language,
        "chief": getattr(config.defaults, "chief", "claude"),
        "privacy": getattr(config.defaults, "privacy", "any"),
        "circuit_breaker_failures": getattr(cb, "failures", 3) if cb else 3,
    }

    return {
        "budgets": budgets_data,
        "profiles": profiles_data,
        "queue": {
            "items": queue_items,
            "counts": queue_counts,
        },
        "circuit_breakers": breakers,
        "settings": settings_data,
    }
