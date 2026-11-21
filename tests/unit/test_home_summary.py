from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from orkestra.chief.home import HomeSummary, home_summary
from orkestra.config.schema import Config, ModelSpec, OllamaProvider, OpenAICompatProvider
from orkestra.doctor import Check, DoctorReport
from orkestra.errors import ProviderAuthError, ProviderQuotaExhausted
from orkestra.state import consent, db, health
from orkestra.workspace.service import Unapplied

NOW = datetime(2026, 11, 21, 14, 0, tzinfo=timezone(timedelta(hours=3)))


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "state.db")) as connection:
        yield connection


def _config(*, ollama: bool = True, cloud: bool = True) -> Config:
    providers: dict[str, Any] = {}
    if ollama:
        providers["ollama"] = OllamaProvider(
            type="ollama",
            base_url="http://localhost:11434",
            models=[ModelSpec(id="qwen2.5-coder:7b", tier=1)],
        )
    if cloud:
        providers["openrouter"] = OpenAICompatProvider(
            type="openai_compat",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
            models=[ModelSpec(id="anthropic/claude-3.5-sonnet", tier=3)],
        )
    return Config(version=1, providers=providers)


def test_home_summary_all_ready(conn: sqlite3.Connection) -> None:
    cfg = _config()
    consent.grant(conn, "ollama", cfg.providers["ollama"], NOW)
    consent.grant(conn, "openrouter", cfg.providers["openrouter"], NOW)
    env = {"OPENROUTER_API_KEY": "sk-secret-test"}

    summary = home_summary(cfg, conn, NOW, environ=env)

    assert isinstance(summary, HomeSummary)
    assert summary.status == "ok"
    assert len(summary.providers) == 2

    p_map = {p.name: p for p in summary.providers}
    assert p_map["ollama"].status == "ready"
    assert p_map["ollama"].is_local is True
    assert p_map["openrouter"].status == "ready"
    assert p_map["openrouter"].is_local is False


def test_home_summary_no_consent(conn: sqlite3.Connection) -> None:
    cfg = _config()
    # No consent granted
    env = {"OPENROUTER_API_KEY": "sk-secret-test"}

    summary = home_summary(cfg, conn, NOW, environ=env)

    assert summary.status in ("warn", "fail")
    p_map = {p.name: p for p in summary.providers}
    assert p_map["ollama"].status == "no_consent"
    ns = summary.next_step.lower()
    assert "ollama" in ns or "onay" in ns or "consent" in ns


def test_home_summary_no_key(conn: sqlite3.Connection) -> None:
    cfg = _config(ollama=False, cloud=True)
    consent.grant(conn, "openrouter", cfg.providers["openrouter"], NOW)
    # OPENROUTER_API_KEY not in env

    summary = home_summary(cfg, conn, NOW, environ={})

    assert summary.status == "fail"
    p = summary.providers[0]
    assert p.status == "no_key"
    assert "OPENROUTER_API_KEY" in summary.next_step or "openrouter" in summary.next_step.lower()


def test_home_summary_paused_provider(conn: sqlite3.Connection) -> None:
    cfg = _config()
    consent.grant(conn, "ollama", cfg.providers["ollama"], NOW)
    consent.grant(conn, "openrouter", cfg.providers["openrouter"], NOW)
    env = {"OPENROUTER_API_KEY": "sk-secret-test"}

    # Pause openrouter with auth failure
    health.record_failure(conn, "openrouter", ProviderAuthError("auth error"), NOW)

    summary = home_summary(cfg, conn, NOW, environ=env)

    p_map = {p.name: p for p in summary.providers}
    assert p_map["ollama"].status == "ready"
    assert p_map["openrouter"].status == "paused"
    text = p_map["openrouter"].status_text.lower()
    assert "paused" in text or "duraklatıldı" in text


