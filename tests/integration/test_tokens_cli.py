"""``orkestra tokens`` end to end on a fake Claude Code home (Faz 13h): nothing is sent."""

from __future__ import annotations

import json
import re
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


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    work = tmp_path / "proj"
    work.mkdir()
    monkeypatch.chdir(work)
    entries = [
        {"type": "user", "cwd": str(work), "message": {"role": "user", "content": "go"}},
        {"type": "assistant", "version": "2.1.325", "message": {
            "id": "m1", "usage": {"input_tokens": 3, "cache_creation_input_tokens": 900,
                                  "cache_read_input_tokens": 0, "output_tokens": 40},
            "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                         "input": {"command": f"pytest {work / 'tests'}"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "F\n" * 400}]}},
        {"type": "assistant", "message": {
            "id": "m2", "usage": {"input_tokens": 3, "cache_creation_input_tokens": 300,
                                  "cache_read_input_tokens": 900, "output_tokens": 20},
            "content": [{"type": "text", "text": "done"}]}},
    ]  # fmt: skip
    folder = tokens.project_folder(work.resolve(), home)
    folder.mkdir(parents=True)
    (folder / "abc123.jsonl").write_bytes("\n".join(json.dumps(e) for e in entries).encode("utf-8"))
    return work


def test_tokens_reports_the_latest_session(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run(["--lang", "en", "tokens"], capsys)
    assert code == 0, err
    assert "Bash pytest ./tests" in out.replace("\\", "/")  # the folder as ".", any slash
    assert "2.1.325" in out and str(tmp_path) not in out

    code, out, _ = _run(["tokens", "--json", "--session", "abc", "--top", "1"], capsys)
    data = json.loads(out)
    assert data["sessions"][0]["id"] == "abc123" and len(data["top"]) == 1
    assert data["top"][0]["category"] == "command" and data["top"][0]["lines"] == 400
    assert data["total"]["output"] == 60
    assert str(tmp_path) not in out


def test_since_and_project_select_the_sessions(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    monkeypatch.chdir(tmp_path)
    code, out, _ = _run(["tokens", "--json", "--since", "7d", "--project", str(project)], capsys)
    assert code == 0 and len(json.loads(out)["sessions"]) == 1


def test_a_project_without_transcripts_is_exit_code_2(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    code, _, err = _run(["--lang", "en", "tokens"], capsys)
    assert code == 2 and "--project" in err
    code, _, _ = _run(["tokens", "--session", "zzz", "--project", str(project)], capsys)
    assert code == 2
    code, _, _ = _run(["tokens", "--since", "0d", "--project", str(project)], capsys)
    assert code == 2
