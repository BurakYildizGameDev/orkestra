"""Faz 13k from the outside: ``status``, ``doctor``, notifications and ``statusline``."""

from __future__ import annotations

import io
import json
import re
import sys
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest

from orkestra import doctor
from orkestra.chief import limits
from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.notify import notify
from orkestra.state import db, forecast

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

CONFIG = """version: 1
providers:
  agy:
    type: cli_agent
    command: agy
    budget:
      daily_runs: 20
"""


def _run(
    argv: list[str], capsys: pytest.CaptureFixture[str], stdin: str | None = None,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> tuple[int, str, str]:  # fmt: skip
    if stdin is not None and monkeypatch is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    return (code if isinstance(code, int) else 0), _ANSI.sub("", captured.out), captured.err


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(CONFIG, encoding="utf-8")
    folder = tmp_path / "proj"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder


def _use_runs(runs: int, minutes_ago: int = 5) -> None:
    now = db.local_now()
    at = now - timedelta(minutes=minutes_ago)
    if at.date() != now.date():  # just after midnight: keep it on today
        at = now
    with closing(db.connect()) as conn, db.transaction(conn):
        conn.execute(
            "INSERT INTO usage (run_id, provider, model, day, prompt_tokens, completion_tokens, "
            "cost_usd, requests, runs, estimated, kind, created_at) "
            "VALUES ('r', 'agy', 'agy', ?, 0, 0, 0, ?, ?, 1, 'actual', ?)",
            (at.date().isoformat(), runs, runs, at.isoformat()),
        )


def test_status_warns_about_a_provider_running_low(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_runs(19)
    code, out, _ = _run(["--lang", "en", "status"], capsys)
    assert code == 0
    assert "quota running low: agy: " in out and "runs 19/20" in out

    code, out, _ = _run(["status", "--json"], capsys)
    [entry] = json.loads(out)["sections"]["forecast"]["providers"]
    assert entry["provider"] == "agy" and entry["low"] is True and entry["value"] == 20


def test_status_says_nothing_when_no_provider_runs_low(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_runs(2, minutes_ago=50)
    code, out, _ = _run(["--lang", "en", "status"], capsys)
    assert code == 0 and "running low" not in out
    code, out, _ = _run(["status", "--json"], capsys)
    assert json.loads(out)["sections"]["forecast"]["providers"][0]["low"] is False


def test_status_shows_the_chiefs_quota_from_the_status_line(
    project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    resets = int((db.local_now() + timedelta(hours=2)).timestamp())
    payload = json.dumps(
        {"rate_limits": {"five_hour": {"used_percentage": 64, "resets_at": resets}}}
    )
    code, out, _ = _run(["statusline"], capsys, payload, monkeypatch)
    assert code == 0 and out.strip().startswith("Claude 5h 64%")

    code, out, _ = _run(["--lang", "en", "status"], capsys)
    assert "Claude: 5h 64%" in out
    code, out, _ = _run(["status", "--json"], capsys)
    [window] = json.loads(out)["sections"]["chief_quota"]["windows"]
    assert window["name"] == "five_hour" and window["used"] == 64


def test_the_status_line_names_a_provider_running_low(
    project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_runs(19)
    payload = json.dumps({"rate_limits": {}})
    code, out, _ = _run(["statusline"], capsys, payload, monkeypatch)
    assert code == 0 and out.strip().startswith("Claude | orkestra: agy")


def test_the_status_line_survives_a_broken_config(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    (tmp_path / "orkestra-home" / "config.yaml").write_text("version: [", encoding="utf-8")
    code, out, _ = _run(["statusline"], capsys, "{}", monkeypatch)
    assert code == 0 and out.strip() == "Claude"


def test_the_hook_command_prints_its_context_once(
    project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    resets = int((db.local_now() + timedelta(hours=2)).timestamp())
    payload = json.dumps(
        {"rate_limits": {"five_hour": {"used_percentage": 92, "resets_at": resets}}}
    )
    _run(["statusline"], capsys, payload, monkeypatch)
    event = json.dumps({"hook_event_name": "UserPromptSubmit"})

    code, out, _ = _run(["statusline", "hook"], capsys, event, monkeypatch)
    assert code == 0
    assert "orkestra handoff update" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
    code, out, _ = _run(["statusline", "hook"], capsys, event, monkeypatch)
    assert code == 0 and out == ""


def test_the_config_command_prints_the_settings_snippet(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run(["--lang", "en", "statusline", "config"], capsys)
    assert code == 0
    assert json.loads(out)["statusLine"]["command"] == "orkestra statusline"
    assert "settings.json" in err


def test_doctor_warns_about_a_provider_running_low(project: Path) -> None:
    _use_runs(19)
    config = load_config(None).config
    checks = doctor._state_checks(config.providers, config.forecast)
    [check] = [c for c in checks if c.data.get("forecast")]
    assert check.status == "warn" and "runs 19/20" in check.message


def test_a_notification_names_providers_running_low() -> None:
    low = forecast.Forecast("agy", "daily_runs", 20, 19, False, 6.0, 600.0, True)
    message = notify.with_quota("3 finished", [], low=[low])
    assert message == "3 finished\nquota running low: agy: ~10 min (runs 19/20)"


def test_a_notification_without_warnings_is_only_the_counts() -> None:
    assert notify.with_quota("3 finished", [], low=[]) == "3 finished"


def test_limits_state_lives_under_orkestra_home(project: Path, tmp_path: Path) -> None:
    assert limits.state_path() == tmp_path / "orkestra-home" / "chief_quota.json"
