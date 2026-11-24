"""Faz 11c final review (Claude, 2026-11-21): one test per finding, written before the fix."""

from __future__ import annotations

import json
import re
import sys
import types
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import keyring
import pytest

from orkestra.chief import advanced, keys, team
from orkestra.config import loader
from orkestra.config.schema import NotifyCfg
from orkestra.errors import ProviderAuthError
from orkestra.i18n import set_language, t
from orkestra.notify import notify
from orkestra.state import db, health
from orkestra.web import ui
from orkestra.web.server import ServerConfig, create_server
from tests.unit.test_web_server import simulate_request

NOW = datetime(2026, 11, 21, 14, 0, tzinfo=UTC)

BASE_CONFIG = """\
version: 1
language: en
defaults:
  chief: agy
chiefs:
  claude:
    launch: ["claude"]
  agy:
    launch: ["agy"]
  codex:
    launch: ["codex"]
providers:
  local:
    type: ollama
    base_url: http://localhost:11434
    models:
      - id: qwen2.5-coder:7b
        tier: 1
  agy:
    type: cli_agent
    command: agy
    tier: 3
"""


@pytest.fixture
def state_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "state.db"
    monkeypatch.setattr("orkestra.paths.state_db_path", lambda: db_file)
    with closing(db.connect(db_file)):
        pass
    return db_file


@pytest.fixture
def cfg_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(BASE_CONFIG, encoding="utf-8")
    return path


# 1. Tests never touch the developer's credential store.
def test_tests_use_an_in_memory_keyring(memory_keyring: object) -> None:
    assert keyring.get_keyring() is memory_keyring
    assert keys.get_key("ORKESTRA_REVIEW_UNSET", {}) is None


# 2. A ntfy topic saved from the Keys screen is the one notifications use.
def test_ntfy_topic_saved_in_keyring_is_used(no_real_notifications: list[tuple[str, ...]]) -> None:
    keys.set_key("ORK_NTFY_TOPIC", "my-private-topic-123")
    deliveries = notify.send(
        NotifyCfg(desktop=False, ntfy_topic_env="ORK_NTFY_TOPIC"), "title", "message", environ={}
    )
    assert [(d.channel, d.state) for d in deliveries] == [("ntfy", "sent")]
    assert no_real_notifications and "my-private-topic-123" in no_real_notifications[0][0]


