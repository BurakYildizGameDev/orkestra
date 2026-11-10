from __future__ import annotations

import multiprocessing
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from orkestra.config.schema import Budget, OpenAICompatProvider
from orkestra.errors import (
    BudgetExhausted,
    ContextTooLong,
    ExitCode,
    ProviderAuthError,
    ProviderBadOutput,
    ProviderTransient,
    ProviderUnavailable,
)
from orkestra.providers.pricing import Price
from orkestra.state import budget, consent, db, health

TZ = timezone(timedelta(hours=3))
NOON = datetime(2026, 11, 9, 12, 0, tzinfo=TZ)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "state.db")) as connection:
        yield connection


# --- db / migrations -------------------------------------------------------------------


def test_schema_v1_tables(conn: sqlite3.Connection) -> None:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"schema_version", "runs", "usage", "consents", "health"} <= tables
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 1
    runs_columns = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    assert {"tags", "batch_id", "worker_output_tokens", "envelope_chars"} <= runs_columns


def test_wal_and_busy_timeout(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == db.BUSY_TIMEOUT_MS


def test_migrate_is_idempotent(conn: sqlite3.Connection) -> None:
    assert db.migrate(conn) == 1
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1


def test_default_path_is_under_orkestra_home(tmp_path: Path) -> None:
    with closing(db.connect()):
        pass
    assert (tmp_path / "orkestra-home" / "state.db").is_file()


def test_runs_rows(conn: sqlite3.Connection) -> None:
    db.record_run_start(conn, run_id="r1", task_id="ask", kind="ask", started_at=NOON)
    db.record_run_end(conn, "r1", status="ok", provider="p", worker_output_tokens=7)
    row = conn.execute("SELECT * FROM runs WHERE run_id = 'r1'").fetchone()
    assert (row["status"], row["provider"], row["worker_output_tokens"]) == ("ok", "p", 7)
    assert row["started_at"] == NOON.isoformat()
    with pytest.raises(ValueError):
        db.record_run_end(conn, "r1", nope=1)


# --- budget ----------------------------------------------------------------------------


def test_estimate_is_pessimistic() -> None:
    amount = budget.estimate(35, 100, Price(1.0, 2.0, "config"))
    assert amount.tokens == 10 + 100  # 35 chars / 3.5
    assert amount.cost_usd == pytest.approx((10 * 1.0 + 100 * 2.0) / 1_000_000)
    assert (amount.requests, amount.runs) == (1, 1)


def test_estimate_without_price_has_zero_cost() -> None:
    assert budget.estimate(35, 100, None).cost_usd == 0.0


def _reserve(conn: sqlite3.Connection, limits: Budget, amount: budget.Amount, now: datetime) -> int:
    return budget.reserve(
        conn, provider="p", model="m", run_id="r", budget=limits, amount=amount, now=now
    )


def test_reserve_until_limit_then_exhausted(conn: sqlite3.Connection) -> None:
    limits = Budget(daily_requests=2)
    one = budget.Amount(tokens=10, requests=1)
    _reserve(conn, limits, one, NOON)
    _reserve(conn, limits, one, NOON)
    with pytest.raises(BudgetExhausted) as exc_info:
        _reserve(conn, limits, one, NOON)
    assert exc_info.value.exit_code == ExitCode.NO_PROVIDER
    assert "daily_requests" in exc_info.value.message


@pytest.mark.parametrize(
    ("limits", "amount", "expected"),
    [
        (Budget(daily_tokens=100), budget.Amount(tokens=101), "daily_tokens"),
        (Budget(daily_usd=0.5), budget.Amount(cost_usd=0.51), "daily_usd"),
        (Budget(daily_runs=0), budget.Amount(runs=1), "daily_runs"),
        (Budget(daily_tokens=100), budget.Amount(tokens=100), None),
        (Budget(), budget.Amount(tokens=10**9, cost_usd=10**6), None),
    ],
)
def test_exceeded(limits: Budget, amount: budget.Amount, expected: str | None) -> None:
    assert budget.exceeded(limits, budget.Amount(), amount) == expected


def test_settle_replaces_reservation_with_actual(conn: sqlite3.Connection) -> None:
    rid = _reserve(conn, Budget(daily_tokens=1000), budget.Amount(tokens=900, requests=1), NOON)
    budget.settle(
        conn, rid, prompt_tokens=30, completion_tokens=20, cost_usd=0.01, estimated=False, now=NOON
    )
    used = budget.used(conn, "p", NOON)
    assert (used.tokens, used.requests, used.cost_usd) == (50, 1, 0.01)
    kinds = [r[0] for r in conn.execute("SELECT kind FROM usage")]
    assert kinds == ["actual"]


def test_release_drops_reservation(conn: sqlite3.Connection) -> None:
    rid = _reserve(conn, Budget(), budget.Amount(tokens=5, requests=1), NOON)
    budget.release(conn, rid)
    assert budget.used(conn, "p", NOON) == budget.Amount()


def test_budget_resets_at_local_midnight(conn: sqlite3.Connection) -> None:
    limits = Budget(daily_requests=1)
    late = datetime(2026, 11, 9, 23, 59, tzinfo=TZ)
    rid = _reserve(conn, limits, budget.Amount(requests=1), late)
    budget.settle(
        conn, rid, prompt_tokens=1, completion_tokens=1, cost_usd=0, estimated=False, now=late
    )
    with pytest.raises(BudgetExhausted):
        _reserve(conn, limits, budget.Amount(requests=1), late + timedelta(seconds=30))
    next_day = datetime(2026, 11, 10, 0, 1, tzinfo=TZ)
    _reserve(conn, limits, budget.Amount(requests=1), next_day)  # new day, new budget


def test_stale_reservation_is_ignored_and_purged(conn: sqlite3.Connection) -> None:
    limits = Budget(daily_requests=1)
    _reserve(conn, limits, budget.Amount(requests=1), NOON)  # crashed process never settled
    with pytest.raises(BudgetExhausted):
        _reserve(conn, limits, budget.Amount(requests=1), NOON + timedelta(minutes=59))
    later = NOON + timedelta(hours=1, minutes=1)
    _reserve(conn, limits, budget.Amount(requests=1), later)
    assert budget.purge_stale_reservations(conn, later) == 1


def test_status_lists_only_configured_limits(conn: sqlite3.Connection) -> None:
    rid = _reserve(conn, Budget(), budget.Amount(tokens=40, requests=1), NOON)
    budget.settle(
        conn, rid, prompt_tokens=30, completion_tokens=10, cost_usd=0, estimated=False, now=NOON
    )
    used, limits = budget.status(conn, "p", Budget(daily_tokens=100), NOON)
    assert used.tokens == 40
    assert [(s.limit, s.value, s.used, s.remaining) for s in limits] == [
        ("daily_tokens", 100, 40, 60)
    ]


def _concurrent_reserver(db_path: str, barrier: Any, results: Any) -> None:
    with closing(db.connect(Path(db_path))) as connection:
        barrier.wait()
        try:
            budget.reserve(
                connection,
                provider="p",
                model="m",
                run_id="r",
                budget=Budget(daily_tokens=500, daily_requests=50),
                amount=budget.Amount(tokens=100, requests=1),
                now=datetime.now().astimezone(),
            )
            results.put("ok")
        except BudgetExhausted:
            results.put("exhausted")


def test_ten_processes_never_exceed_the_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    with closing(db.connect(db_path)):
        pass  # migrate once up front; the workers race only on reservations
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(10)
    results = ctx.Queue()
    workers = [
        ctx.Process(target=_concurrent_reserver, args=(str(db_path), barrier, results))
        for _ in range(10)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=60)
        assert worker.exitcode == 0
    outcomes = sorted(results.get(timeout=5) for _ in workers)
    assert outcomes.count("ok") == 5  # 5 x 100 tokens = the 500 token limit
    assert outcomes.count("exhausted") == 5
    with closing(db.connect(db_path)) as connection:
        total = connection.execute("SELECT SUM(prompt_tokens) FROM usage").fetchone()[0]
    assert total == 500


# --- consent ---------------------------------------------------------------------------

ROUTER = {
    "type": "openai_compat",
    "base_url": "https://router.test/v1",
    "api_key_env": "K",
    "models": [{"id": "m", "tier": 2}],
    "budget": {"daily_usd": 1.0},
}


def _router(**changes: Any) -> OpenAICompatProvider:
    return OpenAICompatProvider.model_validate({**ROUTER, **changes})


def test_consent_lifecycle(conn: sqlite3.Connection) -> None:
    assert consent.state(conn, "router", _router()) == "missing"
    consent.grant(conn, "router", _router(), NOON)
    assert consent.state(conn, "router", _router()) == "granted"
    assert consent.revoke(conn, "router") is True
    assert consent.state(conn, "router", _router()) == "missing"
    assert consent.revoke(conn, "router") is False


def test_consent_invalidated_by_base_url_not_by_budget(conn: sqlite3.Connection) -> None:
    consent.grant(conn, "router", _router(), NOON)
    assert consent.state(conn, "router", _router(budget={"daily_usd": 50.0})) == "granted"
    assert consent.state(conn, "router", _router(base_url="https://evil.test/v1")) == "changed"
    assert consent.state(conn, "router", _router(models=[{"id": "x", "tier": 1}])) == "changed"


@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": False},
        {"timeout_s": 999},
        {"concurrency": 8},
        {"experimental": True},
        {"models": [{"id": "m", "tier": 3, "priority": 9, "context_window": 99999}]},
        {"models": [{"id": "m", "tier": 2, "price_per_mtok": {"input": 5.0, "output": 9.0}}]},
    ],
)
def test_operational_changes_keep_consent(
    conn: sqlite3.Connection, changes: dict[str, Any]
) -> None:
    consent.grant(conn, "router", _router(), NOON)
    assert consent.state(conn, "router", _router(**changes)) == "granted"


