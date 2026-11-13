"""The handoff brief: rule based, redacted and never longer than its limit (Faz 10a)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orkestra.config.schema import Budget, Config, HandoffCfg, ModelSpec, OllamaProvider
from orkestra.handoff import brief, model
from orkestra.i18n import t
from orkestra.state import db
from orkestra.workspace.service import Unapplied

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
Git = Callable[[list[str], Path], tuple[bool, str]]


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "state.db")) as connection:
        yield connection


def _git_ok(
    *,
    branch: str = "main",
    status: str = "",
    log: str = "",
    count: str = "0",
    unknown_commit: bool = False,
) -> Git:
    def run(args: list[str], cwd: Path) -> tuple[bool, str]:
        if "--is-inside-work-tree" in args:
            return True, "true\n"
        if "rev-parse" in args:
            return True, branch + "\n"
        if "status" in args:
            return True, status
        if "log" in args:
            return True, log
        if "rev-list" in args:
            if unknown_commit:
                return False, "fatal: bad object abc123\n"
            return True, count + "\n"
        if "merge-base" in args:
            return True, ""
        return False, "unexpected git call"

    return run


def _document(tmp_path: Path, *, goal: str = "ship it", done: int = 0) -> Path:
    text = model.template("demo", "claude", NOW, "abc123")
    document = model.parse(text)
    model.set_section(document, "goal", goal)
    model.set_section(document, "status", "half done")
    model.set_section(document, "in_progress", "file: src/x.py | branch: faz-10a | next: tests")
    model.set_section(document, "open_questions", "does it work?")
    model.set_section(document, "watch_out", "Windows line endings")
    model.set_section(document, "done", "\n".join(f"- done {n}" for n in range(done)))
    model.set_section(document, "decisions", "- choose markdown")
    path = tmp_path / ".orkestra" / "HANDOFF.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.render(document), encoding="utf-8")
    return path


def _config(max_lines: int = 200, stale_after_commits: int = 5) -> Config:
    return Config(
        version=1,
        handoff=HandoffCfg(max_lines=max_lines, stale_after_commits=stale_after_commits),
    )


def _build(
    path: Path, config: Config, conn: sqlite3.Connection, *, limit: int = 60,
    git: Git | None = None, unapplied: list[Unapplied] | None = None,
    environ: dict[str, str] | None = None,
) -> str:  # fmt: skip
    config = config.model_copy(
        update={"handoff": config.handoff.model_copy(update={"brief_max_lines": limit})}
    )
    result = brief.build(
        config,
        conn,
        NOW,
        path=path,
        cwd=path.parent.parent,
        git=git or _git_ok(),
        unapplied=unapplied or [],
        environ=environ or {},
    )
    return result.text


def test_the_brief_never_exceeds_its_limit_even_with_huge_sections(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _document(tmp_path, goal="word " * 5000, done=200)
    text = _build(path, _config(), conn, limit=40)
    lines = text.splitlines()
    assert len(lines) <= 40
    assert lines[0] == t("handoff.brief.goal")
    assert lines[-1].startswith("... (")


def test_a_limit_of_ten_is_still_good(tmp_path: Path, conn: sqlite3.Connection) -> None:
    path = _document(tmp_path, goal="goal", done=5)
    text = _build(path, _config(), conn, limit=10)
    assert 0 < len(text.splitlines()) <= 10
    assert text.splitlines()[-1].startswith("... (")


def test_priority_puts_goal_and_status_before_the_lists(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _document(tmp_path, goal="the goal", done=30)
    text = _build(path, _config(), conn, limit=25)
    assert "the goal" in text
    assert "half done" in text
    assert text.index(t("handoff.brief.goal")) < text.index(t("handoff.brief.done"))
    assert text.index(t("handoff.brief.status")) < text.index(t("handoff.brief.done"))


def test_git_status_is_cut_to_fifteen_lines(tmp_path: Path, conn: sqlite3.Connection) -> None:
    path = _document(tmp_path)
    status = "".join(f"?? file-{n}.txt\n" for n in range(40))
    text = _build(path, _config(), conn, limit=200, git=_git_ok(status=status))
    assert sum(1 for line in text.splitlines() if "file-" in line) <= 15
    assert "file-39.txt" not in text


def test_a_non_git_directory_gets_a_note_and_does_not_crash(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _document(tmp_path)

    def no_git(args: list[str], cwd: Path) -> tuple[bool, str]:
        return False, "not a git repository"

    text = _build(path, _config(), conn, git=no_git)
    assert t("handoff.brief.no_git") in text
    # No git branch line; the ``branch:`` inside In progress is the chief's own text (D-066).
    branch_line = t("handoff.brief.branch", branch="")
    assert not any(line.startswith(branch_line) for line in text.splitlines())


def test_a_repository_without_commits_still_shows_its_branch(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _document(tmp_path)

    def unborn(args: list[str], cwd: Path) -> tuple[bool, str]:
        if "--is-inside-work-tree" in args:
            return True, "true\n"
        if "branch" in args:
            return True, "main\n"
        if "status" in args:
            return True, ""
        return False, "fatal: your current branch 'main' does not have any commits yet"

    text = _build(path, _config(), conn, git=unborn)
    assert t("handoff.brief.branch", branch="main") in text
    assert t("handoff.brief.no_git") not in text


def test_a_stale_file_gets_an_explicit_warning(tmp_path: Path, conn: sqlite3.Connection) -> None:
    path = _document(tmp_path)
    text = _build(path, _config(stale_after_commits=5), conn, git=_git_ok(count="6"))
    assert t("handoff.brief.stale", count=6) in text


def test_a_commit_that_is_not_in_history_gets_an_explicit_warning(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _document(tmp_path)
    text = _build(path, _config(stale_after_commits=5), conn, git=_git_ok(unknown_commit=True))
    assert t("handoff.brief.unknown_commit", commit="abc123") in text


def test_unapplied_runs_and_remaining_budget_are_listed(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _document(tmp_path)
    config = Config(
        version=1,
        handoff=HandoffCfg(max_lines=200, brief_max_lines=200),
        providers={
            "local": OllamaProvider(
                type="ollama",
                base_url="http://127.0.0.1:11434",
                budget=Budget(daily_requests=100),
                models=[ModelSpec(id="m", tier=1)],
            )
        },
    )
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO usage (provider, model, day, prompt_tokens, completion_tokens, "
            "cost_usd, requests, runs, estimated, kind, created_at) "
            "VALUES ('local', 'm', '2026-11-11', 1, 1, 0, 10, 0, 0, 'actual', ?)",
            (NOW.isoformat(),),
        )
    text = _build(
        path, config, conn, limit=200,
        unapplied=[Unapplied("20261111-120000-abcd", "fix", "changed one file")],
    )  # fmt: skip
    assert "20261111-120000-abcd" in text
    assert "changed one file" in text
    assert t("handoff.brief.budget", name="local", text="requests 90") in text


def test_the_chief_guide_is_included_when_there_is_room(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    text = _build(_document(tmp_path), _config(), conn, limit=200)
    assert t("handoff.brief.guide") in text
    assert "orkestra status --json" in text


def test_secrets_from_git_are_redacted(tmp_path: Path, conn: sqlite3.Connection) -> None:
    secret = "sk-or-v1-TESTKEY0123456789"
    text = _build(_document(tmp_path), _config(), conn, limit=200,
                  git=_git_ok(log=f"add {secret}\n"))  # fmt: skip
    assert secret not in text
    assert "***" in text


def test_only_the_last_five_done_items_are_shown(tmp_path: Path, conn: sqlite3.Connection) -> None:
    path = _document(tmp_path, done=20)
    text = _build(path, _config(), conn, limit=200)
    assert "done 19" in text
    assert "done 14" not in text


def test_the_brief_lists_the_last_five_commit_titles(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    log = "".join(f"commit number {n}\n" for n in range(8, 0, -1))
    text = _build(_document(tmp_path), _config(), conn, limit=200, git=_git_ok(log=log))
    assert t("handoff.brief.commits") in text
    assert "commit number 8" in text
    assert "commit number 1" not in text


def test_staleness_distinguishes_no_git_from_an_unknown_commit(tmp_path: Path) -> None:
    """GLM B4: a missing repository is not the same as a commit that is not in history."""
    document = model.parse(model.template("demo", "claude", NOW, "abc123"))
    config = _config()

    def no_git(args: list[str], cwd: Path) -> tuple[bool, str]:
        return False, "not a git repository"

    state = brief.staleness(document, config, tmp_path, no_git)
    assert state is not None
    assert state.no_git is True
    assert state.stale is False
    assert state.unknown_commit is False
    state = brief.staleness(document, config, tmp_path, _git_ok(unknown_commit=True))
    assert state is not None
    assert state.no_git is False
    assert state.unknown_commit is True


def test_no_git_means_one_note_and_no_unknown_commit_warning(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _document(tmp_path)

    def no_git(args: list[str], cwd: Path) -> tuple[bool, str]:
        return False, "not a git repository"

    text = _build(path, _config(), conn, git=no_git)
    assert text.count(t("handoff.brief.no_git")) == 1
    assert t("handoff.brief.unknown_commit", commit="abc123") not in text


def test_the_brief_survives_every_pressure_at_once(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    """GLM B6: huge sections, 40 dirty files and 50 unapplied runs under a limit of 10."""
    path = _document(tmp_path, goal="word " * 3000, done=200)
    status = "".join(f"?? file-{n}.txt\n" for n in range(40))
    runs = [Unapplied(f"20261111-1200{i:02d}-abcd", "fix", f"changed file {i}") for i in range(50)]
    text = _build(path, _config(), conn, limit=10, git=_git_ok(status=status), unapplied=runs)
    lines = text.splitlines()
    assert 0 < len(lines) <= 10
    assert lines[0] == t("handoff.brief.goal")
    assert lines[-1].startswith("... (")


# --- Claude review of Faz 10 (D-066) -----------------------------------------------------


def test_in_progress_is_in_the_brief_right_after_status(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    """The next step lives in ``In progress``; the next chief must see it (Mimari §17)."""
    text = _build(_document(tmp_path), _config(), conn, limit=200)
    lines = text.splitlines()
    assert "file: src/x.py | branch: faz-10a | next: tests" in lines
    status = lines.index(t("handoff.brief.status"))
    in_progress = lines.index(t("handoff.brief.in_progress"))
    open_questions = lines.index(t("handoff.brief.open_questions"))
    assert status < in_progress < open_questions


def _full_git(count: str) -> Git:
    status = "".join(f"?? file-{n}.txt\n" for n in range(40))
    log = "".join(f"commit {n}\n" for n in range(5))
    return _git_ok(status=status, log=log, count=count)


def test_a_full_brief_keeps_the_stale_warning_and_the_guide(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    """At the default 60 lines a busy project must not push the guide out of the brief."""
    goal = "\n".join(f"goal line {n}" for n in range(30))
    path = _document(tmp_path, goal=goal, done=30)
    text = _build(path, _config(stale_after_commits=5), conn, limit=60, git=_full_git("9"))
    lines = text.splitlines()
    assert len(lines) <= 60
    assert lines[0] == t("handoff.brief.goal")
    assert t("handoff.brief.stale", count=9) in lines
    assert t("handoff.brief.guide") in lines
    guide_last = (
        "- Never approve a provider or exceed a cost threshold without the user's permission."
    )
    assert lines[-2] == guide_last  # the whole guide fits, the cut is in the project content
    assert lines[-1].startswith("... (")


def test_a_tiny_limit_still_keeps_the_stale_warning(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _document(tmp_path, goal="\n".join(f"goal line {n}" for n in range(30)), done=5)
    text = _build(path, _config(stale_after_commits=5), conn, limit=10, git=_full_git("9"))
    lines = text.splitlines()
    assert len(lines) <= 10
    assert t("handoff.brief.stale", count=9) in lines
    assert lines[-1].startswith("... (")


def test_the_cut_count_covers_every_line_that_is_not_shown(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _document(tmp_path, goal="\n".join(f"goal line {n}" for n in range(30)), done=30)
    full = _build(path, _config(), conn, limit=10_000, git=_full_git("0")).splitlines()
    cut = _build(path, _config(), conn, limit=60, git=_full_git("0")).splitlines()
    marker = next(line for line in cut if line.startswith("... ("))
    shown = len(cut) - 1
    assert marker == t("handoff.brief.more", count=len(full) - shown)
