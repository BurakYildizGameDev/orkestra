"""Adaptive routing: success scores per (provider, model, tag) (Faz 12b, Mimari §20).

The score is a pure function of past runs; the router uses it only inside one tier.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from orkestra.config.schema import Config
from orkestra.routing import adaptive
from orkestra.routing.adaptive import Outcome, Score
from orkestra.routing.router import ProviderState, Snapshot, TaskNeeds, route
from orkestra.state import db

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone(timedelta(hours=3)))


def _runs(provider: str, model: str, ok: int, failed: int, *tags: str) -> list[Outcome]:
    return [Outcome(provider, model, tuple(tags), True)] * ok + [
        Outcome(provider, model, tuple(tags), False)
    ] * failed


# --- the score ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ok", "total", "expected"),
    [(0, 0, 0.5), (10, 10, 11 / 12), (0, 10, 1 / 12), (5, 10, 0.5), (7, 10, 8 / 12)],
)
def test_laplace(ok: int, total: int, expected: float) -> None:
    assert adaptive.laplace(ok, total) == pytest.approx(expected)


@dataclass
class ScoreCase:
    name: str
    runs: list[Outcome]
    tags: tuple[str, ...] = ()
    min_samples: int = 10
    expected: Score = field(default_factory=lambda: Score(0.5, 0, 0, 10, scored=False))


SCORE_CASES = [
    ScoreCase("no runs: neutral", []),
    ScoreCase("below min_samples: neutral, but the count is shown",
              _runs("p", "m", 9, 0), expected=Score(0.5, 9, 9, 10, scored=False)),
    ScoreCase("at min_samples: Laplace", _runs("p", "m", 10, 0),
              expected=Score(11 / 12, 10, 10, 10, scored=True)),
    ScoreCase("another model or provider does not count",
              _runs("p", "other", 10, 0) + _runs("q", "m", 10, 0)),
    ScoreCase("an untagged task uses untagged runs only",
              _runs("p", "m", 10, 0, "docstring") + _runs("p", "m", 2, 8),
              expected=Score(3 / 12, 10, 2, 10, scored=True)),
    ScoreCase("a tagged task uses runs with that tag", _runs("p", "m", 2, 8) +
              _runs("p", "m", 9, 1, "tests"), tags=("tests",),
              expected=Score(10 / 12, 10, 9, 10, scored=True)),
    ScoreCase("a run sharing any tag counts once", _runs("p", "m", 10, 0, "tests", "python"),
              tags=("tests", "python"), expected=Score(11 / 12, 10, 10, 10, scored=True)),
    ScoreCase("a low min_samples", _runs("p", "m", 1, 1), min_samples=2,
              expected=Score(0.5, 2, 1, 2, scored=True)),
]  # fmt: skip


@pytest.mark.parametrize("case", SCORE_CASES, ids=lambda c: c.name)
def test_score_for(case: ScoreCase) -> None:
    got = adaptive.score_for(case.runs, "p", "m", case.tags, case.min_samples)
    assert got.scored == case.expected.scored
    assert got.samples == case.expected.samples and got.ok == case.expected.ok
    assert got.value == pytest.approx(case.expected.value)


def test_an_agent_is_matched_by_provider_alone() -> None:
    runs = _runs("codex", "gpt-5-codex", 6, 0) + _runs("codex", "", 4, 0)
    got = adaptive.score_for(runs, "codex", None, (), 10)
    assert got.samples == 10 and got.scored


# --- reading runs ---------------------------------------------------------------------------


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    with closing(db.connect()) as connection:
        yield connection


def _run(conn: sqlite3.Connection, run_id: str, started: datetime, status: str, **end: Any) -> None:
    db.record_run_start(conn, run_id=run_id, task_id="t", kind="ask", started_at=started,
                        tags=end.pop("tags", ()))  # fmt: skip
    if status != "running":
        db.record_run_end(conn, run_id, status=status, **end)


def test_load_outcomes_reads_the_last_30_days_of_finished_runs(conn: sqlite3.Connection) -> None:
    _run(conn, "r1", NOW - timedelta(days=1), "ok", provider="p", model="m", tags=["tests"])
    _run(conn, "r2", NOW - timedelta(days=2), "failed", provider="p", model="m")
    _run(conn, "r3", NOW - timedelta(days=31), "ok", provider="p", model="m")  # too old
    _run(conn, "r4", NOW - timedelta(hours=1), "running")  # not finished
    _run(conn, "r5", NOW - timedelta(days=3), "escalate")  # no final provider: from usage
    conn.execute(
        "INSERT INTO usage (run_id, provider, model, day, kind, created_at) "
        "VALUES ('r5', 'q', 'n', '2026-11-12', 'actual', '2026-11-12T10:00:00+03:00')"
    )
    _run(conn, "r6", NOW - timedelta(days=4), "error")  # sent nothing: no provider at all
    got = sorted(adaptive.load_outcomes(conn, NOW), key=lambda o: (o.provider, o.model, o.ok))
    assert got == [
        Outcome("p", "m", (), False),
        Outcome("p", "m", ("tests",), True),
        Outcome("q", "n", (), False),
    ]


# --- the router (table) ------------------------------------------------------------------

PROVIDERS: dict[str, Any] = {
    "local": {
        "type": "ollama",
        "models": [
            {"id": "a", "tier": 1},
            {"id": "b", "tier": 1},
            {"id": "c", "tier": 2},
        ],
    },
}


def _config(adaptive_on: bool = True, min_samples: int = 10, **models: Any) -> Config:
    providers = {"local": {**PROVIDERS["local"]}}
    if models:
        providers["local"]["models"] = [{"id": k, **v} for k, v in models.items()]
    return Config.model_validate({
        "version": 1, "providers": providers,
        "profiles": {"all": {"min_tier": 1, "max_tier": 3}}, "defaults": {"profile": "all"},
        "routing": {"adaptive": adaptive_on, "min_samples": min_samples},
    })  # fmt: skip


def _order(config: Config, runs: list[Outcome], tags: tuple[str, ...] = ()) -> list[str]:
    scores = adaptive.scores(config, runs, tags) if config.routing.adaptive else {}
    snapshot = Snapshot(NOW, {"local": ProviderState(consent="granted")}, scores=scores)
    return [c.label for c in route(TaskNeeds(), config, snapshot).candidates]


@dataclass
class RouteCase:
    name: str
    runs: list[Outcome]
    expected: list[str]
    config: Config = field(default_factory=_config)
    tags: tuple[str, ...] = ()


ROUTE_CASES = [
    RouteCase("no history: config order", [], ["local/a", "local/b", "local/c"]),
    RouteCase("below min_samples nothing moves",
              _runs("local", "b", 9, 0) + _runs("local", "a", 0, 9),
              ["local/a", "local/b", "local/c"]),
    RouteCase("above min_samples the better model of the tier goes first",
              _runs("local", "b", 10, 0) + _runs("local", "a", 5, 5),
              ["local/b", "local/a", "local/c"]),
    RouteCase("a scored model below neutral falls behind an unscored one",
              _runs("local", "a", 1, 9), ["local/b", "local/a", "local/c"]),
    RouteCase("the tier order never changes",
              _runs("local", "c", 20, 0) + _runs("local", "a", 0, 20) + _runs("local", "b", 0, 20),
              ["local/a", "local/b", "local/c"]),
    RouteCase("adaptive off: history is ignored",
              _runs("local", "b", 10, 0) + _runs("local", "a", 0, 10),
              ["local/a", "local/b", "local/c"], config=_config(adaptive_on=False)),
    RouteCase("the score comes before priority",
              _runs("local", "b", 10, 0) + _runs("local", "a", 0, 10),
              ["local/b", "local/a"],
              config=_config(a={"tier": 1, "priority": 5}, b={"tier": 1})),
    RouteCase("equal scores: priority decides",
              _runs("local", "a", 10, 0) + _runs("local", "b", 10, 0),
              ["local/b", "local/a"],
              config=_config(a={"tier": 1}, b={"tier": 1, "priority": 1})),
    RouteCase("the task's tag picks the history",
              _runs("local", "a", 10, 0, "docs") + _runs("local", "b", 10, 0, "tests")
              + _runs("local", "a", 0, 10, "tests"),
              ["local/b", "local/a", "local/c"], tags=("tests",)),
]  # fmt: skip


@pytest.mark.parametrize("case", ROUTE_CASES, ids=lambda c: c.name)
def test_adaptive_order(case: RouteCase) -> None:
    assert _order(case.config, case.runs, case.tags) == case.expected


def test_candidates_carry_their_score_for_dry_run() -> None:
    config = _config()
    scores = adaptive.scores(config, _runs("local", "b", 10, 0), ())
    snapshot = Snapshot(NOW, {"local": ProviderState(consent="granted")}, scores=scores)
    by_label = {c.label: c.score for c in route(TaskNeeds(), config, snapshot).candidates}
    assert by_label["local/b"] == Score(11 / 12, 10, 10, 10, scored=True)
    assert by_label["local/a"] == Score(0.5, 0, 0, 10, scored=False)
    plain = Snapshot(NOW, {"local": ProviderState(consent="granted")})
    assert all(c.score is None for c in route(TaskNeeds(), _config(False), plain).candidates)
