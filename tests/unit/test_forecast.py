"""Quota forecast (Faz 13k, D-094): how soon a provider runs out, from its pace and its
known (budget) or learned (past quota errors) limit."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from orkestra.config.schema import Config, ForecastCfg
from orkestra.errors import ProviderQuotaExhausted
from orkestra.routing.router import ProviderState, Snapshot, TaskNeeds, route, take_snapshot
from orkestra.state import db, forecast, health

TZ = timezone(timedelta(hours=3))
NOON = datetime(2026, 11, 18, 12, 0, tzinfo=TZ)
SETTINGS = ForecastCfg()


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "state.db")) as connection:
        yield connection


def _use(
    conn: sqlite3.Connection, provider: str, at: datetime, *, runs: int = 1, requests: int = 1,
    tokens: int = 100,
) -> None:  # fmt: skip
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO usage (run_id, provider, model, day, prompt_tokens, completion_tokens, "
            "cost_usd, requests, runs, estimated, kind, created_at) "
            "VALUES ('r', ?, 'm', ?, ?, 0, 0, ?, ?, 0, 'actual', ?)",
            (provider, at.date().isoformat(), tokens, requests, runs, at.isoformat()),
        )


def _config(**provider: Any) -> Config:
    agent = {"type": "cli_agent", "command": "agy", **provider}
    return Config.model_validate({"version": 1, "providers": {"agy": agent}})


def _quota(conn: sqlite3.Connection, at: datetime, pause_s: float = 3600) -> None:
    health.record_failure(conn, "agy", ProviderQuotaExhausted("used up", pause_s), at)


# --- known limits (budget) ---------------------------------------------------------------


def test_known_limit_and_pace_give_the_time_left(conn: sqlite3.Connection) -> None:
    for minutes in range(0, 15 * 30, 30):  # 15 runs in the morning, the last at 10:00
        _use(conn, "agy", NOON.replace(hour=3) + timedelta(minutes=minutes))
    for minutes in (10, 30, 50):  # 3 in the last hour
        _use(conn, "agy", NOON - timedelta(minutes=minutes))
    cfg = _config(budget={"daily_runs": 20}).providers["agy"]

    found = forecast.provider_forecast(conn, "agy", cfg, NOON, SETTINGS)

    assert found is not None
    assert (found.limit, found.value, found.used, found.learned) == ("daily_runs", 20, 18, False)
    assert found.rate_per_h == pytest.approx(3)
    assert found.eta_s == pytest.approx(40 * 60)  # 2 runs left at 3 an hour
    assert found.low


def test_no_recent_use_has_no_time_but_little_left_is_still_low(
    conn: sqlite3.Connection,
) -> None:
    _use(conn, "agy", NOON.replace(hour=6), runs=19)
    cfg = _config(budget={"daily_runs": 20}).providers["agy"]

    found = forecast.provider_forecast(conn, "agy", cfg, NOON, SETTINGS)

    assert found is not None and found.eta_s is None and found.low  # 1 of 20 left: 5% <= 10%


def test_plenty_left_at_a_slow_pace_is_not_low(conn: sqlite3.Connection) -> None:
    _use(conn, "agy", NOON - timedelta(minutes=20), runs=5)
    cfg = _config(budget={"daily_runs": 20}).providers["agy"]

    found = forecast.provider_forecast(conn, "agy", cfg, NOON, SETTINGS)

    assert found is not None and not found.low
    assert found.eta_s == pytest.approx(3 * 3600)  # 15 left at 5 an hour


def test_a_daily_budget_that_resets_first_has_no_time_left(conn: sqlite3.Connection) -> None:
    late = NOON.replace(hour=23, minute=40)
    _use(conn, "agy", late.replace(hour=9), runs=10)
    _use(conn, "agy", late - timedelta(minutes=30), runs=4)
    cfg = _config(budget={"daily_runs": 20}).providers["agy"]

    found = forecast.provider_forecast(conn, "agy", cfg, late, SETTINGS)

    # 6 left at 4 an hour is 90 minutes; midnight comes in 20 minutes and resets the count.
    assert found is not None and found.eta_s is None and not found.low


def test_the_most_pressing_limit_is_shown(conn: sqlite3.Connection) -> None:
    _use(conn, "agy", NOON - timedelta(minutes=30), runs=2, requests=90)
    cfg = _config(budget={"daily_runs": 20, "daily_requests": 100}).providers["agy"]

    found = forecast.provider_forecast(conn, "agy", cfg, NOON, SETTINGS)

    assert found is not None and found.limit == "daily_requests" and found.low


def test_without_any_limit_there_is_no_forecast(conn: sqlite3.Connection) -> None:
    _use(conn, "agy", NOON - timedelta(minutes=5), runs=50)

    assert (
        forecast.provider_forecast(conn, "agy", _config().providers["agy"], NOON, SETTINGS) is None
    )


# --- learned limits (13f's quota errors) -----------------------------------------------


def test_a_quota_error_records_how_much_was_used_since_the_window_began(
    conn: sqlite3.Connection,
) -> None:
    for hour in (8, 9, 10):
        _use(conn, "agy", NOON.replace(hour=hour), runs=4, requests=6)
    _quota(conn, NOON, pause_s=7200)

    rows = conn.execute("SELECT * FROM quota_events").fetchall()

    assert len(rows) == 1
    row = rows[0]
    assert (row["provider"], row["runs"], row["requests"]) == ("agy", 12, 18)
    assert datetime.fromisoformat(row["since"]) == NOON.replace(hour=0)
    assert datetime.fromisoformat(row["resumes_at"]) == NOON + timedelta(hours=2)


def test_the_window_starts_again_when_the_pause_ends(conn: sqlite3.Connection) -> None:
    _use(conn, "agy", NOON.replace(hour=9), runs=10)
    _quota(conn, NOON.replace(hour=10), pause_s=3600)  # resumes at 11:00
    _use(conn, "agy", NOON.replace(hour=11, minute=30), runs=3)
    _quota(conn, NOON, pause_s=3600)

    runs = [r["runs"] for r in conn.execute("SELECT runs FROM quota_events ORDER BY id")]

    assert runs == [10, 3]
    assert forecast.window_start(conn, "agy", NOON + timedelta(hours=2)) == NOON + timedelta(
        hours=1
    )


def test_a_quota_of_one_model_records_nothing(conn: sqlite3.Connection) -> None:
    _use(conn, "agy", NOON.replace(hour=9), runs=3)
    error = ProviderQuotaExhausted("free-models-per-day", 3600, model_only=True)
    health.record_failure(conn, "agy", error, NOON)

    assert conn.execute("SELECT COUNT(*) FROM quota_events").fetchone()[0] == 0


def test_the_learned_limit_is_the_median_of_the_last_events(conn: sqlite3.Connection) -> None:
    for day, runs in ((10, 30), (11, 10), (12, 12), (13, 0), (14, 14)):
        at = NOON.replace(day=day)
        _use(conn, "agy", at.replace(hour=8), runs=runs)
        _quota(conn, at)

    learned = forecast.learned_limits(conn, "agy", NOON, events=5)

    # 0 says nothing (a weekly quota hit on the first run of a day) and is skipped.
    assert learned["daily_runs"] == 13  # median of 30, 10, 12, 14


def test_a_learned_limit_forecasts_from_the_current_window(conn: sqlite3.Connection) -> None:
    yesterday = NOON - timedelta(days=1)
    _use(conn, "agy", yesterday.replace(hour=8), runs=10, requests=20)
    _quota(conn, yesterday)
    _use(conn, "agy", NOON - timedelta(minutes=40), runs=8, requests=8)

    found = forecast.provider_forecast(conn, "agy", _config().providers["agy"], NOON, SETTINGS)

    assert found is not None
    assert (found.limit, found.value, found.used, found.learned) == ("daily_runs", 10, 8, True)
    assert found.eta_s == pytest.approx(15 * 60) and found.low


def test_a_configured_limit_wins_over_a_learned_one(conn: sqlite3.Connection) -> None:
    yesterday = NOON - timedelta(days=1)
    _use(conn, "agy", yesterday.replace(hour=8), runs=10, requests=20)
    _quota(conn, yesterday)
    cfg = _config(budget={"daily_runs": 50}).providers["agy"]

    found = forecast.provider_forecast(conn, "agy", cfg, NOON, SETTINGS)

    assert found is not None and (found.value, found.learned) == (50, False)


def test_old_events_are_forgotten(conn: sqlite3.Connection) -> None:
    long_ago = NOON - timedelta(days=forecast.LEARN_DAYS + 1)
    _use(conn, "agy", long_ago.replace(hour=8), runs=10)
    _quota(conn, long_ago)

    assert forecast.learned_limits(conn, "agy", NOON, events=5) == {}


def test_zeros_do_not_crowd_out_the_events_that_say_something(conn: sqlite3.Connection) -> None:
    """Code review #34: zeros took the LIMIT's places, so the median rested on one event."""
    for day, runs in ((10, 20), (11, 22), (12, 10), (13, 0), (14, 0), (15, 0)):
        at = NOON.replace(day=day)
        if runs:
            _use(conn, "agy", at.replace(hour=8), runs=runs)
        _quota(conn, at)

    assert forecast.learned_limits(conn, "agy", NOON, events=3)["daily_runs"] == 20


