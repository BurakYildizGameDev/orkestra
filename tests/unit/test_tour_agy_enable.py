"""Usage tour 2026-11-23: agy was confirmed in the wizard and listed as enabled, yet the
router dropped it as "experimental, write enabled: true" (D-144)."""

from __future__ import annotations

from datetime import datetime

from orkestra.config.schema import Config
from orkestra.routing.router import ProviderState, Snapshot, TaskNeeds, route
from orkestra.tui import wizard


def _config(agy: dict[str, object]) -> Config:
    return Config.model_validate({"version": 1, "providers": {"agy": agy}})


def test_agy_confirmed_in_the_wizard_is_written_as_enabled() -> None:
    settings = wizard.agent_settings("agy", daily_runs=100, enabled=True)
    assert settings["enabled"] is True
    snapshot = Snapshot(datetime.now().astimezone(), {"agy": ProviderState(consent="granted")})
    result = route(TaskNeeds(kind="edit"), _config(settings), snapshot)
    assert [c.provider for c in result.candidates] == ["agy"]


def test_agy_declined_in_the_wizard_stays_off() -> None:
    assert wizard.agent_settings("agy", daily_runs=100, enabled=False)["enabled"] is False


def test_codex_needs_no_explicit_enabled() -> None:
    assert "enabled" not in wizard.agent_settings("codex", daily_runs=20)


def test_an_unacknowledged_experimental_provider_is_listed_as_off() -> None:
    from orkestra.providers import registry

    config = _config({"type": "cli_agent", "command": "agy", "experimental": True})
    assert registry.usable(config.providers["agy"]) is False
    config = _config({"type": "cli_agent", "command": "agy", "experimental": True, "enabled": True})
    assert registry.usable(config.providers["agy"]) is True
