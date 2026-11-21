"""Advanced configuration, queue, budgets and circuit breakers (Faz 11c-e, Mimari §19).

Only values the config and the state database really have: the terminal interface's budgets,
profiles, queue, handoff brief and settings tabs, read-only, for the web interface.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from orkestra.config.schema import Config
from orkestra.errors import OrkestraError
from orkestra.handoff import brief as handoff_brief
from orkestra.handoff import store as handoff_store
from orkestra.i18n import t
from orkestra.queue import store
from orkestra.state import db, health

BUDGET_LIMITS = ("daily_usd", "daily_tokens", "daily_requests", "daily_runs")


def _budgets(config: Config) -> dict[str, Any]:
    providers: dict[str, dict[str, float]] = {}
    for name, provider in config.providers.items():
        budget = getattr(provider, "budget", None)
        if budget is None:
            continue
        limits = {
            limit: float(value)
            for limit in BUDGET_LIMITS
            if (value := getattr(budget, limit, None)) is not None
        }
        if limits:
            providers[name] = limits
    return {"providers": providers}


def _breakers(config: Config, conn: sqlite3.Connection, now: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in config.providers:
        state = health.get(conn, name)
        is_open = state.is_open(now)
        rows.append(
            {
                "provider": name,
                "is_open": is_open,
                "consecutive_failures": state.consecutive_failures,
                "open_until": state.open_until.isoformat() if state.open_until else None,
                "until_text": (
                    health.until_text(state.open_until, now)
                    if is_open and state.open_until
                    else None
                ),
                "reason_text": (
                    t(f"advanced.breaker.reason.{state.reason or 'errors'}") if is_open else None
                ),
            }
        )
    return rows


def _handoff(config: Config, conn: sqlite3.Connection, now: datetime, cwd: Path) -> dict[str, str]:
    """The brief the next chief would read (the terminal interface's handoff tab)."""
    path = handoff_store.handoff_path(config, cwd)
    if not path.exists():
        return {"text": t("ui.handoff.none", path=path)}
    try:
        return {"text": handoff_brief.build(config, conn, now, path=path, cwd=cwd).text}
    except OrkestraError as exc:  # shown in the card; the rest of the screen still loads
        return {"text": str(exc)}


def advanced_summary(
    config: Config,
    conn: sqlite3.Connection,
    now: datetime | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Budgets, profiles, night queue, circuit breakers, handoff brief and settings."""
    current_time = db.local_now() if now is None else now
    profiles = config.profiles
    return {
        "budgets": _budgets(config),
        "profiles": {
            "active": config.defaults.profile,
            "available": list(profiles),
            "definitions": {
                name: {"min_tier": p.min_tier, "max_tier": p.max_tier}
                for name, p in profiles.items()
            },
        },
        "queue": {
            "items": [
                {
                    "id": item.id,
                    "kind": item.kind,
                    "path": str(item.path),
                    "status": item.status,
                    "note": item.note,
                }
                for item in store.items(conn)
            ],
            "counts": store.counts(conn),
        },
        "circuit_breakers": _breakers(config, conn, current_time),
        "handoff": _handoff(config, conn, current_time, Path.cwd() if cwd is None else cwd),
        "settings": {
            "language": config.language,
            "chief": config.defaults.chief,
            "profile": config.defaults.profile,
        },
    }
