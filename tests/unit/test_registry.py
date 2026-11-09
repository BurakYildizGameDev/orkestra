from __future__ import annotations

from typing import Any

import pytest

from orkestra.config.schema import Config
from orkestra.errors import ConfigError, NoProviderAvailable, UsageError
from orkestra.providers.ollama import OllamaChat
from orkestra.providers.openai_compat import OpenAICompatChat
from orkestra.providers.registry import select_chat_target


def _config(**providers: Any) -> Config:
    return Config.model_validate({"version": 1, "providers": providers})


OLLAMA = {
    "type": "ollama",
    "models": [{"id": "small", "tier": 1}, {"id": "big", "tier": 2}],
}
ROUTER = {
    "type": "openai_compat",
    "base_url": "https://router.test/v1",
    "api_key_env": "ROUTER_KEY",
    "models": [{"id": "r1", "tier": 1}, {"id": "r2", "tier": 2}],
}
CODEX = {"type": "cli_agent", "command": "codex"}
ENV = {"ROUTER_KEY": "k"}


def test_first_tier1_model_in_config_order() -> None:
    target = select_chat_target(_config(ollama=OLLAMA, router=ROUTER), environ=ENV)
    assert (target.name, target.model.id) == ("ollama", "small")
    assert isinstance(target.provider, OllamaChat)


def test_tier_option() -> None:
    target = select_chat_target(_config(ollama=OLLAMA, router=ROUTER), tier=2, environ=ENV)
    assert (target.name, target.model.id) == ("ollama", "big")


def test_priority_within_tier() -> None:
    ollama = {
        "type": "ollama",
        "models": [{"id": "a", "tier": 1}, {"id": "b", "tier": 1, "priority": 5}],
    }
    assert select_chat_target(_config(ollama=ollama), environ={}).model.id == "b"


def test_forced_provider() -> None:
    target = select_chat_target(
        _config(ollama=OLLAMA, router=ROUTER), provider="router", environ=ENV
    )
    assert (target.name, target.model.id) == ("router", "r1")
    assert isinstance(target.provider, OpenAICompatChat)


def test_forced_provider_without_tier1_uses_its_lowest_tier() -> None:
    router = {**ROUTER, "models": [{"id": "r3", "tier": 3}, {"id": "r2", "tier": 2}]}
    target = select_chat_target(_config(router=router), provider="router", environ=ENV)
    assert target.model.id == "r2"


def test_model_finds_its_provider() -> None:
    target = select_chat_target(_config(ollama=OLLAMA, router=ROUTER), model="r2", environ=ENV)
    assert (target.name, target.model.id) == ("router", "r2")


def test_forced_provider_with_unlisted_model() -> None:
    target = select_chat_target(
        _config(ollama=OLLAMA), provider="ollama", model="llama3", environ={}
    )
    assert target.model.id == "llama3"
    assert target.model.tier == 1


def test_disabled_and_agent_skipped() -> None:
    cfg = _config(codex=CODEX, ollama={**OLLAMA, "enabled": False}, router=ROUTER)
    assert select_chat_target(cfg, environ=ENV).name == "router"


def test_missing_key_skipped() -> None:
    cfg = _config(router=ROUTER, ollama=OLLAMA)
    assert select_chat_target(cfg, environ={}).name == "ollama"


def test_no_providers_is_config_error() -> None:
    with pytest.raises(ConfigError) as exc_info:
        select_chat_target(_config(), environ={})
    assert "orkestra init" in exc_info.value.message


def test_unknown_provider_is_usage_error() -> None:
    with pytest.raises(UsageError):
        select_chat_target(_config(ollama=OLLAMA), provider="nope", environ={})


def test_nothing_suitable_lists_reasons() -> None:
    cfg = _config(codex=CODEX, router=ROUTER, ollama={**OLLAMA, "enabled": False})
    with pytest.raises(NoProviderAvailable) as exc_info:
        select_chat_target(cfg, environ={})
    assert exc_info.value.exit_code == 3
    details = " | ".join(exc_info.value.details)
    assert "codex" in details
    assert "ROUTER_KEY" in details
    assert "ollama: disabled" in details


def test_forced_agent_is_not_suitable() -> None:
    with pytest.raises(NoProviderAvailable):
        select_chat_target(_config(codex=CODEX), provider="codex", environ={})


def test_no_model_on_tier() -> None:
    with pytest.raises(NoProviderAvailable) as exc_info:
        select_chat_target(_config(ollama=OLLAMA), tier=3, environ={})
    assert "tier 3" in exc_info.value.details[0]
