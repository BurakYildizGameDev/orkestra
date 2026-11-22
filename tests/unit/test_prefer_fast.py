"""Tests for routing.prefer_fast (Faz 13q-b, Mimari §7, D-124)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from orkestra.config.schema import Config
from orkestra.routing import adaptive
from orkestra.routing.adaptive import Outcome
from orkestra.routing.router import ProviderState, Snapshot, TaskNeeds, route

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


def _config(prefer_fast: bool = False, min_samples: int = 5, **models: Any) -> Config:
    providers = {"local": {**PROVIDERS["local"]}}
    if models:
        providers["local"]["models"] = [{"id": k, **v} for k, v in models.items()]
    return Config.model_validate(
        {
            "version": 1,
            "providers": providers,
            "profiles": {"all": {"min_tier": 1, "max_tier": 3}},
            "defaults": {"profile": "all"},
            "routing": {
                "adaptive": True,
                "min_samples": min_samples,
                "prefer_fast": prefer_fast,
            },
        }
    )


def _route_models(config: Config, outcomes: list[Outcome]) -> list[str]:
    scores = adaptive.scores(config, outcomes, ())
    snapshot = Snapshot(NOW, {"local": ProviderState(consent="granted")}, scores=scores)
    return [c.model.id for c in route(TaskNeeds(), config, snapshot).candidates]


def test_schema_prefer_fast_default_and_validation() -> None:
    cfg = Config.model_validate({"version": 1})
    assert cfg.routing.prefer_fast is False

    cfg_on = Config.model_validate({"version": 1, "routing": {"prefer_fast": True}})
    assert cfg_on.routing.prefer_fast is True

    with pytest.raises(ValidationError):
        Config.model_validate({"version": 1, "routing": {"prefer_fast": "invalid"}})


def test_prefer_fast_off_preserves_config_order_when_scores_equal() -> None:
    # 5 ok runs each (min_samples=5), score = 6/7 for both. "slow" (20s) is first in config.
    runs = [
        Outcome("local", "slow", (), True, duration_s=20.0),
        Outcome("local", "slow", (), True, duration_s=20.0),
        Outcome("local", "slow", (), True, duration_s=20.0),
        Outcome("local", "slow", (), True, duration_s=20.0),
        Outcome("local", "slow", (), True, duration_s=20.0),
        Outcome("local", "fast", (), True, duration_s=2.0),
        Outcome("local", "fast", (), True, duration_s=2.0),
        Outcome("local", "fast", (), True, duration_s=2.0),
        Outcome("local", "fast", (), True, duration_s=2.0),
        Outcome("local", "fast", (), True, duration_s=2.0),
    ]
    cfg = _config(prefer_fast=False)
    order = _route_models(cfg, runs)
    # With prefer_fast=False, "slow" stays first because config order wins equal scores
    assert order == ["slow", "fast", "tier2"]


def test_prefer_fast_on_puts_faster_model_first_when_scores_equal() -> None:
    runs = [
        Outcome("local", "slow", (), True, duration_s=20.0),
        Outcome("local", "slow", (), True, duration_s=20.0),
        Outcome("local", "slow", (), True, duration_s=20.0),
        Outcome("local", "slow", (), True, duration_s=20.0),
        Outcome("local", "slow", (), True, duration_s=20.0),
        Outcome("local", "fast", (), True, duration_s=2.0),
        Outcome("local", "fast", (), True, duration_s=2.0),
        Outcome("local", "fast", (), True, duration_s=2.0),
        Outcome("local", "fast", (), True, duration_s=2.0),
        Outcome("local", "fast", (), True, duration_s=2.0),
    ]
    cfg = _config(prefer_fast=True)
    order = _route_models(cfg, runs)
    # With prefer_fast=True, "fast" (2.0s) comes before "slow" (20.0s)
    assert order == ["fast", "slow", "tier2"]


def test_prefer_fast_on_when_score_diff_under_0_05_faster_wins() -> None:
    # "slow": 10 ok out of 11 -> (10+1)/(11+2) = 11/13 ≈ 0.8462, duration 30s
    # "fast": 9 ok, 1 fail (total 10) -> (9+1)/(10+2) = 10/12 ≈ 0.8333, duration 3s
    # diff = 0.8462 - 0.8333 = 0.0129 < 0.05!
    # "fast": 9 ok, 1 fail (total 10) -> (9+1)/(10+2) = 10/12 ≈ 0.8333, duration 3s
    # diff = 0.8462 - 0.8333 = 0.0129 < 0.05!
    runs_slow = [Outcome("local", "slow", (), True, duration_s=30.0)] * 10 + [
        Outcome("local", "slow", (), False, duration_s=None)
    ]
    runs_fast = [Outcome("local", "fast", (), True, duration_s=3.0)] * 9 + [
        Outcome("local", "fast", (), False, duration_s=None)
    ]
    cfg = _config(prefer_fast=True)
    order = _route_models(cfg, runs_slow + runs_fast)
    assert order == ["fast", "slow", "tier2"]


def test_prefer_fast_on_when_score_diff_0_05_or_above_higher_score_wins() -> None:
    # "slow": 10 ok out of 10 -> (10+1)/(10+2) = 11/12 ≈ 0.9167, duration 40s
    # "fast": 7 ok, 3 fail out of 10 -> (7+1)/(10+2) = 8/12 ≈ 0.6667, duration 2s
    # diff = 0.9167 - 0.6667 = 0.25 >= 0.05! Higher score must win: speed never overrides success.
    runs_slow = [Outcome("local", "slow", (), True, duration_s=40.0)] * 10
    runs_fast = [Outcome("local", "fast", (), True, duration_s=2.0)] * 7 + [
        Outcome("local", "fast", (), False, duration_s=None)
    ] * 3
    cfg = _config(prefer_fast=True)
    order = _route_models(cfg, runs_slow + runs_fast)
    assert order == ["slow", "fast", "tier2"]


def test_prefer_fast_on_unknown_duration_goes_behind_known() -> None:
    # "slow" has known duration (15s) with 5 ok runs.
    # "fast" has 0 runs (unknown duration, neutral score 0.5).
    # "slow" has 5 ok, 5 fail -> (5+1)/(10+2) = 6/12 = 0.5 (same score as neutral!).
    runs_slow = [Outcome("local", "slow", (), True, duration_s=15.0)] * 5 + [
        Outcome("local", "slow", (), False, duration_s=None)
    ] * 5
    cfg = _config(prefer_fast=True)
    order = _route_models(cfg, runs_slow)
    # "slow" has known duration; "fast" has unknown duration -> "slow" comes first
    assert order == ["slow", "fast", "tier2"]


def test_prefer_fast_never_changes_tier_order() -> None:
    # "tier2" model is super fast (1s) and 100% score (10/10 ok).
    # "slow" is tier 1 with 20s and 50% score.
    runs = (
        [Outcome("local", "tier2", (), True, duration_s=1.0)] * 10
        + [Outcome("local", "slow", (), True, duration_s=20.0)] * 5
        + [Outcome("local", "slow", (), False, duration_s=None)] * 5
    )
    cfg = _config(prefer_fast=True)
    order = _route_models(cfg, runs)
    # Tier 1 candidates ("slow", "fast") must ALWAYS be before Tier 2 ("tier2")
    assert order[2] == "tier2"
    assert set(order[:2]) == {"slow", "fast"}