def test_today_is_counted_by_day_like_the_budget(conn: sqlite3.Connection) -> None:
    """Code review #34: a request settled just after midnight keeps yesterday's ``day``; the
    budget does not count it today, so the forecast must not either."""
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO usage (run_id, provider, model, day, prompt_tokens, completion_tokens, "
            "cost_usd, requests, runs, estimated, kind, created_at) "
            "VALUES ('r', 'agy', 'm', ?, 0, 0, 0, 1, 10, 0, 'actual', ?)",
            ((NOON - timedelta(days=1)).date().isoformat(), NOON.replace(hour=0, second=30)
             .isoformat()),
        )  # fmt: skip
    cfg = _config(budget={"daily_runs": 10}).providers["agy"]

    found = forecast.provider_forecast(conn, "agy", cfg, NOON, SETTINGS)

    assert found is not None and found.used == 0 and not found.low


def test_a_paused_provider_is_not_forecast_by_the_router(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real = forecast.provider_forecast

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(args[1])
        return real(*args, **kwargs)

    monkeypatch.setattr(forecast, "provider_forecast", counting)
    _quota(conn, NOON - timedelta(minutes=1))
    take_snapshot(conn, _config(budget={"daily_runs": 20}), NOON, environ={})

    assert calls == []


def test_low_now_leaves_out_paused_providers(conn: sqlite3.Connection) -> None:
    config = _config(budget={"daily_runs": 20})
    _use(conn, "agy", NOON - timedelta(minutes=5), runs=19)
    assert [f.provider for f in forecast.low_now(conn, config, NOON)] == ["agy"]
    assert forecast.low_now(conn, config, NOON, skip={"agy"}) == []
    _quota(conn, NOON)
    assert health.paused_names(conn, NOON) == {"agy"}


def test_forecast_off_returns_nothing(conn: sqlite3.Connection) -> None:
    _use(conn, "agy", NOON - timedelta(minutes=5), runs=19)
    cfg = _config(budget={"daily_runs": 20}).providers["agy"]

    off = ForecastCfg(enabled=False)

    assert forecast.provider_forecast(conn, "agy", cfg, NOON, off) is None


# --- text --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("eta_s", "expected"), [(40 * 60, "~40 min"), (59, "~1 min"), (3 * 3600 + 600, "~3 h")]
)
def test_time_left_text(eta_s: float, expected: str) -> None:
    assert forecast.eta_text(eta_s) == expected