@pytest.mark.parametrize(
    "changes",
    [
        {"api_key_env": "OTHER"},
        {"extra_headers": {"X-Forward": "elsewhere"}},
        {"models": [{"id": "m", "tier": 2}, {"id": "another/model", "tier": 2}]},
    ],
)
def test_data_destination_changes_need_consent(
    conn: sqlite3.Connection, changes: dict[str, Any]
) -> None:
    consent.grant(conn, "router", _router(), NOON)
    assert consent.state(conn, "router", _router(**changes)) == "changed"


@pytest.mark.parametrize(
    "changes", [{"command": "/tmp/other-codex"}, {"sandbox": "read-only"}, {"extra_args": ["-x"]}]
)
def test_agent_changes_need_consent(conn: sqlite3.Connection, changes: dict[str, Any]) -> None:
    from orkestra.config.schema import CliAgentProvider

    base = {"type": "cli_agent", "command": "codex"}
    consent.grant(conn, "codex", CliAgentProvider.model_validate(base), NOON)
    assert (
        consent.state(conn, "codex", CliAgentProvider.model_validate({**base, "timeout_s": 5}))
        == "granted"
    )
    assert (
        consent.state(conn, "codex", CliAgentProvider.model_validate({**base, **changes}))
        == "changed"
    )


