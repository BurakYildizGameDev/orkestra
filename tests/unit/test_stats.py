"""``orkestra stats``: success, attempts, tokens, cost and time per provider and tag (Faz 7b)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from orkestra.errors import UsageError
from orkestra.state import db, stats

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone(timedelta(hours=3)))


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "state.db")) as connection:
        yield connection


def _run(
    conn: sqlite3.Connection, run_id: str, *, status: str, provider: str | None,
    ago: timedelta = timedelta(hours=1), attempts: int = 1, duration: float = 2.0,
    tags: tuple[str, ...] = (),
) -> None:  # fmt: skip
    started = NOW - ago
    db.record_run_start(conn, run_id=run_id, task_id=run_id, kind="ask", started_at=started,
                        tags=tags)  # fmt: skip
    if status != "running":
        db.record_run_end(conn, run_id, status=status, provider=provider, model="m",
                          attempts=attempts, duration_s=duration, finished_at=started)  # fmt: skip


def _usage(
    conn: sqlite3.Connection, run_id: str, provider: str, prompt: int, completion: int,
    cost: float | None, *, kind: str = "actual", ago: timedelta = timedelta(hours=1),
    estimated: bool = False,
) -> None:  # fmt: skip
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO usage (run_id, provider, model, day, prompt_tokens, completion_tokens, "
            "cost_usd, requests, runs, estimated, kind, created_at) "
            "VALUES (?, ?, 'm', '2026-11-11', ?, ?, ?, 1, 1, ?, ?, ?)",
            (run_id, provider, prompt, completion, cost, int(estimated), kind,
             (NOW - ago).isoformat()),
        )  # fmt: skip


@pytest.mark.parametrize(
    ("text", "delta"),
    [("7d", timedelta(days=7)), ("24h", timedelta(hours=24)), ("30m", timedelta(minutes=30)),
     ("1d", timedelta(days=1))],
)  # fmt: skip
def test_since_durations(text: str, delta: timedelta) -> None:
    assert stats.parse_since(text) == delta


@pytest.mark.parametrize("text", ["", "soon", "7", "-1d", "0d", "1w", "d7", "1.5d"])
def test_bad_since_is_a_usage_error(text: str) -> None:
    with pytest.raises(UsageError):
        stats.parse_since(text)


def test_per_provider_numbers(conn: sqlite3.Connection) -> None:
    _run(conn, "r1", status="ok", provider="ollama", attempts=1, duration=2.0)
    _run(conn, "r2", status="failed", provider="ollama", attempts=3, duration=4.0)
    _run(conn, "r3", status="ok", provider="cloud", attempts=2, duration=1.0)
    _usage(conn, "r1", "ollama", 100, 50, 0.0)
    _usage(conn, "r2", "ollama", 200, 60, 0.0)
    _usage(conn, "r2", "cloud", 10, 5, 0.25)  # a failover: tokens count for the provider used
    _usage(conn, "r3", "cloud", 30, 20, 0.5, estimated=True)
    report = stats.collect(conn, since=NOW - timedelta(days=7), now=NOW)
    rows = {row.name: row for row in report.providers}
    assert rows["ollama"].runs == 2 and rows["ollama"].ok == 1
    assert rows["ollama"].success_rate == 0.5
    assert rows["ollama"].avg_attempts == 2.0 and rows["ollama"].avg_duration_s == 3.0
    assert (rows["ollama"].prompt_tokens, rows["ollama"].completion_tokens) == (300, 110)
    assert rows["cloud"].cost_usd == pytest.approx(0.75) and rows["cloud"].estimated
    assert not rows["ollama"].estimated
    assert report.totals.runs == 3 and report.totals.ok == 2
    assert report.totals.cost_usd == pytest.approx(0.75)


def test_old_runs_reservations_and_running_runs_are_left_out(conn: sqlite3.Connection) -> None:
    _run(conn, "old", status="ok", provider="ollama", ago=timedelta(days=10))
    _usage(conn, "old", "ollama", 999, 999, 9.0, ago=timedelta(days=10))
    _run(conn, "now", status="ok", provider="ollama")
    _usage(conn, "now", "ollama", 10, 5, 0.0)
    _usage(conn, "now", "ollama", 5000, 5000, 1.0, kind="reservation")
    _run(conn, "busy", status="running", provider=None)
    report = stats.collect(conn, since=NOW - timedelta(days=7), now=NOW)
    (row,) = report.providers
    assert row.name == "ollama" and row.runs == 1 and row.prompt_tokens == 10
    assert report.running == 1  # shown, but not in the success rate


def test_a_run_without_a_final_provider_counts_for_the_last_one_it_used(
    conn: sqlite3.Connection,
) -> None:
    # An escalated run has no provider in its envelope, but its requests went to workers:
    # its failure must lower their success rate, not disappear under "no provider".
    _run(conn, "r1", status="escalate", provider=None)
    _usage(conn, "r1", "ollama", 10, 5, 0.0)
    _usage(conn, "r1", "cloud", 10, 5, 0.1)
    _run(conn, "r2", status="ok", provider="ollama")
    report = stats.collect(conn, since=NOW - timedelta(days=7), now=NOW)
    rows = {row.name: (row.runs, row.ok, row.escalate) for row in report.providers}
    assert rows == {"ollama": (1, 1, 0), "cloud": (1, 0, 1)}


def test_a_run_without_a_provider_is_counted_as_unknown(conn: sqlite3.Connection) -> None:
    _run(conn, "r1", status="error", provider=None)
    report = stats.collect(conn, since=NOW - timedelta(days=7), now=NOW)
    assert [(row.name, row.runs, row.ok) for row in report.providers] == [(None, 1, 0)]


def test_per_tag_numbers(conn: sqlite3.Connection) -> None:
    _run(conn, "r1", status="ok", provider="ollama", tags=("docs",))
    _run(conn, "r2", status="failed", provider="ollama", tags=("docs", "tests"))
    _run(conn, "r3", status="ok", provider="ollama")
    _usage(conn, "r2", "ollama", 10, 5, 0.1)
    report = stats.collect(conn, since=NOW - timedelta(days=7), now=NOW)
    tags = {row.name: row for row in report.tags}
    assert set(tags) == {"docs", "tests", None}  # None: runs without tags
    assert tags["docs"].runs == 2 and tags["docs"].ok == 1 and tags["docs"].success_rate == 0.5
    assert tags["tests"].cost_usd == pytest.approx(0.1)
    assert tags[None].runs == 1


@pytest.mark.parametrize("text", ["99999999d", "9999999999d", "999999999999999999999m"])
def test_a_huge_since_is_a_usage_error_not_an_overflow(text: str) -> None:
    with pytest.raises(UsageError):
        stats.parse_since(text)


def test_tokens_belong_to_the_runs_in_the_window(conn: sqlite3.Connection) -> None:
    # The run started before the window, its request was settled inside it: both are out,
    # so the totals still match the provider and tag rows.
    _run(conn, "early", status="ok", provider="ollama", ago=timedelta(days=7, minutes=5),
         tags=("docs",))  # fmt: skip
    _usage(conn, "early", "ollama", 100, 50, 1.0, ago=timedelta(days=6, hours=23))
    report = stats.collect(conn, since=NOW - timedelta(days=7), now=NOW)
    assert report.providers == () and report.totals.prompt_tokens == 0
    assert report.totals.cost_usd == 0


def test_times_with_another_utc_offset_are_compared_as_instants(
    conn: sqlite3.Connection,
) -> None:
    # Recorded at 08:30 UTC (before a time zone or daylight saving change); the window starts
    # at 08:00 UTC, written as 11:00+03:00. As strings "08:30+00:00" < "11:00+03:00".
    started = datetime(2026, 11, 11, 8, 30, tzinfo=UTC)
    db.record_run_start(conn, run_id="r1", task_id="r1", kind="ask", started_at=started)
    db.record_run_end(conn, "r1", status="ok", provider="ollama", attempts=1, duration_s=1.0)
    report = stats.collect(conn, since=NOW - timedelta(hours=1), now=NOW)  # 08:00 UTC
    assert report.totals.runs == 1


def test_no_runs_is_an_empty_report(conn: sqlite3.Connection) -> None:
    report = stats.collect(conn, since=NOW - timedelta(days=7), now=NOW)
    assert report.providers == () and report.tags == () and report.totals.runs == 0
    assert report.totals.success_rate is None
