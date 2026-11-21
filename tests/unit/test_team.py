"""Tests for team management service (Faz 11c-c, Mimari §19 & §22).

Covers patron selection, worker add/remove/toggle/reorder/tier/model, and consent,
ensuring all operations use ruamel round-trip, preserve comments, and validate inputs.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orkestra.chief import team
from orkestra.config import loader
from orkestra.config.schema import CliAgentProvider, OllamaProvider, OpenAICompatProvider
from orkestra.errors import ConfigError, UsageError
from orkestra.state import consent, db

NOW = datetime(2026, 11, 21, 14, 0, tzinfo=UTC)

SAMPLE_CONFIG = """\
# Header comment: project config
version: 1
language: en

defaults:
  chief: claude   # the lead agent

chiefs:
  claude:
    launch: ["claude"]
  agy:
    launch: ["agy"]
  codex:
    launch: ["codex"]

providers:
  local:
    type: ollama          # local server
    base_url: http://localhost:11434
    models:
      - id: qwen2.5-coder:7b
        tier: 1
  remote:
    type: openai_compat   # cloud API
    base_url: https://api.example.test/v1
    api_key_env: REMOTE_API_KEY
    models:
      - id: deepseek-chat
        tier: 2
  codex:
    type: cli_agent       # coding agent
    command: codex
    tier: 3
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "orkestra.yaml"
    path.write_bytes(SAMPLE_CONFIG.encode("utf-8"))
    return path


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "state.db")
    yield connection
    connection.close()


def test_team_summary_structure(config_file: Path, conn: sqlite3.Connection) -> None:
    cfg = loader.load_config(config_file).config
    summary = team.team_summary(cfg, conn)
    assert summary.patron == "claude"
    chief_names = [c.name for c in summary.chiefs]
    assert chief_names == ["claude", "agy", "codex"]
    claude_chief = next(c for c in summary.chiefs if c.name == "claude")
    assert claude_chief.is_default is True

    worker_names = [w.name for w in summary.workers]
    assert worker_names == ["local", "remote", "codex"]

    local_worker = next(w for w in summary.workers if w.name == "local")
    assert local_worker.type == "ollama"
    assert local_worker.local is True
    assert local_worker.tier == 1
    assert "qwen2.5-coder:7b" in local_worker.models
    assert local_worker.selected_model == "qwen2.5-coder:7b"

    remote_worker = next(w for w in summary.workers if w.name == "remote")
    assert remote_worker.type == "openai_compat"
    assert remote_worker.local is False
    assert remote_worker.tier == 2
    assert remote_worker.api_key_env == "REMOTE_API_KEY"
    assert remote_worker.consent_state == "missing"


def test_set_patron_updates_config_and_preserves_comments(config_file: Path) -> None:
    res = team.set_patron(config_file, "agy")
    assert res.config.defaults.chief == "agy"
    text = config_file.read_text(encoding="utf-8")
    assert "chief: agy" in text
    assert "# the lead agent" in text
    assert "# Header comment: project config" in text


def test_set_patron_rejects_unknown_chief(config_file: Path) -> None:
    with pytest.raises((UsageError, ConfigError)):
        team.set_patron(config_file, "non_existent_chief")


def test_toggle_worker_preserves_comments(config_file: Path) -> None:
    res = team.toggle_worker(config_file, "local", enabled=False)
    assert res.config.providers["local"].enabled is False
    text = config_file.read_text(encoding="utf-8")
    assert "enabled: false" in text
    assert "# local server" in text


def test_set_worker_tier(config_file: Path) -> None:
    res = team.set_worker_tier(config_file, "remote", tier=3)
    p = res.config.providers["remote"]
    assert isinstance(p, OpenAICompatProvider)
    assert p.models[0].tier == 3
    text = config_file.read_text(encoding="utf-8")
    assert "# cloud API" in text


def test_set_worker_tier_rejects_invalid_tier(config_file: Path) -> None:
    with pytest.raises(UsageError):
        team.set_worker_tier(config_file, "remote", tier=5)