def test_describe_agent_warns_about_files_and_commands() -> None:
    from orkestra.config.schema import CliAgentProvider

    lines = consent.describe(
        "codex", CliAgentProvider.model_validate({"type": "cli_agent", "command": "codex"})
    )
    text = "\n".join(lines)
    assert "write files and run commands" in text
    assert "workspace-write" in text


def test_describe_remote_names_key_variable_only() -> None:
    text = "\n".join(consent.describe("router", _router()))
    assert "https://router.test/v1" in text
    assert "environment variable K" in text
    assert "daily_usd=1.0" in text


# --- health / circuit breaker ----------------------------------------------------------


def test_three_transient_failures_open_for_five_minutes(conn: sqlite3.Connection) -> None:
    err = ProviderTransient("timeout")
    health.record_failure(conn, "p", err, NOON)
    state = health.record_failure(conn, "p", err, NOON)
    assert not state.is_open(NOON)
    state = health.record_failure(conn, "p", ProviderUnavailable("offline"), NOON)
    assert state.consecutive_failures == 3
    assert state.is_open(NOON + timedelta(minutes=4, seconds=59))
    assert not state.is_open(NOON + timedelta(minutes=5, seconds=1))
    assert health.get(conn, "p").last_error == "offline"


def test_success_resets_the_counter(conn: sqlite3.Connection) -> None:
    health.record_failure(conn, "p", ProviderTransient("x"), NOON)
    health.record_failure(conn, "p", ProviderTransient("x"), NOON)
    health.record_success(conn, "p")
    state = health.record_failure(conn, "p", ProviderTransient("x"), NOON)
    assert state.consecutive_failures == 1
    assert not state.is_open(NOON)


def test_auth_failure_opens_for_an_hour(conn: sqlite3.Connection) -> None:
    state = health.record_failure(conn, "p", ProviderAuthError("401"), NOON)
    assert state.is_open(NOON + timedelta(minutes=59))
    assert not state.is_open(NOON + timedelta(minutes=61))


@pytest.mark.parametrize("error", [ContextTooLong("big"), ProviderBadOutput("empty")])
def test_request_errors_do_not_count(conn: sqlite3.Connection, error: Exception) -> None:
    for _ in range(5):
        health.record_failure(conn, "p", error, NOON)  # type: ignore[arg-type]
    assert health.get(conn, "p").consecutive_failures == 0