# 3. --window: a pywebview that cannot start (no GUI backend) falls back to the browser.
def test_window_that_fails_to_start_falls_back_to_browser(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import webbrowser

    from orkestra.web import server
    from tests.unit.test_ui_cli import _run

    opened = MagicMock()
    monkeypatch.setattr(webbrowser, "open", opened)
    fake = types.ModuleType("webview")
    fake.create_window = MagicMock()  # type: ignore[attr-defined]
    fake.start = MagicMock(side_effect=RuntimeError("no GUI backend"))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(server.WebServer, "serve_forever", MagicMock())
    monkeypatch.setattr(server.WebServer, "shutdown", MagicMock())

    code, _, err = _run(["ui", "--window"], capsys)
    assert code == 0
    assert t("ui.web.window_failed", reason="no GUI backend") in err
    assert "Traceback" not in err
    opened.assert_called_once()


# 4. Tier and model go to the file that defines them, not to a project override.
def test_tier_and_model_change_the_file_that_defines_the_models(
    tmp_path: Path, cfg_file: Path
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "orkestra.yaml").write_text(
        "providers:\n  local:\n    enabled: false\n", encoding="utf-8"
    )
    team.set_worker_tier(cfg_file, "local", 2, cwd=project)
    team.set_worker_model(cfg_file, "local", "llama3:8b", cwd=project)
    team.set_worker_tier(cfg_file, "agy", 2, cwd=project)

    effective = loader.load_config(cfg_file, project).config
    local = effective.providers["local"]
    assert [(m.id, m.tier) for m in local.models] == [("llama3:8b", 2), ("qwen2.5-coder:7b", 2)]  # type: ignore[union-attr]
    assert effective.providers["agy"].tier == 2  # type: ignore[union-attr]
    assert "models" not in (project / "orkestra.yaml").read_text(encoding="utf-8")


# 5. The handoff order shows the patron first, then who would take over.
def test_team_handoff_order_starts_with_the_patron(cfg_file: Path) -> None:
    config = loader.load_config(cfg_file).config
    summary = team.team_summary(config)
    assert summary.handoff_order == ("agy", "claude", "codex")


def test_team_api_returns_handoff_order(cfg_file: Path, state_db: Path) -> None:
    server = create_server(ServerConfig(port=0, token="tok", config_path=cfg_file))
    try:
        code, _, body = simulate_request(server, "GET", "/api/team?token=tok")
    finally:
        server.server_close()
    assert code == 200
    assert json.loads(body)["handoff_order"] == ["agy", "claude", "codex"]


# 6. "enabled": "false" (a string) is not silently read as True.
def test_toggle_rejects_a_non_boolean(cfg_file: Path, state_db: Path) -> None:
    server = create_server(ServerConfig(port=0, token="tok", config_path=cfg_file))
    try:
        body = json.dumps({"name": "local", "enabled": "false"}).encode("utf-8")
        code, _, _ = simulate_request(
            server, "POST", "/api/team/worker/toggle?token=tok", body=body
        )
    finally:
        server.server_close()
    assert code == 400
    assert loader.load_config(cfg_file).config.providers["local"].enabled is True


# 7. Usage: 7 or 30 days, chosen on the page; anything else is a 400.
def test_usage_api_takes_days(cfg_file: Path, state_db: Path) -> None:
    server = create_server(ServerConfig(port=0, token="tok", config_path=cfg_file))
    try:
        spans = {}
        for days in (7, 30):
            code, _, body = simulate_request(server, "GET", f"/api/usage?token=tok&days={days}")
            assert code == 200
            data = json.loads(body)
            since = datetime.fromisoformat(data["since"])
            until = datetime.fromisoformat(data["until"])
            spans[days] = round((until - since).total_seconds() / 86400)
        code, _, _ = simulate_request(server, "GET", "/api/usage?token=tok&days=abc")
        assert code == 400
        code, _, _ = simulate_request(server, "GET", "/api/usage?token=tok&days=9999")
        assert code == 400
    finally:
        server.server_close()
    assert spans == {7: 7, 30: 30}


def test_page_has_a_days_selector() -> None:
    page = ui.render_home_html("tok")
    assert 'id="usage-days"' in page
    assert "days=" in page


# 8. Advanced: when a paused provider comes back, and the handoff brief (plan item).
def test_advanced_breaker_says_until_when(state_db: Path, cfg_file: Path, tmp_path: Path) -> None:
    config = loader.load_config(cfg_file).config
    with closing(db.connect(state_db)) as conn:
        health.record_failure(conn, "local", ProviderAuthError("bad key"), NOW)
        data = advanced.advanced_summary(config, conn, now=NOW, cwd=tmp_path)
    local = next(b for b in data["circuit_breakers"] if b["provider"] == "local")
    assert local["is_open"] is True
    assert local["until_text"]
    assert local["reason_text"]


# Advanced showed values the config does not have (``config.budget``, ``defaults.privacy``,
# ``circuit_breaker``): always "no global limit", "privacy: any".
def test_advanced_shows_only_real_settings(state_db: Path, cfg_file: Path, tmp_path: Path) -> None:
    config = loader.load_config(cfg_file).config
    with closing(db.connect(state_db)) as conn:
        data = advanced.advanced_summary(config, conn, now=NOW, cwd=tmp_path)
    assert "daily" not in data["budgets"]
    assert "privacy" not in data["settings"]
    assert "circuit_breaker_failures" not in data["settings"]
    assert data["settings"]["profile"] == config.defaults.profile


def test_advanced_has_handoff_brief(state_db: Path, cfg_file: Path, tmp_path: Path) -> None:
    config = loader.load_config(cfg_file).config
    with closing(db.connect(state_db)) as conn:
        data = advanced.advanced_summary(config, conn, now=NOW, cwd=tmp_path)
    assert "handoff" in data
    assert data["handoff"]["text"]


# 9. The guide's documentation links work (relative links hit the token check: 403).
def test_guide_links_are_absolute_and_safe() -> None:
    page = ui.render_home_html("tok")
    assert 'href="docs/' not in page
    links = re.findall(r'<a href="(https://[^"]+)"[^>]*>', page)
    assert any(link.endswith("/docs/guide.md") for link in links)
    for tag in re.findall(r'<a href="https://[^>]+>', page):
        assert 'rel="noopener noreferrer"' in tag


# 10. No user-visible English baked into the page's script (AGENTS: everything via t()).
@pytest.mark.parametrize(
    "text",
    [
        "Global daily limit",
        "daily limit ",
        "Active profile",
        "min tier",
        " failures",
        "Language: ",
        "Chief: ",
        "Privacy: ",
        " runs (",
        "queueFallback",
        "Save failed",
        "Delete failed",
        '"unnamed"',
        '" tok"',
    ],
)
def test_page_script_has_no_hardcoded_text(text: str) -> None:
    set_language("tr")
    page = ui.render_home_html("tok")
    script = page.split("<script>", 1)[1]
    assert text not in script


# 11. Every class the script sets has a style (``el(tag, "a b", …)`` and ``is-<status>``).
def test_every_class_set_by_the_script_has_a_style() -> None:
    page = ui.render_home_html("tok")
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    script = page.split("<script>", 1)[1]
    used: set[str] = set()
    for classes in re.findall(r'el\("[a-z0-9]+", "([^"]+)"', script):
        used |= set(classes.split())
    for listed in re.findall(r"const [A-Z_]+_STATES = \[([^\]]+)\]", script):
        used |= {f"is-{name}" for name in re.findall(r'"([a-z_]+)"', listed)}
    assert used, "the script sets classes"
    missing = sorted(name for name in used if f".{name}" not in style)
    assert missing == []


def test_usage_and_advanced_use_local_time(
    state_db: Path, cfg_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = datetime(2026, 11, 21, 1, 30, tzinfo=UTC) + timedelta(hours=3)
    monkeypatch.setattr(db, "local_now", lambda: local)
    server = create_server(ServerConfig(port=0, token="tok", config_path=cfg_file))
    try:
        code, _, body = simulate_request(server, "GET", "/api/usage?token=tok")
    finally:
        server.server_close()
    assert code == 200
    assert json.loads(body)["until"] == local.isoformat()


# 12. Like ``providers add``: no variable given → the suggested one (so the Keys screen lists
# it); an explicit "no key" for a local server.
def test_add_api_worker_without_variable_suggests_one(cfg_file: Path) -> None:
    result = team.add_worker(
        cfg_file,
        name="openrouter",
        provider_type="openai_compat",
        model="some/model",
        base_url="https://openrouter.ai/api/v1",
    )
    assert result.config.providers["openrouter"].api_key_env == "OPENROUTER_API_KEY"  # type: ignore[union-attr]
    assert [k.var_name for k in keys.keys_status(result.config)] == ["OPENROUTER_API_KEY"]


def test_add_api_worker_with_no_key(cfg_file: Path) -> None:
    result = team.add_worker(
        cfg_file,
        name="lmstudio",
        provider_type="openai_compat",
        model="local-model",
        base_url="http://localhost:1234/v1",
        no_key=True,
    )
    assert result.config.providers["lmstudio"].api_key_env is None  # type: ignore[union-attr]


def test_add_form_has_a_no_key_choice() -> None:
    page = ui.render_home_html("tok")
    assert 'id="add-worker-no-key"' in page
    assert "no_key" in page.split("<script>", 1)[1]


def test_navigation_and_worker_reorder_have_accessible_labels() -> None:
    page = ui.render_home_html("tok")
    script = page.split("<script>", 1)[1]
    assert 'id="nav-home" class="nav-item active" data-tab="home" aria-pressed="true"' in page
    assert 'item.setAttribute("aria-pressed", String(active))' in script
    assert 'up.setAttribute("aria-label", up.title)' in script
    assert 'down.setAttribute("aria-label", down.title)' in script


# 13. Redesign (2026-11-21, user: "çok AI gibi"): texts the script shows come from the catalog
# by key, so a placeholder can never leak ("0 {count} bekleyen").
def test_script_translations_are_the_catalog_keys_it_uses() -> None:
    page = ui.render_home_html("tok")
    script = page.split("<script>", 1)[1]
    used = {k for k in re.findall(r'\btr\("([a-z0-9_.]+)"', script) if not k.endswith(".")}
    assert "home.pending.unapplied" in used
    found = re.search(r"const I18N = (\{.*?\});\n", script)
    assert found is not None
    catalog = json.loads(found.group(1))
    assert used <= set(catalog)


def test_claude_windows_have_readable_names() -> None:
    script = ui.render_home_html("tok").split("<script>", 1)[1]
    assert 'tr("home.claude." + w.name)' in script
    assert t("home.claude.five_hour") and t("home.claude.seven_day")


# 14. Keys: "try" a saved key with the doctor check of the providers that use it.
def test_key_test_runs_the_providers_checks(cfg_file: Path, state_db: Path) -> None:
    from orkestra.doctor import Check

    cfg_file.write_text(
        BASE_CONFIG
        + "  cloud:\n    type: openai_compat\n    base_url: https://api.example.test/v1\n"
        + "    api_key_env: CLOUD_API_KEY\n    models:\n      - id: m\n        tier: 2\n",
        encoding="utf-8",
    )
    keys.set_key("CLOUD_API_KEY", "sk-test-secret-value-123456")
    server = create_server(ServerConfig(port=0, token="tok", config_path=cfg_file))
    seen: list[str] = []

    def checker(name: str, config: object) -> list[Check]:
        seen.append(name)
        return [Check(f"provider:{name}", "ok", "reachable")]

    server.provider_checker = checker
    try:
        body = json.dumps({"var_name": "CLOUD_API_KEY"}).encode("utf-8")
        code, _, raw = simulate_request(server, "POST", "/api/keys/test?token=tok", body=body)
        bad = json.dumps({"var_name": "NOT_USED_KEY"}).encode("utf-8")
        bad_code, _, _ = simulate_request(server, "POST", "/api/keys/test?token=tok", body=bad)
    finally:
        server.server_close()
    assert code == 200
    assert seen == ["cloud"]
    assert json.loads(raw)["results"] == [
        {"provider": "cloud", "status": "ok", "message": "reachable"}
    ]
    assert b"sk-test-secret" not in raw
    assert bad_code == 400


# 15. The home row's limit text is translated ("runs 0/10" was the raw config name), and a
# provider without limits and without use today shows none ("0 requests, $0.0000" was noise).
def test_home_limit_text_is_translated_and_quiet_when_unused(
    tmp_path: Path, state_db: Path
) -> None:
    from orkestra.chief.home import home_summary

    path = tmp_path / "limits.yaml"
    path.write_text(BASE_CONFIG + "    budget:\n      daily_runs: 10\n", encoding="utf-8")
    config = loader.load_config(path).config
    with closing(db.connect(state_db)) as conn:
        summary = home_summary(config, conn, NOW, environ={})
    rows = {row.name: row for row in summary.providers}
    assert rows["agy"].limits_text == t("home.limit.daily_runs", used=0, value=10)
    assert rows["local"].limits_text is None
