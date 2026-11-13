"""``orkestra handoff to`` and ``handoff install-hook`` end to end (Faz 10b)."""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from orkestra import paths
from orkestra.cli import app
from orkestra.handoff import launch
from orkestra.i18n import t
from orkestra.state import db

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_chief.py"


def _config(mode: str = "arg", *, program: str | None = None, args: list[str] | None = None) -> str:
    launch_line = ", ".join(
        json.dumps(part) for part in [program or sys.executable, *(args or [str(FIXTURE), mode])]
    )
    return f"""\
version: 1
chiefs:
  fake:
    launch: [{launch_line}]
    prompt_mode: {mode}
handoff:
  file: .orkestra/HANDOFF.md
  max_lines: 200
  brief_max_lines: 60
  stale_after_commits: 5
"""


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    return (
        (code if isinstance(code, int) else 0),
        _ANSI.sub("", captured.out),
        _ANSI.sub("", captured.err),
    )


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str) -> Path:
    home = paths.orkestra_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(config, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    monkeypatch.chdir(work)
    monkeypatch.delenv("ORKESTRA_CHIEF", raising=False)
    return work


def _git(repo: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }  # fmt: skip
    import os

    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=repo, capture_output=True,
        check=True, env={**os.environ, **env},
    )  # fmt: skip
    return done.stdout.decode("utf-8", errors="replace")


def _prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    *, mode: str = "arg",
) -> Path:  # fmt: skip
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _setup(tmp_path, monkeypatch, _config(mode))
    monkeypatch.chdir(repo)
    code, out, err = _run(["handoff", "init"], capsys)
    assert code == 0, err or out
    _git(repo, "add", "a.txt", ".orkestra/HANDOFF.md")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _rows() -> list[sqlite3.Row]:
    with closing(db.connect()) as conn:
        return list(conn.execute("SELECT * FROM handoffs ORDER BY id"))


def test_to_print_only_prints_the_brief_and_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _prepare(tmp_path, monkeypatch, capsys)
    capture = tmp_path / "captured.txt"
    monkeypatch.setenv("FAKE_CHIEF_OUT", str(capture))
    code, out, _ = _run(["handoff", "to", "fake", "--print-only"], capsys)
    assert code == 0
    code, shown, _ = _run(["handoff", "show", "--brief"], capsys)
    assert code == 0
    assert out == shown
    assert not capture.exists()
    assert _rows() == []


def test_to_starts_the_fake_chief_and_exits_with_its_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _prepare(tmp_path, monkeypatch, capsys)
    capture = tmp_path / "captured.txt"
    monkeypatch.setenv("FAKE_CHIEF_OUT", str(capture))
    monkeypatch.setenv("FAKE_CHIEF_EXIT", "3")
    code, brief_text, _ = _run(["handoff", "show", "--brief"], capsys)
    assert code == 0
    code, _, err = _run(["handoff", "to", "fake"], capsys)
    assert code == 3
    received = json.loads(capture.read_bytes().decode("utf-8"))
    assert received == [brief_text.strip()]
    assert t("handoff.to.starting", chief="fake", mode="arg") in err


def test_to_in_file_mode_writes_the_brief_the_chief_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    repo = _prepare(tmp_path, monkeypatch, capsys, mode="file")
    capture = tmp_path / "captured.txt"
    monkeypatch.setenv("FAKE_CHIEF_OUT", str(capture))
    code, brief_text, _ = _run(["handoff", "show", "--brief"], capsys)
    assert code == 0
    code, _, err = _run(["handoff", "to", "fake"], capsys)
    assert code == 0, err
    written = (repo / ".orkestra" / "BRIEF.md").read_bytes().decode("utf-8")
    assert written == brief_text.strip()
    assert capture.read_bytes().decode("utf-8") == brief_text.strip()
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["brief_path"] == str(repo / ".orkestra" / "BRIEF.md")


def test_to_with_a_missing_launcher_exits_2_and_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    repo = _prepare(tmp_path, monkeypatch, capsys)
    config = _config(program="not-installed-chief-xyz", args=[])
    (paths.orkestra_home() / "config.yaml").write_text(config, encoding="utf-8")
    capture = tmp_path / "captured.txt"
    monkeypatch.setenv("FAKE_CHIEF_OUT", str(capture))
    code, _, err = _run(["handoff", "to", "fake"], capsys)
    assert code == 2
    assert t("handoff.error.launch_missing", chief="fake",
             command="not-installed-chief-xyz") in err  # fmt: skip
    assert not capture.exists()
    assert not (repo / ".orkestra" / "BRIEF.md").exists()
    assert _rows() == []


def test_to_on_a_dirty_tree_exits_5_and_allow_dirty_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    repo = _prepare(tmp_path, monkeypatch, capsys)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    capture = tmp_path / "captured.txt"
    monkeypatch.setenv("FAKE_CHIEF_OUT", str(capture))
    code, _, err = _run(["handoff", "to", "fake"], capsys)
    assert code == 5
    assert t("handoff.error.dirty", count=1) in err
    assert not capture.exists()
    assert _rows() == []
    code, _, err = _run(["handoff", "to", "fake", "--allow-dirty"], capsys)
    assert code == 0, err
    assert capture.exists()
    assert len(_rows()) == 1


def test_the_handoff_row_records_the_writing_chief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _prepare(tmp_path, monkeypatch, capsys)
    monkeypatch.setenv("ORKESTRA_CHIEF", "codex")
    monkeypatch.setenv("FAKE_CHIEF_OUT", str(tmp_path / "captured.txt"))
    code, _, err = _run(["handoff", "to", "fake"], capsys)
    assert code == 0, err
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["from_chief"] == "codex"
    assert rows[0]["to_chief"] == "fake"


def test_to_with_an_unknown_chief_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _prepare(tmp_path, monkeypatch, capsys)
    code, _, err = _run(["handoff", "to", "nobody"], capsys)
    assert code == 2
    from orkestra.config import loader

    choices = ", ".join(sorted(loader.load_config(None).config.chiefs))
    assert t("handoff.error.unknown_chief", name="nobody", choices=choices) in err


def test_install_hook_creates_then_leaves_the_hook_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    repo = _prepare(tmp_path, monkeypatch, capsys)
    code, out, _ = _run(["handoff", "install-hook"], capsys)
    assert code == 0
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert hook.exists()
    assert t("handoff.hook.created", path=hook) in out
    assert launch.HOOK_MARKER_START in hook.read_text(encoding="utf-8")
    before = hook.read_bytes()
    code, out, _ = _run(["handoff", "install-hook"], capsys)
    assert code == 0
    assert t("handoff.hook.exists", path=hook) in out
    assert hook.read_bytes() == before


def test_install_hook_outside_a_repository_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch, _config())
    assert not (work / ".git").exists()
    code, _, err = _run(["handoff", "install-hook"], capsys)
    assert code == 2
    assert t("handoff.error.no_git") in err
