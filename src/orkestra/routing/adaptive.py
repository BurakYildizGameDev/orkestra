"""Adaptive routing: how well each model did on this kind of task (Faz 12b, Mimari §20).

- Source: runs of the last 30 days that ended ``ok``, ``failed`` or ``escalate``. ``error``
  runs (Ctrl+C, a disk error, every provider offline) say nothing about a model's quality and
  are left out (D-075).
- In a run, the model that gave the final result counts with the run's status. Every other
  model that **answered** in that run (``usage`` with completion tokens) and was replaced, by
  a retry on another model, a failover or an escalation, counts as a failure, once per run. A
  request that got no answer (offline, refused) does not count. A run without a final model
  (escalated to the chief) counts as a failure for the last model that answered.
- The group is (provider, model, tag); untagged tasks use untagged runs. A task with several
  tags uses the runs that share any of them, each run once.
- Score: Laplace-smoothed success rate ``(ok + 1) / (total + 2)``. Below ``min_samples`` the
  score is neutral (0.5), so a model that was tried a few times is not pushed aside.
- The router only orders inside one tier with it (``router.route``); tiers never move.

Everything here except ``load_outcomes`` is a pure function of the outcomes.
"""

from __future__ import annotations

import sqlite3
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from orkestra.config.schema import CliAgentProvider, Config
from orkestra.state.stats import OFFSET_MARGIN, parse_started, parse_tags

NEUTRAL = 0.5
WINDOW = timedelta(days=30)
SCORED = ("ok", "failed", "escalate")  # not "error": D-075


@dataclass(frozen=True)
class Outcome:
    provider: str
    model: str
    tags: tuple[str, ...]
    ok: bool
    duration_s: float | None = None


@dataclass(frozen=True)
class Score:
    value: float
    samples: int  # matching runs
    ok: int
    needed: int  # min_samples
    scored: bool  # samples >= needed; otherwise value is NEUTRAL
    median_duration_s: float | None = None


ScoreKey = tuple[str, str]  # provider, candidate model id


def laplace(ok: int, total: int) -> float:
    return (ok + 1) / (total + 2)


def _matches(outcome: Outcome, tags: Sequence[str]) -> bool:
    if not tags:
        return not outcome.tags
    return any(tag in outcome.tags for tag in tags)


def median_duration_for(
    outcomes: Iterable[Outcome],
    provider: str,
    model: str | None,
    tags: Sequence[str],
    min_samples: int,
) -> float | None:
    """The median duration in seconds for (provider, model, tags) from runs that ended 'ok'.

    Below ``min_samples``, returns None.
    """
    durations: list[float] = []
    for outcome in outcomes:
        if not outcome.ok or outcome.duration_s is None:
            continue
        if outcome.provider != provider or (model is not None and outcome.model != model):
            continue
        if _matches(outcome, tags):
            durations.append(outcome.duration_s)
    if len(durations) < min_samples:
        return None
    return float(statistics.median(durations))


def score_for(
    outcomes: Iterable[Outcome],
    provider: str,
    model: str | None,
    tags: Sequence[str],
    min_samples: int,
) -> Score:
    """``model=None``: a code agent, matched by provider alone (its model may vary)."""
    found = list(outcomes)
    total = ok = 0
    for outcome in found:
        if outcome.provider != provider or (model is not None and outcome.model != model):
            continue
        if _matches(outcome, tags):
            total += 1
            ok += outcome.ok
    median = median_duration_for(found, provider, model, tags, min_samples)
    if total < min_samples:
        return Score(NEUTRAL, total, ok, min_samples, scored=False, median_duration_s=median)
    return Score(laplace(ok, total), total, ok, min_samples, scored=True, median_duration_s=median)


def agent_model_id(cfg: CliAgentProvider) -> str:
    """The id the router gives a code agent's candidate (``router._agent_candidate``)."""
    return cfg.model or cfg.kind or "agent"


def scores(
    config: Config,
    outcomes: Iterable[Outcome],
    tags: Sequence[str],
    names: Sequence[str] | None = None,
    *,
    extra: tuple[str, str] | None = None,
) -> dict[ScoreKey, Score]:
    """A score for every model of the enabled providers in ``names`` (default: all), and for
    ``extra`` (provider, model id): a model the task names that the config does not list."""
    found = list(outcomes)
    minimum = config.routing.min_samples
    result: dict[ScoreKey, Score] = {}
    if extra is not None:
        result[extra] = score_for(found, extra[0], extra[1], tags, minimum)
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


def _answered(conn: sqlite3.Connection, since: datetime) -> Mapping[str, list[tuple[str, str]]]:
    """Per run, the (provider, model) of every request that got an answer, in order (one
    query for the whole window)."""
    found: dict[str, list[tuple[str, str]]] = {}
    rows = conn.execute(
        "SELECT run_id, provider, model FROM usage WHERE kind = 'actual' "
        "AND completion_tokens > 0 AND provider IS NOT NULL AND run_id IN "
        "(SELECT run_id FROM runs WHERE started_at >= ?) ORDER BY id",
        ((since - OFFSET_MARGIN).isoformat(),),
    ).fetchall()
    for run_id, provider, model in rows:
        found.setdefault(run_id, []).append((provider, model or ""))
    return found


def _replaced(used: Sequence[tuple[str, str]], final: tuple[str, str]) -> list[tuple[str, str]]:
    """Models that answered but did not give the final result (an agent: same provider)."""
    provider, model = final
    return [
        pair for pair in dict.fromkeys(used)
        if not (pair[0] == provider and (pair[1] == model or not model or not pair[1]))
    ]  # fmt: skip


def load_outcomes(
    conn: sqlite3.Connection, now: datetime, window: timedelta = WINDOW
) -> list[Outcome]:
    since = now - window
    rows = conn.execute(
        "SELECT run_id, status, provider, model, tags, started_at, duration_s FROM runs "
        f"WHERE started_at >= ? AND status IN ({', '.join('?' for _ in SCORED)})",
        ((since - OFFSET_MARGIN).isoformat(), *SCORED),
    ).fetchall()
    answered = _answered(conn, since)
    outcomes: list[Outcome] = []
    for row in rows:
        started = parse_started(row["started_at"])
        if started is None or started < since:
            continue
        used = answered.get(row["run_id"], [])
        if row["provider"]:
            final = (row["provider"], row["model"] or "")
        elif used:
            final = used[-1]
        else:
            continue  # nothing answered: nothing to say about a model
        tags = parse_tags(row["tags"])
        is_ok = row["status"] == "ok" and bool(row["provider"])
        duration = float(row["duration_s"]) if (is_ok and row["duration_s"] is not None) else None
        outcomes.append(Outcome(*final, tags, is_ok, duration))
        outcomes.extend(Outcome(*pair, tags, False, None) for pair in _replaced(used, final))
    return outcomes
