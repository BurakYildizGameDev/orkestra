"""Tests for orkestra tokens --compare (Faz 13r-c, item 6)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import git

from orkestra.chief import token_compare, tokens
from orkestra.errors import UsageError


def make_commit(
    repo: Path,
    message: str,
    date_str: str,
    files: dict[str, str] | None = None,
) -> None:
    """Commit at a fixed committer and author date."""
    if files:
        for rel_path, content in files.items():
            f = repo / rel_path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content, encoding="utf-8")
        git(repo, "add", "-A")
    old_cdate = os.environ.get("GIT_COMMITTER_DATE")
    old_adate = os.environ.get("GIT_AUTHOR_DATE")
    try:
        os.environ["GIT_COMMITTER_DATE"] = date_str
        os.environ["GIT_AUTHOR_DATE"] = date_str
        git(repo, "commit", "-q", "--allow-empty", "-m", message)
    finally:
        if old_cdate is not None:
            os.environ["GIT_COMMITTER_DATE"] = old_cdate
        else:
            os.environ.pop("GIT_COMMITTER_DATE", None)
        if old_adate is not None:
            os.environ["GIT_AUTHOR_DATE"] = old_adate
        else:
            os.environ.pop("GIT_AUTHOR_DATE", None)


def make_assistant(
    msg_id: str,
    timestamp: str | None,
    inp: int = 10,
    write: int = 0,
    read: int = 0,
    out: int = 10,
) -> dict[str, Any]:
    """Create an assistant entry with usage."""
    entry: dict[str, Any] = {
        "type": "assistant",
        "message": {
            "id": msg_id,
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "usage": {
                "input_tokens": inp,
                "cache_creation_input_tokens": write,
                "cache_read_input_tokens": read,
                "output_tokens": out,
            },
        },
    }
    if timestamp is not None:
        entry["timestamp"] = timestamp
    return entry


def make_transcript(
    home: Path,
    repo: Path,
    session_id: str,
    entries: list[dict[str, Any]],
    subagent_entries: dict[str, list[dict[str, Any]]] | None = None,
) -> Path:
    """Write Claude Code session and optional subagent transcripts."""
    proj_folder = tokens.project_folder(repo, home)
    proj_folder.mkdir(parents=True, exist_ok=True)
    session_file = proj_folder / f"{session_id}.jsonl"
    lines = [json.dumps(e) for e in entries]
    session_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if subagent_entries:
        sub_dir = proj_folder / session_id / "subagents"
        sub_dir.mkdir(parents=True, exist_ok=True)
        for sub_id, sub_ents in subagent_entries.items():
            sub_file = sub_dir / f"{sub_id}.jsonl"
            sub_lines = [json.dumps(e) for e in sub_ents]
            sub_file.write_text("\n".join(sub_lines) + "\n", encoding="utf-8")

    return session_file


def test_two_phase_commits_and_uncommitted(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    home = tmp_path / "claude"

    make_commit(repo, "feat(faz-1a): first", "2026-11-20T10:00:00Z", {"a.txt": "1\n2\n"})
    make_commit(repo, "feat(faz-1b): second", "2026-11-20T12:00:00Z", {"b.txt": "1\n2\n3\n"})

    entries = [
        make_assistant("m1", "2026-11-20T09:00:00Z", inp=10, out=10),
        make_assistant("m2", "2026-11-20T11:00:00Z", inp=20, out=20),
        make_assistant("m3", "2026-11-20T13:00:00Z", inp=30, out=30),
    ]
    make_transcript(home, repo, "s1", entries)

    report = token_compare.compare(
        project=repo,
        environ={"CLAUDE_CONFIG_DIR": str(home)},
    )

    assert len(report.phases) == 3
    p1, p2, uncommitted = report.phases

    assert p1.phase == "1a"
    assert p1.commits == 1
    assert p1.requests == 1
    assert p1.raw_tokens == 20
    assert p1.weighted == 60.0
    assert p1.added_lines == 2
    assert p1.weighted_per_1k_lines == 60.0 / 2 * 1000

    assert p2.phase == "1b"
    assert p2.commits == 1
    assert p2.requests == 1
    assert p2.raw_tokens == 40
    assert p2.weighted == 120.0
    assert p2.added_lines == 3
    assert p2.weighted_per_1k_lines == 120.0 / 3 * 1000

    assert uncommitted.phase == "uncommitted"
    assert uncommitted.commits == 0
    assert uncommitted.requests == 1
    assert uncommitted.raw_tokens == 60
    assert uncommitted.weighted == 180.0
    assert uncommitted.added_lines == 0
    assert uncommitted.weighted_per_1k_lines is None

    assert report.total.commits == 2
    assert report.total.requests == 3
    assert report.total.raw_tokens == 120
    assert report.total.weighted == 360.0
    assert report.total.added_lines == 5
    assert report.total.weighted_per_1k_lines == 360.0 / 5 * 1000
    assert report.skipped == 0


def test_duplicate_message_ids_count_once_with_last_usage(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    home = tmp_path / "claude"

    make_commit(repo, "feat(faz-1a): init", "2026-11-20T10:00:00Z")

    entries = [
        make_assistant("m1", "2026-11-20T09:00:00Z", inp=10, out=10),
        make_assistant("m1", "2026-11-20T09:00:00Z", inp=50, out=50),
    ]
    make_transcript(home, repo, "s1", entries)

    report = token_compare.compare(
        project=repo,
        environ={"CLAUDE_CONFIG_DIR": str(home)},
    )
    assert len(report.phases) == 1
    row = report.phases[0]
    assert row.requests == 1
    assert row.raw_tokens == 100
    assert row.weighted == 300.0


def test_subagent_transcript_requests_counted_in_right_phase(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    home = tmp_path / "claude"

    make_commit(repo, "feat(faz-1a): first", "2026-11-20T10:00:00Z")
    make_commit(repo, "feat(faz-1b): second", "2026-11-20T12:00:00Z")

    main_entries = [
        make_assistant("m1", "2026-11-20T09:00:00Z", inp=10, out=10),
    ]
    subagent_entries = {
        "sub1": [
            make_assistant("sub_m1", "2026-11-20T11:00:00Z", inp=20, out=20),
        ]
    }
    make_transcript(home, repo, "s1", main_entries, subagent_entries=subagent_entries)

    report = token_compare.compare(
        project=repo,
        environ={"CLAUDE_CONFIG_DIR": str(home)},
    )
    assert len(report.phases) == 2
    p1, p2 = report.phases
    assert p1.phase == "1a" and p1.requests == 1 and p1.raw_tokens == 20
    assert p2.phase == "1b" and p2.requests == 1 and p2.raw_tokens == 40


def test_non_phase_commit_is_not_a_boundary(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    home = tmp_path / "claude"

    make_commit(repo, "feat(faz-1a): first", "2026-11-20T10:00:00Z")
    make_commit(repo, "chore: intermediate cleanup", "2026-11-20T11:00:00Z")
    make_commit(repo, "feat(faz-1b): second", "2026-11-20T12:00:00Z")

    entries = [
        make_assistant("m1", "2026-11-20T10:30:00Z", inp=20, out=20),
    ]
    make_transcript(home, repo, "s1", entries)

    report = token_compare.compare(
        project=repo,
        environ={"CLAUDE_CONFIG_DIR": str(home)},
    )
    assert len(report.phases) == 2
    p1, p2 = report.phases
    assert p1.phase == "1a" and p1.requests == 0
    assert p2.phase == "1b" and p2.requests == 1


def test_added_lines_and_null_weighted_per_1k_when_zero(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    home = tmp_path / "claude"

    make_commit(
        repo,
        "feat(faz-1a): has added lines",
        "2026-11-20T10:00:00Z",
        {"code.py": "x = 1\ny = 2\n"},
    )
    make_commit(repo, "feat(faz-1b): zero added lines", "2026-11-20T12:00:00Z")

    entries = [
        make_assistant("m1", "2026-11-20T09:00:00Z", inp=10, out=10),
        make_assistant("m2", "2026-11-20T11:00:00Z", inp=20, out=20),
    ]
    make_transcript(home, repo, "s1", entries)

    report = token_compare.compare(
        project=repo,
        environ={"CLAUDE_CONFIG_DIR": str(home)},
    )
    assert len(report.phases) == 2
    p1, p2 = report.phases
    assert p1.added_lines == 2
    assert p1.weighted_per_1k_lines is not None
    assert p2.added_lines == 0
    assert p2.weighted_per_1k_lines is None


def test_since_drops_older_requests(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    home = tmp_path / "claude"

    make_commit(repo, "feat(faz-1a): past work", "2026-11-20T10:00:00Z")

    entries = [
        make_assistant("m_old", "2026-11-10T10:00:00Z", inp=10, out=10),
        make_assistant("m_recent", "2026-11-19T10:00:00Z", inp=20, out=20),
    ]
    make_transcript(home, repo, "s1", entries)

    fixed_now = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)
    report = token_compare.compare(
        project=repo,
        since="7d",
        environ={"CLAUDE_CONFIG_DIR": str(home)},
        now=fixed_now,
    )
    assert len(report.phases) == 1
    assert report.phases[0].requests == 1
    assert report.phases[0].raw_tokens == 40


def test_cli_tokens_compare_json_and_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from orkestra.cli import build_app

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    home = tmp_path / "claude"

    make_commit(repo, "feat(faz-1a): init", "2026-11-20T10:00:00Z", {"f.txt": "hello\n"})
    entries = [
        make_assistant("m1", "2026-11-20T09:00:00Z", inp=10, out=10),
    ]
    make_transcript(home, repo, "s1", entries)

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    runner = CliRunner()
    app = build_app()

    result = runner.invoke(app, ["tokens", "--compare", "--project", str(repo), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "phases" in data
    assert "total" in data
    assert "skipped" in data
    assert len(data["phases"]) == 1
    assert data["phases"][0]["phase"] == "1a"
    assert data["phases"][0]["commits"] == 1
    assert data["phases"][0]["added_lines"] == 1

    # Conflicts raise UsageError; the entry point turns it into exit code 2
    # (tests/unit/test_13r_c_review.py runs them through it).
    result_conflict_session = runner.invoke(app, ["tokens", "--compare", "--session", "s1"])
    assert isinstance(result_conflict_session.exception, UsageError)

    result_conflict_top = runner.invoke(app, ["tokens", "--compare", "--top", "5"])
    assert isinstance(result_conflict_top.exception, UsageError)


def test_entry_without_timestamp_increments_skipped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    home = tmp_path / "claude"

    make_commit(repo, "feat(faz-1a): init", "2026-11-20T10:00:00Z")

    entries = [
        make_assistant("m1", "2026-11-20T09:00:00Z", inp=10, out=10),
        make_assistant("m2", None, inp=20, out=20),
    ]
    make_transcript(home, repo, "s1", entries)

    report = token_compare.compare(
        project=repo,
        environ={"CLAUDE_CONFIG_DIR": str(home)},
    )
    assert report.skipped == 1
    assert len(report.phases) == 1
    assert report.phases[0].requests == 1


def test_not_a_git_repository_raises_usage_error(tmp_path: Path) -> None:
    not_repo = tmp_path / "not_repo"
    not_repo.mkdir()
    home = tmp_path / "claude"
    make_transcript(home, not_repo, "s1", [make_assistant("m1", "2026-11-20T09:00:00Z")])

    with pytest.raises(UsageError) as exc_info:
        token_compare.compare(
            project=not_repo,
            environ={"CLAUDE_CONFIG_DIR": str(home)},
        )
    assert exc_info.value.exit_code == 2


def test_no_transcripts_raises_usage_error(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    home = tmp_path / "claude"

    with pytest.raises(UsageError) as exc_info:
        token_compare.compare(
            project=repo,
            environ={"CLAUDE_CONFIG_DIR": str(home)},
        )
    assert exc_info.value.exit_code == 2


def test_render_table_format(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    home = tmp_path / "claude"

    make_commit(repo, "feat(faz-1a): init", "2026-11-20T10:00:00Z", {"a.txt": "1\n2\n"})
    entries = [
        make_assistant("m1", "2026-11-20T09:00:00Z", inp=10, out=10),
    ]
    make_transcript(home, repo, "s1", entries)

    report = token_compare.compare(
        project=repo,
        environ={"CLAUDE_CONFIG_DIR": str(home)},
    )
    rendered = token_compare.render(report)
    assert "Phase" in rendered
    assert "1a" in rendered
    assert "total" in rendered
