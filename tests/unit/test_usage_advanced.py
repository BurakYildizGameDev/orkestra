"""Tests for Usage and Advanced views services and endpoints (Faz 11c-e, Mimari §19).

Verifies usage statistics, daily grouping, advanced configuration inspection,
API endpoints security, and window fallback behavior.
"""

from __future__ import annotations

import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from orkestra.chief import advanced, usage
from orkestra.config import loader
from orkestra.state import db
from orkestra.web.server import ServerConfig, create_server
from tests.unit.test_web_server import simulate_request

NOW = datetime(2026, 11, 21, 14, 0, tzinfo=UTC)

SAMPLE_CONFIG = """\
version: 1
language: en
defaults:
  chief: claude
  profile: balanced
profiles:
  balanced:
    min_tier: 1
    max_tier: 2
  fast:
    min_tier: 1
    max_tier: 1
providers:
  local:
    type: ollama
    base_url: http://localhost:11434
    models:
      - id: qwen2.5:7b
        tier: 1
  remote:
    type: openai_compat
    base_url: https://api.test/v1
    api_key_env: REMOTE_KEY
    budget:
      daily_usd: 5.0
    models:
      - id: gpt-4o-mini
        tier: 2
"""


@pytest.fixture
def test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "state.db"
    monkeypatch.setattr("orkestra.paths.state_db_path", lambda: db_file)
    with closing(db.connect(db_file)):
        pass
    return db_file


def test_usage_summary_empty(test_db: Path) -> None:
    with closing(db.connect(test_db)) as conn:
        data = usage.usage_summary(conn, days=7, now=NOW)
    assert data["totals"]["runs"] == 0
    assert data["totals"]["cost_usd"] == 0.0
    assert data["daily"] == []
    assert data["providers"] == []
    assert data["savings"]["worker_output_tokens"] == 0


def test_usage_summary_with_runs(test_db: Path) -> None:
    with closing(db.connect(test_db)) as conn:
        # Insert completed run from yesterday
        yesterday = NOW - timedelta(days=1)
        db.record_run_start(
            conn, run_id="run-1", task_id="task-1", kind="edit", started_at=yesterday
        )
        db.record_run_end(
            conn,
            "run-1",
            finished_at=yesterday + timedelta(seconds=10),
            status="ok",
            provider="remote",
            worker_output_tokens=500,
            envelope_chars=200,
        )
        conn.execute(
            "INSERT INTO usage (run_id, provider, model, day, prompt_tokens, "
            "completion_tokens, cost_usd, kind, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'actual', ?)",
            (
                "run-1",
                "remote",
                "m",
                yesterday.date().isoformat(),
                100,
                200,
                0.015,
                yesterday.isoformat(),
            ),
        )
        # Insert failed run from today
        db.record_run_start(conn, run_id="run-2", task_id="task-2", kind="edit", started_at=NOW)
        db.record_run_end(
            conn,
            "run-2",
            finished_at=NOW + timedelta(seconds=5),
            status="failed",
            provider="local",
            worker_output_tokens=100,
        )

        data = usage.usage_summary(conn, days=7, now=NOW)

    assert data["totals"]["runs"] == 2
    assert data["totals"]["ok"] == 1
    assert data["totals"]["cost_usd"] == 0.015
    assert len(data["daily"]) == 2
    assert data["savings"]["worker_output_tokens"] == 500


def test_advanced_summary(test_db: Path) -> None:
    parsed = loader.read_yaml_text(Path("orkestra.yaml"), SAMPLE_CONFIG)
    cfg = loader.Config.model_validate(parsed)

    with closing(db.connect(test_db)) as conn:
        data = advanced.advanced_summary(cfg, conn, now=NOW)

    assert data["settings"]["chief"] == "claude"
    assert data["settings"]["language"] == "en"
    assert data["profiles"]["active"] == "balanced"
    assert "fast" in data["profiles"]["available"]
    assert data["budgets"]["providers"]["remote"]["daily_usd"] == 5.0
    assert "queue" in data
    assert "circuit_breakers" in data


def test_web_server_usage_and_advanced_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, test_db: Path
) -> None:
    cfg_file = tmp_path / "orkestra.yaml"
    cfg_file.write_text(SAMPLE_CONFIG, encoding="utf-8")

    server = create_server(ServerConfig(port=0, config_path=cfg_file))
    try:
        # 1. 403 when token missing
        code, _, _ = simulate_request(server, "GET", "/api/usage")
        assert code == 403
        code, _, _ = simulate_request(server, "GET", "/api/advanced")
        assert code == 403

        # 2. GET /api/usage returns valid JSON
        code, _, body = simulate_request(server, "GET", f"/api/usage?token={server.token}")
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert "totals" in data
        assert "providers" in data
        assert "daily" in data
        assert "savings" in data

        # 3. GET /api/advanced returns valid JSON
        code, _, body = simulate_request(server, "GET", f"/api/advanced?token={server.token}")
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert "budgets" in data
        assert "profiles" in data
        assert "queue" in data
        assert "circuit_breakers" in data
        assert "settings" in data
    finally:
        server.server_close()
