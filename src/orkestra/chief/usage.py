"""Usage and statistics service for web interface (Faz 11c-e, Mimari §19).

Computes aggregated usage, daily breakdown, cost, and savings metrics from state.db.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from orkestra.state import stats


def usage_summary(
    conn: sqlite3.Connection,
    days: int = 7,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect usage statistics and daily breakdown for the given lookback period."""
    current_time = datetime.now(UTC) if now is None else now
    since = current_time - timedelta(days=days)
    report = stats.collect(conn, since=since, now=current_time)

    # Compute daily breakdown directly from runs and usage
    daily_groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"runs": 0, "ok": 0, "failed": 0, "cost": 0.0, "tokens": 0}
    )
    for r in conn.execute(
        "SELECT started_at, status, run_id FROM runs WHERE started_at >= ?",
        ((since - stats.OFFSET_MARGIN).isoformat(),),
    ).fetchall():
        started = stats.parse_started(r[0])
        if started and started >= since:
            day_str = started.date().isoformat()
            daily_groups[day_str]["runs"] += 1
            if r[1] == "ok":
                daily_groups[day_str]["ok"] += 1
            elif r[1] == "failed":
                daily_groups[day_str]["failed"] += 1

    # Join cost and tokens from settled usage
    for u in conn.execute(
        "SELECT day, coalesce(sum(cost_usd), 0.0), "
        "coalesce(sum(prompt_tokens + completion_tokens), 0) "
        "FROM usage WHERE kind = 'actual' AND day >= ? GROUP BY day",
        (since.date().isoformat(),),
    ).fetchall():
        day_str = str(u[0])
        daily_groups[day_str]["cost"] += float(u[1])
        daily_groups[day_str]["tokens"] += int(u[2])

    daily_list = [
        {"date": day, **vals} for day, vals in sorted(daily_groups.items(), key=lambda x: x[0])
    ]

    base_dict = stats.to_dict(report)
    return {
        "since": base_dict["since"],
        "until": base_dict["until"],
        "totals": base_dict["totals"],
        "providers": base_dict["providers"],
        "daily": daily_list,
        "savings": base_dict["savings"],
    }