def test_describe_names_the_limit_and_whether_it_was_learned() -> None:
    found = forecast.Forecast("agy", "daily_runs", 10, 8, True, 12.0, 600.0, True)
    assert forecast.describe(found) == "agy: ~10 min (runs 8/10, learned)"
    quiet = forecast.Forecast("api", "daily_requests", 100, 95, False, 0.0, None, True)
    assert forecast.describe(quiet) == "api: requests 95/100"


# --- router: a provider about to run out goes last in its tier ---------------------------

PROVIDERS: dict[str, Any] = {
    "first": {"type": "ollama", "models": [{"id": "a", "tier": 1}, {"id": "b", "tier": 2}]},
    "second": {"type": "ollama", "models": [{"id": "c", "tier": 1}]},
}


def _route(states: dict[str, ProviderState]) -> list[str]:
    config = Config.model_validate({"version": 1, "providers": PROVIDERS})
    found = route(TaskNeeds(), config, Snapshot(NOON, states), profile="balanced")
    return [c.label for c in found.candidates]


def test_a_provider_running_low_goes_last_inside_its_tier() -> None:
    normal = {n: ProviderState(consent="granted") for n in PROVIDERS}
    low = {**normal, "first": ProviderState(consent="granted", quota_low=True)}

    assert _route(normal) == ["first/a", "second/c", "first/b"]
    # The tier rule still comes first: first/b (tier 2) does not move before second/c.
    assert _route(low) == ["second/c", "first/a", "first/b"]


def test_the_snapshot_marks_a_provider_running_low(conn: sqlite3.Connection) -> None:
    config = _config(budget={"daily_runs": 20})
    _use(conn, "agy", NOON - timedelta(minutes=5), runs=19)

    snap = take_snapshot(conn, config, NOON, environ={})

    assert snap.providers["agy"].quota_low


def test_the_dry_run_description_shows_it() -> None:
    from orkestra.routing.router import describe_candidates

    states = {n: ProviderState(consent="granted", quota_low=n == "first") for n in PROVIDERS}
    config = Config.model_validate({"version": 1, "providers": PROVIDERS})
    found = route(TaskNeeds(), config, Snapshot(NOON, states), profile="cheap")

    described = {d["provider"]: d["quota_low"] for d in describe_candidates(found.candidates)}
    assert described == {"first": True, "second": False}
