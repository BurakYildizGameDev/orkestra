from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from ruamel.yaml import YAML

from orkestra import i18n
from orkestra.config.loader import format_validation_error
from orkestra.config.schema import CliAgentProvider, Config, OpenAICompatProvider

REPO_ROOT = Path(__file__).resolve().parents[2]


def _errors(data: dict[str, Any]) -> list[str]:
    with pytest.raises(ValidationError) as exc_info:
        Config.model_validate(data)
    return format_validation_error(exc_info.value)


def _openrouter(**model: Any) -> dict[str, Any]:
    return {
        "type": "openai_compat",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "models": [{"id": "provider/model", "tier": 2, **model}],
    }


# --- valid configs ---------------------------------------------------------------------


def test_minimal_config_defaults() -> None:
    cfg = Config.model_validate({"version": 1})
    assert cfg.providers == {}
    assert cfg.language == "auto"
    assert cfg.defaults.profile == "balanced"
    assert set(cfg.profiles) == {"cheap", "balanced", "quality"}
    assert (cfg.profiles["cheap"].min_tier, cfg.profiles["cheap"].max_tier) == (1, 1)
    assert (cfg.profiles["balanced"].min_tier, cfg.profiles["balanced"].max_tier) == (1, 3)
    assert (cfg.profiles["quality"].min_tier, cfg.profiles["quality"].max_tier) == (2, 3)
    assert set(cfg.chiefs) == {"claude", "agy", "codex"}
    assert cfg.map.privacy == "local_only"
    assert cfg.security.block_secrets_to_remote is True


def test_defaults_are_not_shared_between_instances() -> None:
    a = Config.model_validate({"version": 1})
    b = Config.model_validate({"version": 1})
    a.profiles["cheap"].max_tier = 3
    a.defaults.timeout_s = 1
    assert b.profiles["cheap"].max_tier == 1
    assert b.defaults.timeout_s == 300


def test_packaged_example_is_valid() -> None:
    text = resources.files("orkestra.config").joinpath("example.yaml").read_text(encoding="utf-8")
    cfg = Config.model_validate(YAML(typ="safe").load(text))
    assert {"ollama", "openrouter", "codex", "agy"} <= set(cfg.providers)
    agy = cfg.providers["agy"]
    assert isinstance(agy, CliAgentProvider)
    assert agy.experimental is True
    assert agy.enabled is False  # experimental agent is off by default


def test_examples_copy_matches_packaged_example() -> None:
    packaged = (
        resources.files("orkestra.config").joinpath("example.yaml").read_text(encoding="utf-8")
    )
    copy = (REPO_ROOT / "examples" / "orkestra.example.yaml").read_text(encoding="utf-8")
    assert copy == packaged


def test_discriminated_union_picks_provider_class() -> None:
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "local": {"type": "ollama", "models": [{"id": "m", "tier": 1}]},
                "router": _openrouter(),
                "codex": {"type": "cli_agent", "command": "codex"},
            },
        }
    )
    assert type(cfg.providers["local"]).__name__ == "OllamaProvider"
    assert cfg.providers["local"].local is True
    assert type(cfg.providers["router"]).__name__ == "OpenAICompatProvider"
    assert cfg.providers["router"].local is False
    assert isinstance(cfg.providers["codex"], CliAgentProvider)
    assert cfg.providers["codex"].sandbox == "workspace-write"


def test_api_key_env_is_optional() -> None:
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "lmstudio": {
                    "type": "openai_compat",
                    "base_url": "http://localhost:1234/v1",
                    "models": [{"id": "m", "tier": 1}],
                }
            },
        }
    )
    provider = cfg.providers["lmstudio"]
    assert isinstance(provider, OpenAICompatProvider)
    assert provider.api_key_env is None


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("codex", "codex"),
        ("agy", "agy"),
        ("codex.cmd", "codex"),
        ("C:\\tools\\codex.exe", "codex"),
        ("/usr/local/bin/agy", "agy"),
        ("my-agent", "generic"),
    ],
)
def test_cli_agent_kind_inferred_from_command(command: str, expected: str) -> None:
    provider = CliAgentProvider.model_validate({"type": "cli_agent", "command": command})
    assert provider.kind == expected


def test_cli_agent_explicit_kind_kept() -> None:
    provider = CliAgentProvider.model_validate(
        {"type": "cli_agent", "command": "wrapper.sh", "kind": "codex"}
    )
    assert provider.kind == "codex"


def test_user_profiles_merge_with_builtin() -> None:
    cfg = Config.model_validate(
        {
            "version": 1,
            "profiles": {"fast": {"min_tier": 1, "max_tier": 2}, "cheap": {"max_tier": 2}},
        }
    )
    assert set(cfg.profiles) == {"cheap", "balanced", "quality", "fast"}
    assert cfg.profiles["cheap"].max_tier == 2


