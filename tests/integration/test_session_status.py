"""``status`` and ``tokens`` suggest a fresh session when the context is large (Faz 13j)."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from orkestra.chief import tokens
from orkestra.cli import app

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


def _transcript(home: Path, project: Path, *contexts: int) -> Path:
    entries = [
        {"type": "assistant", "version": "2.1.325", "message": {
            "id": f"m{n}", "content": [{"type": "text", "text": "x"}],
            "usage": {"input_tokens": 0, "cache_creation_input_tokens": 0,
                      "cache_read_input_tokens": c, "output_tokens": 10}}}
        for n, c in enumerate(contexts)
    ]  # fmt: skip
    folder = tokens.project_folder(project.resolve(), home)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "live.jsonl"
    path.write_bytes("\n".join(json.dumps(e) for e in entries).encode("utf-8"))
    return path


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(
        "version: 1\nhandoff:\n  suggest_at_tokens: 120000\n", encoding="utf-8"
    )
    folder = tmp_path / "proj"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder


def test_status_suggests_a_fresh_session_past_the_threshold(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _transcript(tmp_path / "claude-home", project, 47_000, 120_000, 180_000)
    code, out, _ = _run(["--lang", "en", "status"], capsys)
    assert code == 0
    assert "180,000" in out and "1,300,000" in out and "handoff" in out
    code, out, _ = _run(["status", "--json"], capsys)
    session = json.loads(out)["sections"]["session"]
    assert session["over"] is True and session["context"] == 180_000


def test_below_the_threshold_status_says_nothing_about_it(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _transcript(tmp_path / "claude-home", project, 47_000, 60_000)
    code, out, _ = _run(["--lang", "en", "status"], capsys)
    assert code == 0 and "fresh session" not in out
    code, out, _ = _run(["status", "--json"], capsys)
    assert json.loads(out)["sections"]["session"]["over"] is False


def test_an_old_session_is_not_the_current_one(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _transcript(tmp_path / "claude-home", project, 47_000, 300_000)
    old = time.time() - 24 * 3600
    os.utime(path, (old, old))
    _, out, _ = _run(["status", "--json"], capsys)
    assert "session" not in json.loads(out)["sections"]


def test_no_claude_code_no_session_line(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["status", "--json"], capsys)
    assert code == 0 and "session" not in json.loads(out)["sections"]


def test_tokens_shows_the_same_hint(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _transcript(tmp_path / "claude-home", project, 47_000, 120_000, 180_000)
    _, out, _ = _run(["tokens", "--json"], capsys)
    hint = json.loads(out)["handoff_hint"]
    assert hint["over"] is True and hint["saving_per_100"] == 1_300_000
