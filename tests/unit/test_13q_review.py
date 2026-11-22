"""Faz 13q review fixes (Claude, 2026-11-23, D-127).

- ``prefer_fast``/``max_wait_s`` without ``routing.adaptive`` must not reorder by success.
- ``prefer_fast``'s "close score" grouping is transitive: the order never depends on the
  order the models are written in.
- A run's duration says something about the final model only when that model alone did
  the work: no failover, no second attempt, no cached answer.
"""

from __future__ import annotations

import itertools
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from orkestra.config.schema import Config
from orkestra.routing import adaptive
from orkestra.routing.adaptive import Outcome, Score
from orkestra.routing.router import ProviderState, Snapshot, TaskNeeds, route
from orkestra.state import db

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone(timedelta(hours=3)))


def _config(models: list[str], **routing: Any) -> Config:
    return Config.model_validate(
        {
            "version": 1,
            "providers": {
                "local": {"type": "ollama", "models": [{"id": m, "tier": 1} for m in models]}
            },
            "profiles": {"all": {"min_tier": 1, "max_tier": 3}},
            "defaults": {"profile": "all"},
            "routing": {"min_samples": 5, **routing},
        }
    )


def _order(config: Config, outcomes: list[Outcome], needs: TaskNeeds | None = None) -> list[str]:
    scores = adaptive.scores(config, outcomes, ())
    snapshot = Snapshot(NOW, {"local": ProviderState(consent="granted")}, scores=scores)
    return [c.model.id for c in route(needs or TaskNeeds(), config, snapshot).candidates]


def _history() -> list[Outcome]:
    """``first`` (written first): mostly fails, quick; ``second``: always ok, slower."""
    return (
        [Outcome("local", "first", (), True, duration_s=5.0)] * 5
        + [Outcome("local", "first", (), False)] * 10
        + [Outcome("local", "second", (), True, duration_s=8.0)] * 10
    )


def test_max_wait_without_adaptive_keeps_the_config_order() -> None:
    config = _config(["first", "second"], adaptive=False)
    # nobody exceeds 60 s: max_wait_s changes nothing, success must not sneak in
    assert _order(config, _history(), TaskNeeds(max_wait_s=60)) == ["first", "second"]


def test_max_wait_without_adaptive_still_moves_the_slow_one() -> None:
    config = _config(["first", "second"], adaptive=False)
    assert _order(config, _history(), TaskNeeds(max_wait_s=6)) == ["first", "second"]
    assert _order(config, _history(), TaskNeeds(max_wait_s=4)) == ["first", "second"]
    slow_first = [Outcome("local", "first", (), True, duration_s=50.0)] * 5 + [
        Outcome("local", "second", (), True, duration_s=8.0)
    ] * 5
    assert _order(config, slow_first, TaskNeeds(max_wait_s=10)) == ["second", "first"]


def test_prefer_fast_without_adaptive_orders_by_speed_only() -> None:
    config = _config(["second", "first"], adaptive=False, prefer_fast=True)
    candidates = route(
        TaskNeeds(),
        config,
        Snapshot(
            NOW,
            {"local": ProviderState(consent="granted")},
            scores=adaptive.scores(config, _history(), ()),
        ),
    ).candidates
    # success is not used without routing.adaptive (and not shown): the quicker one first
    assert [c.model.id for c in candidates] == ["first", "second"]
    assert all(c.score is None for c in candidates)
    assert [c.median_duration_s for c in candidates] == [5.0, 8.0]


def _scored(value: float, duration: float) -> Score:
    return Score(value, 20, 10, 5, scored=True, median_duration_s=duration)


def test_prefer_fast_close_scores_are_grouped_transitively() -> None:
    # x~y (0.04) and y~z (0.04) but x vs z (0.08) is a clear gap: pairwise comparison
    # cycles (y<x, z<y, x<z). Groups start at the best score: {x, y}, then {z}.
    scores = {
        ("local", "x"): _scored(0.60, 30.0),
        ("local", "y"): _scored(0.56, 20.0),
        ("local", "z"): _scored(0.52, 10.0),
    }
    for models in itertools.permutations(["x", "y", "z"]):
        config = _config(list(models), adaptive=True, prefer_fast=True)
        snapshot = Snapshot(NOW, {"local": ProviderState(consent="granted")}, scores=scores)
        got = [c.model.id for c in route(TaskNeeds(), config, snapshot).candidates]
        assert got == ["y", "x", "z"], models


# --- durations from the runs table ----------------------------------------------------------


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    with closing(db.connect()) as connection:
        yield connection


def _run(conn: sqlite3.Connection, run_id: str, **end: Any) -> None:
    db.record_run_start(conn, run_id=run_id, task_id="t", kind="ask",
                        started_at=NOW - timedelta(days=1))  # fmt: skip
    db.record_run_end(conn, run_id, status="ok", provider="p", model="m", duration_s=30.0, **end)


def _durations(conn: sqlite3.Connection) -> list[float | None]:
    return [o.duration_s for o in adaptive.load_outcomes(conn, NOW) if o.model == "m"]


def test_a_single_attempt_run_gives_its_duration(conn: sqlite3.Connection) -> None:
    _run(conn, "r1", attempts=1, worker_output_tokens=40)
    assert _durations(conn) == [30.0]


def test_a_run_with_more_attempts_gives_no_duration(conn: sqlite3.Connection) -> None:
    # the time includes earlier attempts (retries, or another model before a failover)
    _run(conn, "r1", attempts=2, worker_output_tokens=40)
    assert _durations(conn) == [None]


def test_a_cached_answer_gives_no_duration(conn: sqlite3.Connection) -> None:
    _run(conn, "r1", attempts=1, worker_output_tokens=0)  # nothing generated: from the cache
    assert _durations(conn) == [None]


def test_a_replaced_model_makes_the_final_duration_unknown(conn: sqlite3.Connection) -> None:
    _run(conn, "r1", attempts=1, worker_output_tokens=40)
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO usage (run_id, provider, model, day, prompt_tokens, completion_tokens, "
            "cost_usd, requests, runs, estimated, kind, created_at) "
            "VALUES ('r1', 'q', 'n', '2026-11-22', 10, 12, 0, 1, 0, 0, 'actual', ?)",
            ((NOW - timedelta(days=1)).isoformat(),),
        )
    assert _durations(conn) == [None]
