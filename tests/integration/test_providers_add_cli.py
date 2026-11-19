"""``providers add`` / ``import opencode`` / ``remove`` (Faz 13o), with no network."""

from __future__ import annotations

import json
import re
from contextlib import closing
from pathlib import Path

import httpx
import pytest
import respx

from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.config.schema import OpenAICompatProvider
from orkestra.i18n import t
from orkestra.state import consent, db

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
BASE = "https://llm.example.test/v1"
FAKE_KEY = "sk-FAKE-opencode-key-never-copied-0000000000000000"

CONFIG = """\
# my notes
version: 1
providers:
  ollama:
    type: ollama
    models:
      - id: coder
        tier: 1
"""


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "orkestra-home"
    path.mkdir()
    (path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.delenv("OPENCODE_CONFIG", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("EVREN_API_KEY", raising=False)
    return path


def _chat(name: str) -> OpenAICompatProvider:
    cfg = load_config().config.providers[name]
    assert isinstance(cfg, OpenAICompatProvider)
    return cfg


def _config_text(home: Path) -> str:
    return (home / "config.yaml").read_text(encoding="utf-8")


def _opencode(tmp_path: Path) -> Path:
    path = tmp_path / "opencode.json"
    data = {
        "provider": {
            "evren": {
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": BASE, "apiKey": FAKE_KEY},
                "models": {"deepseek-v4.1-flash": {}, "glm-5.3": {}},
            },
            "claude": {"npm": "@ai-sdk/anthropic", "models": {"x": {}}},
        }
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


ADD = ["providers", "add", "evren", "--base-url", BASE, "--model", "deepseek-v4.1-flash",
       "--model", "glm-5.3"]  # fmt: skip


# --- add -----------------------------------------------------------------------------------


def test_add_writes_the_provider_and_points_to_consent(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(ADD, capsys)
    assert code == 0
    cfg = _chat("evren")
    assert cfg.type == "openai_compat"
    assert cfg.api_key_env == "EVREN_API_KEY"  # suggested from the name
    assert [(m.id, m.tier) for m in cfg.models] == [("deepseek-v4.1-flash", 2), ("glm-5.3", 2)]
    assert _config_text(home).startswith(CONFIG)
    assert t("providers.add.saved", name="evren", path=home / "config.yaml") in out
    assert t("providers.add.key_missing", var="EVREN_API_KEY") in out
    assert "orkestra providers enable evren" in out
    with closing(db.connect()) as conn:
        assert consent.state(conn, "evren", cfg) == "missing"  # adding is not consenting


def test_add_json(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run([*ADD, "--tier", "1", "--context-window", "32000", "--json"], capsys)
    assert code == 0
    data = json.loads(out)
    assert data["name"] == "evren"
    assert data["path"] == str(home / "config.yaml")
    assert data["api_key_env"] == "EVREN_API_KEY"
    assert data["key_present"] is False
    assert data["models"] == [
        {"id": "deepseek-v4.1-flash", "tier": 1, "context_window": 32000},
        {"id": "glm-5.3", "tier": 1, "context_window": 32000},
    ]
    assert data["next"] == "orkestra providers enable evren"
    assert data["check"] is None


def test_an_existing_name_needs_force(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(ADD, capsys)[0] == 0
    code, _, err = _run(ADD, capsys)
    assert code == 2
    assert t("providers.error.exists", name="evren") in err
    assert _run([*ADD, "--force"], capsys)[0] == 0


def test_no_key_for_a_local_server(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, _ = _run(["providers", "add", "lab", "--base-url", "http://localhost:1234/v1",
                       "--model", "m", "--no-key"], capsys)  # fmt: skip
    assert code == 0
    assert _chat("lab").api_key_env is None
    code, _, _ = _run(["providers", "add", "lab2", "--base-url", "http://localhost:1/v1",
                         "--model", "m", "--no-key", "--api-key-env", "X"], capsys)  # fmt: skip
    assert code == 2


def test_add_to_the_project_file(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, _ = _run([*ADD, "--project"], capsys)
    assert code == 0
    assert "evren" not in _config_text(home)
    assert "evren" in (Path.cwd() / "orkestra.yaml").read_text(encoding="utf-8")
    assert {"ollama", "evren"} <= set(load_config().config.providers)


@respx.mock
def test_check_asks_the_server_for_its_models(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVREN_API_KEY", "sk-fake")
    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "deepseek-v4.1-flash"}]})
    )
    code, out, _ = _run([*ADD, "--check"], capsys)
    assert code == 0  # a missing model is a warning; the provider itself answers
    assert t("doctor.api.model_missing", model="glm-5.3") in out
    assert t("providers.add.key_present", var="EVREN_API_KEY") in out


@respx.mock
def test_a_failed_check_keeps_the_entry_and_exits_3(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVREN_API_KEY", "sk-fake")
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(401, json={"error": "no"}))
    code, out, _ = _run([*ADD, "--check", "--json"], capsys)
    assert code == 3
    data = json.loads(out)
    assert data["check"]["ok"] is False
    assert "evren" in load_config().config.providers


# --- import opencode -----------------------------------------------------------------------


def test_import_opencode_takes_the_only_supported_provider(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _opencode(tmp_path)
    code, out, err = _run(["providers", "import", "opencode", "--path", str(source)], capsys)
    assert code == 0
    cfg = _chat("evren")
    assert cfg.base_url == BASE
    assert [m.id for m in cfg.models] == ["deepseek-v4.1-flash", "glm-5.3"]
    assert cfg.api_key_env == "EVREN_API_KEY"
    assert t("providers.import.plain_key", var="EVREN_API_KEY", path=source) in out
    for text in (_config_text(home), out, err):
        assert FAKE_KEY not in text
    assert "claude" not in load_config().config.providers


def test_import_opencode_lists_when_there_is_a_choice(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _opencode(tmp_path)
    data = json.loads(source.read_text(encoding="utf-8"))
    data["provider"]["lab"] = {"npm": "@ai-sdk/openai-compatible",
                               "options": {"baseURL": "http://localhost:1234/v1",
                                           "apiKey": "{env:LAB_TOKEN}"},
                               "models": {"m": {}}}  # fmt: skip
    source.write_text(json.dumps(data), encoding="utf-8")
    code, out, _ = _run(["providers", "import", "opencode", "--path", str(source), "--json"],
                        capsys)  # fmt: skip
    assert code == 0
    listed = json.loads(out)
    assert listed["imported"] is None
    rows = {row["name"]: row for row in listed["providers"]}
    assert rows["lab"]["key"] == {"env": "LAB_TOKEN", "plain": False, "file": False}
    assert rows["evren"]["key"] == {"env": None, "plain": True, "file": False}
    assert rows["claude"]["supported"] is False
    assert FAKE_KEY not in out
    assert "lab" not in load_config().config.providers

    code, _, _ = _run(["providers", "import", "opencode", "--path", str(source),
                       "--name", "lab"], capsys)  # fmt: skip
    assert code == 0
    assert _chat("lab").api_key_env == "LAB_TOKEN"


def test_import_refuses_an_unsupported_provider(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = _run(["providers", "import", "opencode", "--path", str(_opencode(tmp_path)),
                         "--name", "claude"], capsys)  # fmt: skip
    assert code == 2
    assert t("providers.import.unsupported", name="claude", npm="@ai-sdk/anthropic") in err


def test_import_only_knows_opencode(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(["providers", "import", "cursor"], capsys)[0] == 2


def test_import_finds_opencode_in_its_default_place(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENCODE_CONFIG", str(_opencode(tmp_path)))
    assert _run(["providers", "import", "opencode"], capsys)[0] == 0
    assert "evren" in load_config().config.providers


# --- remove --------------------------------------------------------------------------------


def test_remove_deletes_the_entry_and_its_consent(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(ADD, capsys)
    assert _run(["providers", "enable", "evren", "--yes"], capsys)[0] == 0
    code, out, _ = _run(["providers", "remove", "evren"], capsys)
    assert code == 0
    assert _config_text(home) == CONFIG
    assert t("providers.remove.done", name="evren", path=home / "config.yaml") in out
    with closing(db.connect()) as conn:
        assert consent.revoke(conn, "evren") is False  # already gone


def test_remove_an_unknown_provider(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _run(["providers", "remove", "evren"], capsys)
    assert code == 2
    assert t("providers.error.not_in_file", name="evren", path=home / "config.yaml") in err


def test_import_as_another_name(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _opencode(tmp_path)
    code, _, _ = _run(["providers", "import", "opencode", "--path", str(source),
                       "--as", "evren2"], capsys)  # fmt: skip
    assert code == 0
    assert _chat("evren2").api_key_env == "EVREN2_API_KEY"


def test_a_pasted_key_is_refused_and_not_echoed(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pasted = "sk-live-PASTEDKEY000000000000"
    code, out, err = _run([*ADD, "--api-key-env", pasted], capsys)
    assert code == 2
    assert pasted not in out + err + _config_text(home)


PROJECT_LAB = """\
version: 1
providers:
  lab:
    type: openai_compat
    base_url: http://localhost:1/v1
    models:
      - id: m
        tier: 1
"""


def test_remove_keeps_consent_while_the_project_file_still_defines_it(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(ADD, capsys)
    (Path.cwd() / "orkestra.yaml").write_text(
        PROJECT_LAB,
        encoding="utf-8",
    )
    _run(["providers", "add", "lab", "--base-url", "http://localhost:2/v1", "--model", "m",
          "--no-key"], capsys)  # fmt: skip
    assert _run(["providers", "enable", "lab", "--yes"], capsys)[0] == 0
    code, out, _ = _run(["providers", "remove", "lab"], capsys)
    assert code == 0
    assert t("consent.revoked", name="lab") not in out
    assert "lab" in load_config().config.providers
