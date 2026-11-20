"""``gc`` removes old ``runs``/``usage``/``queue`` rows (düzeltme-fable a, D-104)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from orkestra.routing import adaptive
from orkestra.state import db, retention, stats

NOW = datetime(2026, 11, 20, 12, 0).astimezone()


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    with closing(db.connect()) as connection:
        yield connection


def _run(conn: sqlite3.Connection, run_id: str, days_ago: float, **fields: object) -> None:
    started = NOW - timedelta(days=days_ago)
    db.record_run_start(conn, run_id=run_id, task_id="t", kind="edit", started_at=started)
    db.update_run(conn, run_id, status="ok", provider="p", model="m", **fields)
    conn.execute(
        "INSERT INTO usage (run_id, provider, model, day, prompt_tokens, completion_tokens, "
        "cost_usd, requests, runs, estimated, kind, created_at) "
        "VALUES (?, 'p', 'm', ?, 10, 5, 0, 1, 1, 0, 'actual', ?)",
        (run_id, started.date().isoformat(), started.isoformat()),
    )
    conn.commit()


def _queue(conn: sqlite3.Connection, status: str, days_ago: float) -> int:
    at = (NOW - timedelta(days=days_ago)).isoformat()
    finished = at if status in ("done", "failed") else None
    cursor = conn.execute(
        "INSERT INTO queue (path, kind, status, added_at, finished_at, workdir) "
        "VALUES ('x.yaml', 'task', ?, ?, ?, '.')",
        (status, at, finished),
    )
    conn.commit()
    return int(cursor.lastrowid or 0)


def _ids(conn: sqlite3.Connection, table: str, column: str) -> set[object]:
    return {row[0] for row in conn.execute(f"SELECT {column} FROM {table}")}


def test_old_rows_go_and_recent_ones_stay(conn: sqlite3.Connection) -> None:
    _run(conn, "old", 100)
    _run(conn, "new", 3)
    pruned = retention.prune(conn, NOW - timedelta(days=60), dry_run=False)
    assert pruned == retention.Pruned(runs=1, usage=1, queue=0)
    assert _ids(conn, "runs", "run_id") == {"new"}
    assert _ids(conn, "usage", "run_id") == {"new"}


def test_dry_run_only_counts(conn: sqlite3.Connection) -> None:
    _run(conn, "old", 100)
    _queue(conn, "done", 100)
    pruned = retention.prune(conn, NOW - timedelta(days=60), dry_run=True)
    assert pruned == retention.Pruned(runs=1, usage=1, queue=1)
    assert _ids(conn, "runs", "run_id") == {"old"}
    assert len(_ids(conn, "queue", "id")) == 1


def test_finished_and_removed_queue_items_go_pending_and_running_stay(
    conn: sqlite3.Connection,
) -> None:
    done = _queue(conn, "done", 100)
    failed = _queue(conn, "failed", 100)
    removed = _queue(conn, "removed", 100)
    pending = _queue(conn, "pending", 100)
    running = _queue(conn, "running", 100)
    recent = _queue(conn, "done", 2)
    pruned = retention.prune(conn, NOW - timedelta(days=60), dry_run=False)
    assert pruned.queue == 3
    assert _ids(conn, "queue", "id") == {pending, running, recent}
    assert not {done, failed, removed} & _ids(conn, "queue", "id")


def test_a_run_whose_worktree_is_still_on_disk_stays(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    tree = tmp_path / "wt"
    tree.mkdir()
    _run(conn, "unapplied", 100, worktree=str(tree), applied=0)
    _run(conn, "gone", 100, worktree=str(tmp_path / "missing"), applied=0)
    pruned = retention.prune(conn, NOW - timedelta(days=60), dry_run=False)
    assert pruned.runs == 1
    assert _ids(conn, "runs", "run_id") == {"unapplied"}
    assert _ids(conn, "usage", "run_id") == {"unapplied"}


def test_dry_run_treats_worktrees_gc_will_remove_as_gone(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    tree = tmp_path / "wt"
    tree.mkdir()
    _run(conn, "old", 100, worktree=str(tree))
    pruned = retention.prune(
        conn, NOW - timedelta(days=60), dry_run=True, removing=frozenset({tree})
    )
    assert pruned.runs == 1


def test_usage_without_a_run_goes_by_its_day(conn: sqlite3.Connection) -> None:
    for days_ago in (100, 1):
        day = (NOW - timedelta(days=days_ago)).date().isoformat()
        conn.execute(
            "INSERT INTO usage (run_id, provider, model, day, prompt_tokens, completion_tokens,"
            " cost_usd, requests, runs, estimated, kind, created_at)"
            " VALUES (NULL, 'p', 'm', ?, 1, 1, 0, 1, 0, 0, 'actual', ?)",
            (day, NOW.isoformat()),
        )
    conn.commit()
    pruned = retention.prune(conn, NOW - timedelta(days=60), dry_run=False)
    assert pruned.usage == 1
    assert conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0] == 1


def test_row_cutoff_never_cuts_into_the_learning_window() -> None:
    assert retention.row_cutoff(NOW, timedelta(days=0)) == NOW - retention.MIN_KEEP
    assert retention.row_cutoff(NOW, timedelta(days=90)) == NOW - timedelta(days=90)
    assert retention.MIN_KEEP >= adaptive.WINDOW


def test_stats_and_adaptive_are_unchanged_after_pruning(conn: sqlite3.Connection) -> None:
    for index in range(12):
        _run(conn, f"recent-{index}", 1 + index)
    for index in range(5):
        _run(conn, f"ancient-{index}", 200 + index)
    since = NOW - adaptive.WINDOW
    before = (stats.to_dict(stats.collect(conn, since=since, now=NOW)),
              adaptive.load_outcomes(conn, NOW))  # fmt: skip
    retention.prune(conn, retention.row_cutoff(NOW, timedelta(days=0)), dry_run=False)
    after = (stats.to_dict(stats.collect(conn, since=since, now=NOW)),
             adaptive.load_outcomes(conn, NOW))  # fmt: skip
    assert before == after


# --- code review (PR #39) ---------------------------------------------------------------


def _priced(conn: sqlite3.Connection, run_id: str, days_ago: float, cost: float) -> None:
    started = NOW - timedelta(days=days_ago)
    db.record_run_start(conn, run_id=run_id, task_id="t", kind="ask", started_at=started)
    conn.execute(
        "INSERT INTO usage (run_id, provider, model, day, prompt_tokens, completion_tokens, "
        "cost_usd, requests, runs, estimated, kind, created_at) "
        "VALUES (?, 'paid', 'm1', ?, 1000, 1000, ?, 1, 1, 0, 'actual', ?)",
        (run_id, started.date().isoformat(), cost, started.isoformat()),
    )
    conn.commit()


def test_the_learned_price_of_an_unused_model_survives(conn: sqlite3.Connection) -> None:
    from orkestra.providers import pricing

    _priced(conn, "cheap", 100, 0.001)
    _priced(conn, "dear", 90, 0.004)
    before = pricing._from_history(conn, "paid", "m1")  # pyright: ignore[reportPrivateUsage]
    pruned = retention.prune(conn, NOW - timedelta(days=60), dry_run=False)
    assert pruned.runs == 2 and pruned.usage == 1
    after = pricing._from_history(conn, "paid", "m1")  # pyright: ignore[reportPrivateUsage]
    assert before is not None and after == before


def test_a_run_without_a_readable_start_and_its_usage_stay(conn: sqlite3.Connection) -> None:
    _run(conn, "today", 0)
    conn.execute("UPDATE runs SET started_at = NULL WHERE run_id = 'today'")
    _run(conn, "garbled", 0)
    conn.execute("UPDATE runs SET started_at = 'yesterday-ish' WHERE run_id = 'garbled'")
    conn.commit()
    pruned = retention.prune(conn, NOW - timedelta(days=60), dry_run=False)
    assert pruned == retention.Pruned(runs=0, usage=0, queue=0)
    assert _ids(conn, "usage", "run_id") == {"today", "garbled"}


def test_a_dry_run_does_not_take_the_write_lock(conn: sqlite3.Connection) -> None:
    _run(conn, "old", 100)
    with closing(db.connect()) as writer:
        writer.execute("BEGIN IMMEDIATE")  # a worker writing at the same time
        conn.execute("PRAGMA busy_timeout = 0")
        pruned = retention.prune(conn, NOW - timedelta(days=60), dry_run=True)
        writer.execute("ROLLBACK")
    assert pruned.runs == 1
