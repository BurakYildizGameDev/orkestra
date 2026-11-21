"""Tests for task field max_wait_s (Faz 13q-c, Mimari §4.2, §7, D-125)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from orkestra.config.schema import Config
from orkestra.routing import adaptive
from orkestra.routing.adaptive import Outcome
from orkestra.routing.router import ProviderState, Snapshot, TaskNeeds, route
from orkestra.tasks.spec import TaskSpec

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone(timedelta(hours=3)))

PROVIDERS: dict[str, Any] = {
    "local": {
        "type": "ollama",
        "models": [
            {"id": "slow", "tier": 1},
            {"id": "fast", "tier": 1},
            {"id": "tier2", "tier": 2},
        ],
    },
}


def _config() -> Config:
    return Config.model_validate(
        {
            "version": 1,
            "providers": PROVIDERS,
            "profiles": {"all": {"min_tier": 1, "max_tier": 3}},
            "defaults": {"profile": "all"},
            "routing": {"adaptive": True, "min_samples": 5},
        }
    )


def _runs() -> list[Outcome]:
    return (
        [Outcome("local", "slow", (), True, duration_s=20.0)] * 5
        + [Outcome("local", "fast", (), True, duration_s=5.0)] * 5
        + [Outcome("local", "tier2", (), True, duration_s=1.0)] * 5
    )


def test_task_spec_max_wait_s_validation() -> None:
    # Optional positive integer
    spec = TaskSpec.model_validate({"id": "t", "kind": "ask", "prompt": "hello", "max_wait_s": 30})
    assert spec.max_wait_s == 30

    # Default is None
    spec_default = TaskSpec.model_validate({"id": "t", "kind": "ask", "prompt": "hello"})
    assert spec_default.max_wait_s is None

    # Invalid values: 0, negative, string
    with pytest.raises(ValidationError):
        TaskSpec.model_validate({"id": "t", "kind": "ask", "prompt": "hello", "max_wait_s": 0})

    with pytest.raises(ValidationError):
        TaskSpec.model_validate({"id": "t", "kind": "ask", "prompt": "hello", "max_wait_s": -10})

    with pytest.raises(ValidationError):
        TaskSpec.model_validate({"id": "t", "kind": "ask", "prompt": "hello", "max_wait_s": "fast"})


def test_slow_candidate_moved_to_end_of_tier() -> None:
    config = _config()
    runs = _runs()
    scores = adaptive.scores(config, runs, ())
    snapshot = Snapshot(NOW, {"local": ProviderState(consent="granted")}, scores=scores)

    # Without max_wait_s: slow (20s) and fast (5s) have equal score, config order puts "slow" first
    needs_none = TaskNeeds(max_wait_s=None)
    order_none = [c.model.id for c in route(needs_none, config, snapshot).candidates]
    assert order_none == ["slow", "fast", "tier2"]

    # With max_wait_s=10: slow (20s > 10s) is moved to end of Tier 1
    needs_wait = TaskNeeds(max_wait_s=10)
    candidates = route(needs_wait, config, snapshot).candidates
    assert [c.model.id for c in candidates] == ["fast", "slow", "tier2"]
    assert candidates[0].wait_exceeded is False
    assert candidates[1].wait_exceeded is True


def test_single_candidate_still_tried_when_exceeding_max_wait() -> None:
    # Only "slow" in Tier 1
    config = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "local": {
                    "type": "ollama",
                    "models": [{"id": "slow", "tier": 1}],
                }
            },
            "profiles": {"all": {"min_tier": 1, "max_tier": 3}},
            "defaults": {"profile": "all"},
            "routing": {"adaptive": True, "min_samples": 5},
        }
    )
    runs = [Outcome("local", "slow", (), True, duration_s=20.0)] * 5
    scores = adaptive.scores(config, runs, ())
    snapshot = Snapshot(NOW, {"local": ProviderState(consent="granted")}, scores=scores)

    # Exceeds max_wait_s=10, but not eliminated: single candidate is still tried!
    needs = TaskNeeds(max_wait_s=10)
    routed = route(needs, config, snapshot)
    assert [c.model.id for c in routed.candidates] == ["slow"]
    assert routed.candidates[0].wait_exceeded is True


def test_candidates_within_max_wait_not_moved() -> None:
    config = _config()
    runs = _runs()
    scores = adaptive.scores(config, runs, ())
    snapshot = Snapshot(NOW, {"local": ProviderState(consent="granted")}, scores=scores)

    # max_wait_s=30: both 20s and 5s are <= 30s -> normal order preserved
    needs = TaskNeeds(max_wait_s=30)
    routed = route(needs, config, snapshot)
    assert [c.model.id for c in routed.candidates] == ["slow", "fast", "tier2"]
    assert all(not c.wait_exceeded for c in routed.candidates)


def test_max_wait_never_changes_tier_order() -> None:
    config = _config()
    runs = _runs()
    scores = adaptive.scores(config, runs, ())
    snapshot = Snapshot(NOW, {"local": ProviderState(consent="granted")}, scores=scores)

    # "slow" (Tier 1) exceeds max_wait_s (20s > 10s).
    # "tier2" (Tier 2) does not (1s <= 10s).
    # "slow" stays within Tier 1, so it is still tried BEFORE "tier2"!
    needs = TaskNeeds(max_wait_s=10)
    order = [c.model.id for c in route(needs, config, snapshot).candidates]
    assert order == ["fast", "slow", "tier2"]