def test_user_chiefs_merge_with_builtin() -> None:
    cfg = Config.model_validate({"version": 1, "chiefs": {"gemini": {"launch": ["gemini"]}}})
    assert {"claude", "agy", "codex", "gemini"} <= set(cfg.chiefs)
    assert cfg.chiefs["gemini"].prompt_mode == "file"


def test_null_estimate_threshold_allowed() -> None:
    cfg = Config.model_validate({"version": 1, "estimate": {"confirm_above_usd": None}})
    assert cfg.estimate.confirm_above_usd is None


# --- invalid configs and readable messages ---------------------------------------------


def test_invalid_tier_message_en() -> None:
    errors = _errors({"version": 1, "providers": {"openrouter": _openrouter(tier=5)}})
    assert errors == ["providers.openrouter.models[0].tier: must be 1, 2 or 3"]


def test_invalid_tier_message_tr() -> None:
    i18n.set_language("tr")
    errors = _errors({"version": 1, "providers": {"openrouter": _openrouter(tier=5)}})
    assert errors == ["providers.openrouter.models[0].tier: 1, 2 veya 3 olmalı"]


def test_unknown_provider_type() -> None:
    errors = _errors({"version": 1, "providers": {"x": {"type": "gemini_web"}}})
    assert len(errors) == 1
    assert errors[0].startswith("providers.x: unknown provider type 'gemini_web'")
    assert "ollama, openai_compat, cli_agent" in errors[0]


def test_missing_provider_type() -> None:
    errors = _errors({"version": 1, "providers": {"x": {"command": "codex"}}})
    assert errors[0].startswith("providers.x: 'type' is required")


def test_danger_full_access_rejected() -> None:
    errors = _errors(
        {
            "version": 1,
            "providers": {
                "codex": {"type": "cli_agent", "command": "codex", "sandbox": "danger-full-access"}
            },
        }
    )
    assert len(errors) == 1
    assert errors[0].startswith("providers.codex.sandbox: 'danger-full-access' is not supported")


def test_unknown_sandbox_rejected() -> None:
    errors = _errors(
        {"version": 1, "providers": {"c": {"type": "cli_agent", "command": "c", "sandbox": "x"}}}
    )
    assert errors == ["providers.c.sandbox: must be 'read-only' or 'workspace-write'"]


@pytest.mark.parametrize("name", ["My Provider", "UPPER", "a.b", "ç"])
def test_invalid_provider_name(name: str) -> None:
    errors = _errors({"version": 1, "providers": {name: {"type": "cli_agent", "command": "codex"}}})
    assert any(f"invalid provider name '{name}'" in e for e in errors), errors


def test_unknown_field_is_reported() -> None:
    errors = _errors({"version": 1, "defaults": {"profil": "cheap"}})
    assert errors == ["defaults.profil: unknown field"]


def test_missing_version() -> None:
    assert _errors({}) == ["version: required field is missing"]


def test_wrong_version() -> None:
    assert _errors({"version": 2}) == ["version: must be 1"]


def test_unknown_default_profile() -> None:
    errors = _errors({"version": 1, "defaults": {"profile": "turbo"}})
    assert errors == ["defaults.profile: profile 'turbo' is not defined in profiles"]


def test_unknown_queue_profile() -> None:
    errors = _errors({"version": 1, "queue": {"default_profile": "turbo"}})
    assert errors == ["queue.default_profile: profile 'turbo' is not defined in profiles"]


def test_unknown_default_chief() -> None:
    errors = _errors({"version": 1, "defaults": {"chief": "gpt"}})
    assert errors == ["defaults.chief: chief 'gpt' is not defined in chiefs"]


def test_min_tier_above_max_tier() -> None:
    errors = _errors({"version": 1, "profiles": {"odd": {"min_tier": 3, "max_tier": 1}}})
    assert errors == ["profiles.odd: min_tier (3) must not be greater than max_tier (1)"]


def test_negative_budget() -> None:
    errors = _errors(
        {
            "version": 1,
            "providers": {
                "c": {"type": "cli_agent", "command": "codex", "budget": {"daily_usd": -1}}
            },
        }
    )
    assert errors == ["providers.c.budget.daily_usd: must be at least 0"]


def test_wrong_types_are_reported() -> None:
    errors = _errors(
        {
            "version": 1,
            "language": "jp",
            "defaults": {"timeout_s": "soon"},
            "providers": {"c": {"type": "cli_agent", "command": "codex", "concurrency": 0}},
        }
    )
    assert "language: must be 'auto', 'en', 'tr', 'de', 'es' or 'fr'" in errors
    assert "defaults.timeout_s: must be an integer" in errors
    assert "providers.c.concurrency: must be at least 1" in errors