def test_home_summary_quota_paused(conn: sqlite3.Connection) -> None:
    cfg = _config()
    consent.grant(conn, "ollama", cfg.providers["ollama"], NOW)
    consent.grant(conn, "openrouter", cfg.providers["openrouter"], NOW)
    env = {"OPENROUTER_API_KEY": "sk-secret-test"}

    health.record_failure(
        conn, "openrouter", ProviderQuotaExhausted("quota exceeded", pause_s=2700), NOW
    )

    summary = home_summary(cfg, conn, NOW, environ=env)

    p_map = {p.name: p for p in summary.providers}
    assert p_map["openrouter"].status == "paused"
    text = p_map["openrouter"].status_text.lower()
    assert "quota" in text or "kota" in text


def test_home_summary_disabled_provider(conn: sqlite3.Connection) -> None:
    cfg = _config()
    cfg.providers["ollama"].enabled = False
    consent.grant(conn, "openrouter", cfg.providers["openrouter"], NOW)
    env = {"OPENROUTER_API_KEY": "sk-secret-test"}

    summary = home_summary(cfg, conn, NOW, environ=env)

    p_map = {p.name: p for p in summary.providers}
    assert p_map["ollama"].status == "disabled"
    assert p_map["openrouter"].status == "ready"


def test_home_summary_unapplied_runs(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _config()
    consent.grant(conn, "ollama", cfg.providers["ollama"], NOW)
    consent.grant(conn, "openrouter", cfg.providers["openrouter"], NOW)
    env = {"OPENROUTER_API_KEY": "sk-secret-test"}

    monkeypatch.setattr(
        "orkestra.chief.home.service.unapplied_runs",
        lambda c: [Unapplied("r1", "t1", "Fix docstring")],
    )

    summary = home_summary(cfg, conn, NOW, environ=env)

    assert summary.pending.unapplied_runs == 1
    assert "apply" in summary.next_step.lower()


def test_home_summary_doctor_report(conn: sqlite3.Connection) -> None:
    cfg = _config()
    consent.grant(conn, "ollama", cfg.providers["ollama"], NOW)
    consent.grant(conn, "openrouter", cfg.providers["openrouter"], NOW)
    env = {"OPENROUTER_API_KEY": "sk-secret-test"}

    report = DoctorReport(
        checks=(
            Check(name="provider:ollama", status="ok", message="ollama is healthy"),
            Check(name="provider:openrouter", status="fail", message="unauthorized"),
        )
    )

    summary = home_summary(cfg, conn, NOW, environ=env, doctor_report=report)

    p_map = {p.name: p for p in summary.providers}
    assert p_map["ollama"].doctor_status == "ok"
    assert p_map["openrouter"].doctor_status == "fail"
    assert p_map["openrouter"].doctor_message == "unauthorized"


def _ready_both(conn: sqlite3.Connection) -> tuple[Config, dict[str, str]]:
    cfg = _config()
    consent.grant(conn, "ollama", cfg.providers["ollama"], NOW)
    consent.grant(conn, "openrouter", cfg.providers["openrouter"], NOW)
    return cfg, {"OPENROUTER_API_KEY": "sk-secret-test"}


def test_home_summary_doctor_fail_makes_provider_not_ready(conn: sqlite3.Connection) -> None:
    cfg, env = _ready_both(conn)
    report = DoctorReport(
        checks=(
            Check(name="provider:ollama", status="ok", message="healthy"),
            Check(name="provider:openrouter", status="fail", message="unauthorized"),
        )
    )

    summary = home_summary(cfg, conn, NOW, environ=env, doctor_report=report)

    p_map = {p.name: p for p in summary.providers}
    assert p_map["openrouter"].status == "check_failed"
    assert "unauthorized" in p_map["openrouter"].status_text
    assert p_map["ollama"].status == "ready"
    assert summary.status == "warn"
    assert "openrouter" in summary.status_text
    assert "openrouter" in summary.next_step
    assert "unauthorized" in summary.next_step


def test_home_summary_all_doctor_fail_is_red(conn: sqlite3.Connection) -> None:
    cfg, env = _ready_both(conn)
    report = DoctorReport(
        checks=(
            Check(name="provider:ollama", status="fail", message="not running"),
            Check(name="provider:openrouter", status="fail", message="unauthorized"),
        )
    )

    summary = home_summary(cfg, conn, NOW, environ=env, doctor_report=report)

    assert summary.status == "fail"
    assert "ollama" in summary.next_step
    assert "not running" in summary.next_step


def test_home_summary_doctor_warn_warns_but_stays_ready(conn: sqlite3.Connection) -> None:
    cfg, env = _ready_both(conn)
    report = DoctorReport(
        checks=(Check(name="provider:openrouter", status="warn", message="quota forecast low"),)
    )

    summary = home_summary(cfg, conn, NOW, environ=env, doctor_report=report)

    p_map = {p.name: p for p in summary.providers}
    assert p_map["openrouter"].status == "ready"
    assert summary.status == "warn"
    assert "openrouter" in summary.status_text
    assert "quota forecast low" in summary.next_step


def test_home_summary_doctor_sub_checks_map_to_provider_worst_wins(
    conn: sqlite3.Connection,
) -> None:
    cfg, env = _ready_both(conn)
    report = DoctorReport(
        checks=(
            Check(name="provider:ollama", status="info", message="found"),
            Check(name="provider:ollama:login", status="warn", message="not logged in"),
            Check(name="provider:ollama:mcp:unity", status="ok", message="answers"),
            Check(name="provider:openrouter:mcp:x", status="info", message="exited"),
        )
    )

    summary = home_summary(cfg, conn, NOW, environ=env, doctor_report=report)

    p_map = {p.name: p for p in summary.providers}
    assert p_map["ollama"].doctor_status == "warn"
    assert p_map["ollama"].doctor_message == "not logged in"
    assert p_map["openrouter"].doctor_status == "info"


def test_home_summary_doctor_prefix_does_not_match_other_provider(
    conn: sqlite3.Connection,
) -> None:
    cfg, env = _ready_both(conn)
    report = DoctorReport(checks=(Check(name="provider:ollamax", status="fail", message="x"),))

    summary = home_summary(cfg, conn, NOW, environ=env, doctor_report=report)

    p_map = {p.name: p for p in summary.providers}
    assert p_map["ollama"].doctor_status is None
    assert p_map["ollama"].status == "ready"


def test_home_summary_paused_until_multiday(conn: sqlite3.Connection) -> None:
    cfg = _config()
    consent.grant(conn, "ollama", cfg.providers["ollama"], NOW)
    consent.grant(conn, "openrouter", cfg.providers["openrouter"], NOW)
    env = {"OPENROUTER_API_KEY": "sk-secret-test"}

    tomorrow = NOW + timedelta(days=1, hours=2)
    health.record_failure(conn, "openrouter", ProviderAuthError("auth error"), NOW)
    with conn:
        conn.execute(
            "UPDATE health SET open_until = ? WHERE provider = 'openrouter'",
            (tomorrow.isoformat(),),
        )

    summary = home_summary(cfg, conn, NOW, environ=env)
    p_map = {p.name: p for p in summary.providers}
    assert p_map["openrouter"].status == "paused"
    assert f"{tomorrow:%Y-%m-%d}" in p_map["openrouter"].status_text


def test_home_summary_single_paused_warn_next_step_is_wait_or_reset(
    conn: sqlite3.Connection,
) -> None:
    from orkestra.i18n import t

    cfg, env = _ready_both(conn)
    health.record_failure(conn, "openrouter", ProviderAuthError("auth error"), NOW)

    summary = home_summary(cfg, conn, NOW, environ=env)
    assert summary.status == "warn"
    assert summary.next_step == t("home.next_step.wait_or_reset")


def test_home_summary_queue_failed_warn_suggests_queue_list(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, env = _ready_both(conn)

    monkeypatch.setattr(
        "orkestra.chief.home.queue_store.counts",
        lambda c, failed_since: {"pending": 0, "running": 0, "failed": 1},
    )

    summary = home_summary(cfg, conn, NOW, environ=env)
    assert summary.status == "warn"
    assert "queue list" in summary.next_step
