"""Adaptive routing: how well each model did on this kind of task (Faz 12b, Mimari §20).

- Source: finished runs of the last 30 days (``runs``). A run counts for the provider and
  model that gave its final result; one without (escalated, failed before an answer) counts
  for its last settled request (``usage``), as in ``orkestra stats``. A run that sent nothing
  does not count.
- The group is (provider, model, tag); untagged tasks use untagged runs. A task with several
  tags uses the runs that share any of them, each run once.
- Score: Laplace-smoothed success rate ``(ok + 1) / (total + 2)``. Below ``min_samples`` the
  score is neutral (0.5), so a model that was tried a few times is not pushed aside.
- The router only orders inside one tier with it (``router.route``); tiers never move.

Everything here except ``load_outcomes`` is a pure function of the outcomes.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from orkestra.config.schema import CliAgentProvider, Config

NEUTRAL = 0.5
WINDOW = timedelta(days=30)
FINISHED = ("ok", "failed", "escalate", "error")
_OFFSET_MARGIN = timedelta(days=2)  # stored times keep their day's UTC offset


@dataclass(frozen=True)
class Outcome:
    provider: str
    model: str
    tags: tuple[str, ...]
    ok: bool


@dataclass(frozen=True)
class Score:
    value: float
    samples: int  # matching runs
    ok: int
    needed: int  # min_samples
    scored: bool  # samples >= needed; otherwise value is NEUTRAL


ScoreKey = tuple[str, str]  # provider, candidate model id


def laplace(ok: int, total: int) -> float:
    return (ok + 1) / (total + 2)


def _matches(outcome: Outcome, tags: Sequence[str]) -> bool:
    if not tags:
        return not outcome.tags
    return any(tag in outcome.tags for tag in tags)


def score_for(
    outcomes: Iterable[Outcome],
    provider: str,
    model: str | None,
    tags: Sequence[str],
    min_samples: int,
) -> Score:
    """``model=None``: a code agent, matched by provider alone (its model may vary)."""
    total = ok = 0
    for outcome in outcomes:
        if outcome.provider != provider or (model is not None and outcome.model != model):
            continue
        if _matches(outcome, tags):
            total += 1
            ok += outcome.ok
    if total < min_samples:
        return Score(NEUTRAL, total, ok, min_samples, scored=False)
    return Score(laplace(ok, total), total, ok, min_samples, scored=True)


def agent_model_id(cfg: CliAgentProvider) -> str:
    """The id the router gives a code agent's candidate (``router._agent_candidate``)."""
    return cfg.model or cfg.kind or "agent"


def scores(
    config: Config,
    outcomes: Iterable[Outcome],
    tags: Sequence[str],
    names: Sequence[str] | None = None,
) -> dict[ScoreKey, Score]:
    """A score for every model of the enabled providers in ``names`` (default: all)."""
    found = list(outcomes)
    minimum = config.routing.min_samples
    result: dict[ScoreKey, Score] = {}
    for name in config.providers if names is None else names:
        cfg = config.providers[name]
        if not cfg.enabled:
            continue
        if isinstance(cfg, CliAgentProvider):
            result[(name, agent_model_id(cfg))] = score_for(found, name, None, tags, minimum)
            continue
        for model in cfg.models:
            result[(name, model.id)] = score_for(found, name, model.id, tags, minimum)
    return result


def _tags(raw: str | None) -> tuple[str, ...]:
    try:
        value = json.loads(raw) if raw else []
    except ValueError:
        return ()
    return tuple(str(tag) for tag in value) if isinstance(value, list) else ()


def _last_requests(
    conn: sqlite3.Connection, run_ids: Sequence[str]
) -> Mapping[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for run_id in run_ids:
        row = conn.execute(
            "SELECT provider, model FROM usage WHERE run_id = ? AND kind = 'actual' "
            "ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is not None and row[0]:
            found[run_id] = (row[0], row[1] or "")
    return found


def load_outcomes(
    conn: sqlite3.Connection, now: datetime, window: timedelta = WINDOW
) -> list[Outcome]:
    since = now - window
    rows = conn.execute(
        "SELECT run_id, status, provider, model, tags, started_at FROM runs "
        f"WHERE started_at >= ? AND status IN ({', '.join('?' for _ in FINISHED)})",
        ((since - _OFFSET_MARGIN).isoformat(), *FINISHED),
    ).fetchall()
    chosen = []
    for row in rows:
        try:
            started = datetime.fromisoformat(row["started_at"])
        except (TypeError, ValueError):
            continue
        if started >= since:
            chosen.append(row)
    missing = _last_requests(conn, [r["run_id"] for r in chosen if not r["provider"]])
    outcomes: list[Outcome] = []
    for row in chosen:
        if row["provider"]:
            provider, model = row["provider"], row["model"] or ""
        elif row["run_id"] in missing:
            provider, model = missing[row["run_id"]]
        else:
            continue  # it sent nothing
        outcomes.append(Outcome(provider, model, _tags(row["tags"]), row["status"] == "ok"))
    return outcomes
