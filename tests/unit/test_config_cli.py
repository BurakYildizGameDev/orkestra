from __future__ import annotations

import io
import json
import re
import sys
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from orkestra.cli import app

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

INVALID_TIER = """\
version: 1
providers:
  openrouter:
    type: openai_compat
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    models:
      - id: provider/model
        tier: 4
"""

UNKNOWN_TYPE = "version: 1\nproviders:\n  web:\n    type: chatgpt_web\n"

DANGER = """\
version: 1
providers:
  codex:
    type: cli_agent
    command: codex
    sandbox: danger-full-access
"""


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "orkestra-home"


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    monkeypatch.chdir(path)
    return path


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- config validate -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (INVALID_TIER, "providers.openrouter.models[0].tier: must be 1, 2 or 3"),
        (UNKNOWN_TYPE, "providers.web: unknown provider type 'chatgpt_web'"),
        (DANGER, "providers.codex.sandbox: 'danger-full-access' is not supported"),
    ],
)
def test_validate_rejects_with_exit_2(
    text: str, expected: str, home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(home / "config.yaml", text)
    code, out, err = _run(["config", "validate"], capsys)
    assert code == 2
    assert out == ""
    assert expected in err


def test_validate_ok(home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(home / "config.yaml", "version: 1\n")
    code, out, _ = _run(["config", "validate"], capsys)
    assert code == 0
    assert "valid" in out
    assert str(home / "config.yaml") in out


def test_validate_message_in_turkish(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(home / "config.yaml", INVALID_TIER)
    code, _, err = _run(["--lang", "tr", "config", "validate"], capsys)
    assert code == 2
    assert "providers.openrouter.models[0].tier: 1, 2 veya 3 olmalı" in err


def test_language_from_config_file(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(home / "config.yaml", "version: 1\nlanguage: tr\n")
    _, out, _ = _run(["config", "validate"], capsys)
    assert "geçerli" in out
    _, out, _ = _run(["--lang", "en", "config", "validate"], capsys)
    assert "valid" in out


def test_validate_json_error(home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(home / "config.yaml", INVALID_TIER)
    code, out, _ = _run(["config", "validate", "--json"], capsys)
    assert code == 2
    doc = json.loads(out)
    assert doc["error"]["code"] == 2
    assert doc["error"]["type"] == "ConfigError"
    assert "providers.openrouter.models[0].tier: must be 1, 2 or 3" in doc["error"]["details"]


def test_validate_json_ok(home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(home / "config.yaml", "version: 1\n")
    code, out, _ = _run(["config", "validate", "--json"], capsys)
    assert code == 0
    doc = json.loads(out)
    assert doc["valid"] is True
    assert doc["sources"] == [{"kind": "global", "path": str(home / "config.yaml")}]


def test_validate_yaml_syntax_error(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(home / "config.yaml", "version: 1\nproviders:\n  - [\n")
    code, _, err = _run(["config", "validate"], capsys)
    assert code == 2
    assert "line" in err


def test_config_flag(tmp_path: Path, workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    custom = _write(tmp_path / "custom.yaml", INVALID_TIER)
    code, _, err = _run(["--config", str(custom), "config", "validate"], capsys)
    assert code == 2
    assert str(custom) in err


def test_config_flag_missing_file(
    tmp_path: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = _run(["--config", str(tmp_path / "missing.yaml"), "config", "show"], capsys)
    assert code == 2
    assert "missing.yaml" in err


# --- config show -----------------------------------------------------------------------


def test_show_json_is_valid_json(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(home / "config.yaml", "version: 1\ndefaults:\n  timeout_s: 42\n")
    _write(workdir / "orkestra.yaml", "defaults:\n  max_retries: 5\n")
    code, out, _ = _run(["config", "show", "--json"], capsys)
    assert code == 0
    doc: dict[str, Any] = json.loads(out)
    assert [s["kind"] for s in doc["sources"]] == ["global", "project"]
    assert doc["config"]["version"] == 1
    assert doc["config"]["defaults"]["timeout_s"] == 42
    assert doc["config"]["defaults"]["max_retries"] == 5
    assert doc["config"]["defaults"]["profile"] == "balanced"


def test_show_human_prints_yaml(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(home / "config.yaml", "version: 1\n")
    code, out, err = _run(["config", "show"], capsys)
    assert code == 0
    data = YAML(typ="safe").load(StringIO(out))
    assert data["version"] == 1
    assert str(home / "config.yaml") in err


def test_show_without_any_config(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(["config", "show", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["sources"] == []
    assert err == ""


# --- init ------------------------------------------------------------------------------


def test_init_creates_global_config(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = _run(["init"], capsys)
    assert code == 0
    target = home / "config.yaml"
    assert target.is_file()
    code, _, _ = _run(["config", "validate"], capsys)
    assert code == 0


def test_init_twice_does_not_touch_file(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(["init"], capsys)
    target = home / "config.yaml"
    target.write_text(target.read_text(encoding="utf-8") + "# my edit\n", encoding="utf-8")
    before = target.read_bytes()
    code, out, err = _run(["init"], capsys)
    assert code == 0
    assert target.read_bytes() == before
    assert "--force" in out + err


def test_init_force_overwrites_with_backup(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = _write(home / "config.yaml", "version: 1\n# mine\n")
    code, _, _ = _run(["init", "--force"], capsys)
    assert code == 0
    assert "# mine" not in target.read_text(encoding="utf-8")
    assert (home / "config.yaml.bak").read_text(encoding="utf-8") == "version: 1\n# mine\n"


def test_init_project(workdir: Path, home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, _ = _run(["init", "--project"], capsys)
    assert code == 0
    assert (workdir / "orkestra.yaml").is_file()
    assert not (home / "config.yaml").exists()


def test_init_respects_config_flag(
    tmp_path: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "elsewhere" / "cfg.yaml"
    code, _, _ = _run(["--config", str(target), "init"], capsys)
    assert code == 0
    assert target.is_file()


def test_init_adds_cache_to_gitignore_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(repo / ".gitignore", "node_modules/")  # no trailing newline
    sub = repo / "src"
    sub.mkdir()
    monkeypatch.chdir(sub)
    _run(["init", "--project"], capsys)
    _run(["init", "--project"], capsys)
    lines = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines == ["node_modules/", ".orkestra/cache/"]


def test_init_creates_gitignore_in_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.chdir(repo)
    _run(["init", "--project"], capsys)
    assert (repo / ".gitignore").read_text(encoding="utf-8") == ".orkestra/cache/\n"


def test_init_outside_git_leaves_no_gitignore(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(["init", "--project"], capsys)
    assert not (workdir / ".gitignore").exists()


def test_init_keeps_existing_cache_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".gitignore").write_bytes(b"/.orkestra/cache\r\n")
    monkeypatch.chdir(repo)
    _run(["init"], capsys)
    assert (repo / ".gitignore").read_bytes() == b"/.orkestra/cache\r\n"


# --- code review fixes (Faz 1, PR #2) ---------------------------------------------------


def test_global_init_leaves_the_cwd_repo_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.chdir(repo)
    code, _, _ = _run(["init"], capsys)
    assert code == 0
    assert not (repo / ".gitignore").exists()


def test_internal_error_in_json_mode_is_json(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from orkestra.config import loader

    def boom(*_: Any, **__: Any) -> Any:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(loader, "init_config", boom)
    code, out, err = _run(["init", "--json"], capsys)
    assert code == 10
    error = json.loads(out)["error"]
    assert error["code"] == 10
    assert error["type"] == "InternalError"
    assert "kaboom" in error["message"]
    assert "kaboom" in err


def test_language_prescan_errors_do_not_escape(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from orkestra.config import loader

    def boom(*_: Any, **__: Any) -> Any:
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(loader, "find_sources", boom)
    code, out, _ = _run(["--version"], capsys)
    assert code == 0
    assert "orkestra" in out


def test_config_show_masks_secret_headers(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(
        home / "config.yaml",
        "version: 1\nproviders:\n  r:\n    type: openai_compat\n    base_url: https://r.test/v1\n"
        "    extra_headers:\n      Authorization: Bearer sk-secretvalue1234567890abcd\n"
        "      x-api-key: plainsecret\n      X-Title: Orkestra\n"
        "    models: [{id: m, tier: 1}]\n",
    )
    for argv in (["config", "show"], ["config", "show", "--json"]):
        code, out, _ = _run(argv, capsys)
        assert code == 0
        assert "secretvalue" not in out and "plainsecret" not in out
        assert "Orkestra" in out


class _Console(io.TextIOWrapper):
    """A text stream that says it is a terminal (a console with a legacy code page)."""

    def isatty(self) -> bool:
        return True


def test_redirected_output_is_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows pipes default to the ANSI code page (cp1254), but the reader (Claude Code,
    # Git Bash, a file) expects UTF-8: Turkish letters came out as "ko�usu".
    from orkestra import cli

    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1254"))
    cli._safe_streams()
    print("Merhaba 😀 → koşusu ğüş")
    sys.stdout.flush()
    assert raw.getvalue().decode("utf-8").startswith("Merhaba 😀 → koşusu ğüş")


def test_a_legacy_console_never_crashes_on_unencodable_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from orkestra import cli

    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", _Console(raw, encoding="cp1254"))
    cli._safe_streams()
    print("Merhaba 😀 → ğüş")
    sys.stdout.flush()
    assert raw.getvalue().decode("cp1254").startswith("Merhaba ? ? ğüş")


def test_a_utf8_stream_never_crashes_on_undecodable_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    # git output is decoded with surrogateescape; printing such a path must not raise.
    from orkestra import cli

    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="utf-8"))
    cli._safe_streams()
    print("dosya-\udcff.txt")
    sys.stdout.flush()
    assert raw.getvalue().decode("utf-8").startswith("dosya-?.txt")


def test_pythonioencoding_is_respected_for_redirected_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from orkestra import cli

    monkeypatch.setenv("PYTHONIOENCODING", "cp1254")
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1254"))
    cli._safe_streams()
    print("koşu \U0001f600")
    sys.stdout.flush()
    assert raw.getvalue().decode("cp1254").startswith("koşu ?")
