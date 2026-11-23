"""Faz 13r-c code review: ``orkestra tokens --compare`` fixes (D-138)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from test_token_compare import make_assistant, make_commit, make_transcript

from orkestra.chief import token_compare, tokens
from orkestra.cli import app

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    from conftest import git

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    return repo, tmp_path / "claude"


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    return (code if isinstance(code, int) else 0), _ANSI.sub("", captured.out), captured.err


def test_a_resumed_session_copying_old_messages_is_counted_once(tmp_path: Path) -> None:
    """Claude Code copies the earlier messages into the new file of a resumed session."""
    repo, home = _repo(tmp_path)
    make_commit(repo, "feat(faz-1a): x", "2026-11-20T10:00:00Z")
    first = [make_assistant("m1", "2026-11-20T09:00:00Z", inp=10, out=10)]
    make_transcript(home, repo, "s1", first)
    make_transcript(home, repo, "s2", [*first, make_assistant("m2", "2026-11-20T09:30:00Z")])

    report = token_compare.compare(project=repo, environ={"CLAUDE_CONFIG_DIR": str(home)})

    assert report.phases[0].requests == 2
    assert report.phases[0].raw_tokens == 40


def test_a_request_at_the_commit_second_belongs_to_that_commit(tmp_path: Path) -> None:
    repo, home = _repo(tmp_path)
    make_commit(repo, "feat(faz-1a): x", "2026-11-20T10:00:00Z")
    make_commit(repo, "feat(faz-1b): y", "2026-11-20T12:00:00Z")
    entries = [
        make_assistant("m1", "2026-11-20T10:00:00Z"),
        make_assistant("m2", "2026-11-20T10:00:00.500Z"),
        make_assistant("m3", "2026-11-20T12:00:00Z"),
    ]
    make_transcript(home, repo, "s1", entries)

    report = token_compare.compare(project=repo, environ={"CLAUDE_CONFIG_DIR": str(home)})

    assert [(r.phase, r.requests) for r in report.phases] == [("1a", 2), ("1b", 1)]


def test_a_broken_config_is_reported_not_swallowed(tmp_path: Path) -> None:
    repo, home = _repo(tmp_path)
    make_commit(repo, "feat(faz-1a): x", "2026-11-20T10:00:00Z")
    make_transcript(home, repo, "s1", [make_assistant("m1", "2026-11-20T09:00:00Z")])
    config = tmp_path / "orkestra.yaml"
    config.write_text("version: [unclosed\n", encoding="utf-8")

    report = token_compare.compare(
        project=repo, config_flag=config, environ={"CLAUDE_CONFIG_DIR": str(home)}
    )

    assert report.warnings
    assert report.warnings[0] in token_compare.render(report)
    assert token_compare.to_dict(report)["warnings"] == report.warnings


@pytest.mark.parametrize("extra", [["--session", "s1"], ["--top", "3"]])
def test_cli_conflict_is_one_json_error_document(
    tmp_path: Path, extra: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(["--lang", "en", "tokens", "--compare", *extra, "--json"], capsys)

    assert code == 2
    data: dict[str, Any] = json.loads(out)
    assert data["error"]["type"] == "UsageError"
    assert "--compare" in data["error"]["message"]


def test_cli_text_output_has_no_personal_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, home = _repo(tmp_path)
    make_commit(repo, "feat(faz-1a): x", "2026-11-20T10:00:00Z", {"a.txt": "1\n"})
    make_transcript(home, repo, "s1", [make_assistant("m1", "2026-11-20T09:00:00Z")])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.chdir(repo)

    code, out, err = _run(["--lang", "en", "tokens", "--compare"], capsys)

    assert code == 0, err
    assert "1a" in out and str(tmp_path) not in out
    assert tokens.project_folder(repo, home).name not in out


def test_a_hyphenated_sub_phase_is_its_own_phase(tmp_path: Path) -> None:
    """``feat(faz-13i-a): ...`` was ignored by the planned pattern."""
    repo, home = _repo(tmp_path)
    make_commit(repo, "feat(faz-13i-a): x", "2026-11-20T10:00:00Z")
    make_commit(repo, "fix(faz-13i-b): y", "2026-11-20T12:00:00Z")
    make_commit(repo, "fix(duzeltme-fable-a): z", "2026-11-20T13:00:00Z")
    entries = [
        make_assistant("m1", "2026-11-20T09:00:00Z"),
        make_assistant("m2", "2026-11-20T11:00:00Z"),
    ]
    make_transcript(home, repo, "s1", entries)

    report = token_compare.compare(project=repo, environ={"CLAUDE_CONFIG_DIR": str(home)})

    assert [(r.phase, r.requests) for r in report.phases] == [("13i-a", 1), ("13i-b", 1)]