def test_set_worker_model(config_file: Path) -> None:
    res = team.set_worker_model(config_file, "local", "llama3:latest")
    p = res.config.providers["local"]
    assert isinstance(p, OllamaProvider)
    assert p.models[0].id == "llama3:latest"
    text = config_file.read_text(encoding="utf-8")
    assert "# local server" in text


def test_reorder_workers_preserves_comments(config_file: Path) -> None:
    res = team.reorder_workers(config_file, ["codex", "remote", "local"])
    assert list(res.config.providers.keys()) == ["codex", "remote", "local"]
    text = config_file.read_text(encoding="utf-8")
    assert "# coding agent" in text
    assert "# cloud API" in text
    assert "# local server" in text
    # Verify order in text: codex comes before remote and local
    codex_pos = text.find("codex:")
    remote_pos = text.find("remote:")
    local_pos = text.find("local:")
    assert codex_pos < remote_pos < local_pos


def test_add_worker_openai_compat(config_file: Path) -> None:
    res = team.add_worker(
        config_file,
        name="openrouter",
        provider_type="openai_compat",
        model="anthropic/claude-3.5-sonnet",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        tier=2,
    )
    assert "openrouter" in res.config.providers
    p = res.config.providers["openrouter"]
    assert p.type == "openai_compat"
    assert p.base_url == "https://openrouter.ai/api/v1"
    assert p.api_key_env == "OPENROUTER_API_KEY"
    assert p.models[0].id == "anthropic/claude-3.5-sonnet"
    assert "# Header comment: project config" in config_file.read_text(encoding="utf-8")


def test_add_worker_ollama(config_file: Path) -> None:
    res = team.add_worker(
        config_file,
        name="my-ollama",
        provider_type="ollama",
        model="deepseek-r1:8b",
        base_url="http://localhost:11434",
        tier=1,
    )
    assert "my-ollama" in res.config.providers
    p = res.config.providers["my-ollama"]
    assert p.type == "ollama"
    assert p.local is True
    assert p.models[0].id == "deepseek-r1:8b"


def test_add_worker_cli_agent(config_file: Path) -> None:
    res = team.add_worker(
        config_file,
        name="my-agy",
        provider_type="cli_agent",
        command="agy",
        tier=3,
        model="gemini-2.0-flash",
    )
    assert "my-agy" in res.config.providers
    p = res.config.providers["my-agy"]
    assert isinstance(p, CliAgentProvider)
    assert p.type == "cli_agent"
    assert p.command == "agy"
    assert p.model == "gemini-2.0-flash"


def test_add_worker_rejects_invalid_name_or_duplicate(config_file: Path) -> None:
    with pytest.raises(UsageError):
        team.add_worker(
            config_file,
            name="Invalid Name With Spaces!",
            provider_type="ollama",
            model="m",
        )
    with pytest.raises(UsageError):
        team.add_worker(
            config_file,
            name="local",  # already exists
            provider_type="ollama",
            model="m",
        )


def test_add_worker_rejects_raw_key_in_key_env(config_file: Path) -> None:
    with pytest.raises(UsageError):
        team.add_worker(
            config_file,
            name="new-provider",
            provider_type="openai_compat",
            model="m",
            base_url="https://api.example.test",
            api_key_env="sk-1234567890abcdef1234567890abcdef",  # Looks like an API key!
        )


def test_remove_worker_and_revoke_consent(config_file: Path, conn: sqlite3.Connection) -> None:
    # First grant consent to remote
    cfg = loader.load_config(config_file).config
    consent.grant(conn, "remote", cfg.providers["remote"], NOW)
    assert consent.state(conn, "remote", cfg.providers["remote"]) == "granted"

    outcome = team.remove_worker(config_file, "remote", conn=conn)
    assert "remote" not in outcome.saved.config.providers
    assert outcome.consent_revoked is True
    # Comments of other providers preserved
    text = config_file.read_text(encoding="utf-8")
    assert "# local server" in text
    assert "# coding agent" in text


def test_grant_consent(config_file: Path, conn: sqlite3.Connection) -> None:
    cfg = loader.load_config(config_file).config
    assert consent.state(conn, "remote", cfg.providers["remote"]) == "missing"
    team.grant_consent(conn, cfg, "remote", NOW)
    assert consent.state(conn, "remote", cfg.providers["remote"]) == "granted"
