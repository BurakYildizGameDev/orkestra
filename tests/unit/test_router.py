from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from orkestra.config.schema import Config
from orkestra.errors import ConfigError, ConsentRequired, NoProviderAvailable, UsageError
from orkestra.providers.pricing import Price
from orkestra.routing.router import ProviderState, Snapshot, TaskNeeds, route
from orkestra.state.budget import Amount

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone(timedelta(hours=3)))

BASE_PROVIDERS: dict[str, Any] = {
    "local": {
        "type": "ollama",
        "models": [
            {"id": "small", "tier": 1, "context_window": 4096},
            {"id": "big", "tier": 1, "context_window": 32768},
            {"id": "mid", "tier": 2, "context_window": 16384},
        ],
    },
    "router": {
        "type": "openai_compat",
        "base_url": "https://router.test/v1",
        "api_key_env": "ROUTER_KEY",
        "models": [
            {"id": "r1", "tier": 1, "context_window": 128000},
            {"id": "r2", "tier": 2, "context_window": 128000},
        ],
        "budget": {"daily_usd": 1.0, "daily_requests": 100},
    },
    "codex": {"type": "cli_agent", "command": "codex"},
}


def _config(providers: dict[str, Any] | None = None, **extra: Any) -> Config:
    return Config.model_validate({"version": 1, "providers": providers or BASE_PROVIDERS, **extra})


def _granted(**overrides: ProviderState) -> dict[str, ProviderState]:
    states = {name: ProviderState(consent="granted") for name in BASE_PROVIDERS}
    states.update(overrides)
    return states


@dataclass
class Case:
    name: str
    needs: TaskNeeds = field(default_factory=TaskNeeds)
    states: dict[str, ProviderState] = field(default_factory=_granted)
    expected: list[str] = field(default_factory=list)  # provider/model in order
    eliminated: dict[str, str] = field(default_factory=dict)  # label -> code
    profile: str | None = None
    providers: dict[str, Any] | None = None
    prices: dict[tuple[str, str], Price | None] = field(default_factory=dict)


CASES = [
    Case(
        "default: tier ascending, then config order, agent left out",
        expected=["local/small", "local/big", "router/r1", "local/mid", "router/r2"],
        eliminated={"codex": "agent_not_supported"},
    ),
    Case(
        "task tier raises the lower bound",
        needs=TaskNeeds(tier=2),
        expected=["local/mid", "router/r2"],
        eliminated={
            "local/small": "tier_out_of_range",
            "local/big": "tier_out_of_range",
            "router/r1": "tier_out_of_range",
        },
    ),
    Case(
        "profile cheap: only tier 1",
        profile="cheap",
        expected=["local/small", "local/big", "router/r1"],
        eliminated={"local/mid": "tier_out_of_range", "router/r2": "tier_out_of_range"},
    ),
    Case(
        "profile quality: tiers 2-3 even if the task says 1",
        profile="quality",
        expected=["local/mid", "router/r2"],
    ),
    Case(
        "local_only keeps only local providers",
        needs=TaskNeeds(privacy="local_only"),
        expected=["local/small", "local/big", "local/mid"],
        eliminated={"router": "not_local"},
    ),
    Case(
        "secrets in context: remote left out",
        needs=TaskNeeds(has_secrets=True),
        expected=["local/small", "local/big", "local/mid"],
        eliminated={"router": "secrets_remote"},
    ),
    Case(
        "secrets with --allow-secrets: remote allowed",
        needs=TaskNeeds(has_secrets=True, allow_secrets=True),
        expected=["local/small", "local/big", "router/r1", "local/mid", "router/r2"],
    ),
    Case(
        "context too big for small windows (80% rule)",
        needs=TaskNeeds(prompt_chars=int(3.5 * 10000)),  # ~10000 tokens
        expected=["local/big", "router/r1", "local/mid", "router/r2"],
        eliminated={"local/small": "context_too_small"},
    ),
    Case(
        "no consent",
        states=_granted(router=ProviderState(consent="missing")),
        expected=["local/small", "local/big", "local/mid"],
        eliminated={"router": "consent_missing"},
    ),
    Case(
        "consent for changed settings",
        states=_granted(router=ProviderState(consent="changed")),
        expected=["local/small", "local/big", "local/mid"],
        eliminated={"router": "consent_changed"},
    ),
    Case(
        "circuit open",
        states=_granted(
            router=ProviderState(consent="granted", open_until=NOW + timedelta(minutes=3))
        ),
        expected=["local/small", "local/big", "local/mid"],
        eliminated={"router": "circuit_open"},
    ),
    Case(
        "circuit expired is closed again",
        states=_granted(
            router=ProviderState(consent="granted", open_until=NOW - timedelta(seconds=1))
        ),
        expected=["local/small", "local/big", "router/r1", "local/mid", "router/r2"],
    ),
    Case(
        "API key missing",
        states=_granted(router=ProviderState(consent="granted", key_present=False)),
        expected=["local/small", "local/big", "local/mid"],
        eliminated={"router": "key_missing"},
    ),
    Case(
        "budget exhausted (requests)",
        states=_granted(router=ProviderState(consent="granted", used=Amount(requests=100))),
        expected=["local/small", "local/big", "local/mid"],
        eliminated={"router/r1": "budget", "router/r2": "budget"},
    ),
    Case(
        "budget: price makes the estimate exceed daily_usd",
        prices={("router", "r2"): Price(100.0, 300.0, "provider")},  # 4096 out ≈ $1.23
        expected=["local/small", "local/big", "router/r1", "local/mid"],
        eliminated={"router/r2": "budget"},
    ),
    Case(
        "budget only filters: config order wins even with less budget left",
        providers={
            "a": {
                "type": "ollama",
                "models": [{"id": "m", "tier": 1}],
                "budget": {"daily_requests": 10},
            },
            "b": {
                "type": "ollama",
                "models": [{"id": "m", "tier": 1}],
                "budget": {"daily_requests": 10},
            },
        },
        states={
            "a": ProviderState(consent="granted", used=Amount(requests=8)),
            "b": ProviderState(consent="granted", used=Amount(requests=1)),
        },
        expected=["a/m", "b/m"],
    ),
    Case(
        "priority beats config order within a tier",
        providers={
            "a": {"type": "ollama", "models": [{"id": "m", "tier": 1}]},
            "b": {"type": "ollama", "models": [{"id": "m", "tier": 1, "priority": 5}]},
        },
        states={"a": ProviderState(consent="granted"), "b": ProviderState(consent="granted")},
        expected=["b/m", "a/m"],
    ),
    Case(
        "config order: providers as written, then models as listed (not by name)",
        providers={
            "zeta": {"type": "ollama", "models": [{"id": "b", "tier": 1}, {"id": "a", "tier": 1}]},
            "alpha": {"type": "ollama", "models": [{"id": "z", "tier": 1}]},
        },
        states={
            "zeta": ProviderState(consent="granted"),
            "alpha": ProviderState(consent="granted"),
        },
        expected=["zeta/b", "zeta/a", "alpha/z"],
    ),
    Case(
        "forced provider: only its models",
        needs=TaskNeeds(provider="router"),
        expected=["router/r1", "router/r2"],
    ),
    Case(
        "forced model: found on its provider",
        needs=TaskNeeds(model="mid"),
        expected=["local/mid"],
        eliminated={"router/mid": "no_such_model", "codex": "agent_not_supported"},
    ),
    Case(
        "forced provider + unlisted model is trusted",
        needs=TaskNeeds(provider="local", model="llama3"),
        expected=["local/llama3"],
    ),
    Case(
        "disabled provider",
        providers={
            "off": {"type": "ollama", "enabled": False, "models": [{"id": "m", "tier": 1}]},
            "on": {"type": "ollama", "models": [{"id": "m", "tier": 1}]},
        },
        states={"off": ProviderState(consent="granted"), "on": ProviderState(consent="granted")},
        expected=["on/m"],
        eliminated={"off": "disabled"},
    ),
    Case(
        "experimental needs an explicit enabled: true",
        providers={
            "exp": {"type": "ollama", "experimental": True, "models": [{"id": "m", "tier": 1}]},
            "exp_on": {
                "type": "ollama",
                "experimental": True,
                "enabled": True,
                "models": [{"id": "m", "tier": 1}],
            },
        },
        states={
            "exp": ProviderState(consent="granted"),
            "exp_on": ProviderState(consent="granted"),
        },
        expected=["exp_on/m"],
        eliminated={"exp": "experimental"},
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_route_table(case: Case) -> None:
    result = route(
        case.needs,
        _config(case.providers),
        Snapshot(NOW, case.states, case.prices),
        profile=case.profile,
    )
    assert [c.label for c in result.candidates] == case.expected
    got = {e.label: e.code for e in result.eliminated}
    for label, code in case.eliminated.items():
        assert got.get(label) == code, (label, got)
    assert all(e.reason for e in result.eliminated)  # every elimination has a readable reason


def test_every_reason_names_the_provider() -> None:
    states = _granted(router=ProviderState(consent="missing"))
    result = route(TaskNeeds(), _config(), Snapshot(NOW, states))
    for e in result.eliminated:
        assert e.provider in e.reason


def test_forced_provider_that_is_unusable_is_an_explicit_error() -> None:
    states = _granted(router=ProviderState(consent="granted", key_present=False))
    result = route(TaskNeeds(provider="router"), _config(), Snapshot(NOW, states))
    assert result.candidates == ()
    error = result.error()
    assert isinstance(error, NoProviderAvailable)
    assert error.exit_code == 3
    assert any("ROUTER_KEY" in d for d in error.details)  # no silent switch to another provider


def test_missing_consent_error_is_exit_4() -> None:
    states = {name: ProviderState(consent="missing") for name in BASE_PROVIDERS}
    error = route(TaskNeeds(), _config(), Snapshot(NOW, states)).error()
    assert isinstance(error, ConsentRequired)
    assert error.exit_code == 4


def test_tier_out_of_range_reason_is_readable() -> None:
    result = route(TaskNeeds(), _config(), Snapshot(NOW, _granted()), profile="cheap")
    reason = next(e.reason for e in result.eliminated if e.code == "tier_out_of_range")
    assert reason == "local/mid: tier 2 is outside 1-1 (profile cheap)"


def test_unknown_profile() -> None:
    with pytest.raises(UsageError):
        route(TaskNeeds(), _config(), Snapshot(NOW, _granted()), profile="turbo")


def test_profile_default_from_config() -> None:
    cfg = _config(defaults={"profile": "cheap"})
    result = route(TaskNeeds(), cfg, Snapshot(NOW, _granted()))
    assert result.profile == "cheap"
    assert result.tier_range == (1, 1)


def test_unknown_forced_provider() -> None:
    with pytest.raises(UsageError):
        route(TaskNeeds(provider="nope"), _config(), Snapshot(NOW, _granted()))


def test_no_providers() -> None:
    with pytest.raises(ConfigError):
        route(TaskNeeds(), Config.model_validate({"version": 1}), Snapshot(NOW))


def test_route_is_pure() -> None:
    snapshot = Snapshot(NOW, _granted())
    first = route(TaskNeeds(), _config(), snapshot)
    second = route(TaskNeeds(), _config(), snapshot)
    assert first == second


def test_project_provider_comes_after_global_ones() -> None:
    """Merged configs keep the global order; providers new in the project file come last."""
    from orkestra.config.loader import merge_dicts

    merged = merge_dicts(
        {"version": 1, "providers": {"g": {"type": "ollama", "models": [{"id": "m", "tier": 1}]}}},
        {"providers": {"p": {"type": "ollama", "models": [{"id": "m", "tier": 1}]}}},
    )
    cfg = Config.model_validate(merged)
    states = {"g": ProviderState(consent="granted"), "p": ProviderState(consent="granted")}
    result = route(TaskNeeds(), cfg, Snapshot(NOW, states))
    assert [c.label for c in result.candidates] == ["g/m", "p/m"]


# --- code review fixes (Faz 4, PR #5) ---------------------------------------------------


def test_explicit_model_is_not_dropped_by_the_profile() -> None:
    result = route(
        TaskNeeds(provider="router", model="r2"), _config(), Snapshot(NOW, _granted()),
        profile="cheap",
    )  # fmt: skip
    assert [c.label for c in result.candidates] == ["router/r2"]


def test_task_tier_above_default_profile_narrows_to_that_tier() -> None:
    cfg = _config(defaults={"profile": "cheap"})
    result = route(TaskNeeds(tier=2), cfg, Snapshot(NOW, _granted()))
    assert result.tier_range == (2, 2)
    assert [c.label for c in result.candidates] == ["local/mid", "router/r2"]


def test_task_tier_above_explicit_profile_is_a_usage_error() -> None:
    with pytest.raises(UsageError) as exc_info:
        route(TaskNeeds(tier=2), _config(), Snapshot(NOW, _granted()), profile="cheap")
    assert "cheap" in exc_info.value.message


def test_unlisted_explicit_model_uses_its_snapshot_price() -> None:
    price = Price(1000.0, 1000.0, "provider")  # absurdly expensive: over daily_usd 1.0
    result = route(
        TaskNeeds(provider="router", model="other/model", prompt_chars=10),
        _config(), Snapshot(NOW, _granted(), {("router", "other/model"): price}),
    )  # fmt: skip
    assert result.candidates == ()
    assert result.eliminated[-1].code == "budget"


def test_snapshot_only_reads_the_providers_it_needs(tmp_path: Any) -> None:
    from contextlib import closing

    from orkestra.routing.router import take_snapshot
    from orkestra.state import db

    with closing(db.connect(tmp_path / "s.db")) as conn:
        snap = take_snapshot(conn, _config(), NOW, environ={}, names=["local"])
    assert set(snap.providers) == {"local"}
    assert ("router", "r1") not in snap.prices
