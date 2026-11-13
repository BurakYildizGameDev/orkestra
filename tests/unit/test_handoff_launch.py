"""Launching the next chief and the git hook (Faz 10b, Mimari §17 "Başlatma")."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest

from orkestra.config.schema import Chief, Config, HandoffCfg
from orkestra.errors import HandoffNotClean, UsageError
from orkestra.handoff import brief, launch, model
from orkestra.i18n import t
from orkestra.state import db

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
Git = Callable[[list[str], Path], tuple[bool, str]]
Spawn = Callable[[list[str], str | None], int]


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "state.db")) as connection:
        yield connection


def _config(mode: Literal["arg", "stdin", "file"] = "arg", *, program: str = "fakechief") -> Config:
    return Config(
        version=1,
        chiefs={"fake": Chief(launch=[program, "arg"], prompt_mode=mode)},
        handoff=HandoffCfg(),
    )


def _git(*, status: str = "", short: str = "abc123", root: Path | None = None) -> Git:
    def run(args: list[str], cwd: Path) -> tuple[bool, str]:
        if "--is-inside-work-tree" in args:
            return True, "true\n"
        if "--show-toplevel" in args:
            return True, f"{root or cwd}\n"
        if "--short" in args:
            return True, f"{short}\n"
        if "--abbrev-ref" in args:
            return True, "main\n"
        if "rev-list" in args:
            return True, "0\n"
        if "status" in args:
            return True, status
        if "log" in args:
            return True, ""
        return False, f"unexpected git call: {args}"

    return run


def _handoff(tmp_path: Path, *, goal: str = "ship it") -> Path:
    path = tmp_path / ".orkestra" / "HANDOFF.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = model.template("demo", "claude", NOW, "abc123")
    document = model.parse(text)
    model.set_section(document, "goal", goal)
    path.write_bytes(model.render(document).encode("utf-8"))
    return path


def _which(path: str = "C:/tools/fakechief.exe") -> Callable[[str], str | None]:
    return lambda command: path


def _spawn(recorded: list[tuple[list[str], str | None]], code: int = 0) -> Spawn:
    def run(argv: list[str], stdin_text: str | None) -> int:
        recorded.append((argv, stdin_text))
        return code

    return run


def _expected_brief(path: Path, config: Config, conn: sqlite3.Connection, tmp_path: Path) -> str:
    return brief.build(config, conn, NOW, path=path, cwd=tmp_path, git=_git()).text


def _rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM handoffs ORDER BY id"))


def test_arg_mode_gives_the_brief_as_the_last_argument(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _handoff(tmp_path)
    recorded: list[tuple[list[str], str | None]] = []
    result = launch.to(
        "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        which=_which(), spawn=_spawn(recorded), git=_git(root=tmp_path),
    )  # fmt: skip
    assert len(recorded) == 1
    argv, stdin_text = recorded[0]
    assert stdin_text is None
    assert argv[0] == "C:/tools/fakechief.exe"
    assert argv[1] == "arg"  # the configured extra argument stays before the brief
    assert argv[-1] == _expected_brief(path, _config(), conn, tmp_path)
    assert result.mode == "arg"
    assert result.brief_path is None


def test_stdin_mode_feeds_the_brief_on_stdin(tmp_path: Path, conn: sqlite3.Connection) -> None:
    path = _handoff(tmp_path)
    recorded: list[tuple[list[str], str | None]] = []
    result = launch.to(
        "fake", _config("stdin"), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        which=_which(), spawn=_spawn(recorded), git=_git(root=tmp_path),
    )  # fmt: skip
    argv, stdin_text = recorded[0]
    assert argv == ["C:/tools/fakechief.exe", "arg"]
    assert stdin_text == result.brief
    assert result.mode == "stdin"
    assert result.brief_path is None


def test_file_mode_writes_the_brief_and_gives_a_short_instruction(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _handoff(tmp_path)
    recorded: list[tuple[list[str], str | None]] = []
    result = launch.to(
        "fake", _config("file"), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        which=_which(), spawn=_spawn(recorded), git=_git(root=tmp_path),
    )  # fmt: skip
    brief_path = tmp_path / ".orkestra" / "BRIEF.md"
    assert brief_path.read_bytes().decode("utf-8") == result.brief
    assert result.brief_path == brief_path
    argv, stdin_text = recorded[0]
    assert stdin_text is None
    assert argv[-1] == launch.BRIEF_INSTRUCTION


def test_a_long_brief_falls_back_from_arg_to_file_with_a_warning(
    tmp_path: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    path = _handoff(tmp_path)
    recorded: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(launch, "ARG_MAX_CHARS", 10)
    result = launch.to(
        "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        which=_which(), spawn=_spawn(recorded), git=_git(root=tmp_path),
    )  # fmt: skip
    assert result.mode == "file"
    assert t("handoff.to.warning.long") in result.warnings
    assert (tmp_path / ".orkestra" / "BRIEF.md").exists()


def test_a_cmd_launcher_falls_back_to_file_mode(tmp_path: Path, conn: sqlite3.Connection) -> None:
    path = _handoff(tmp_path)
    recorded: list[tuple[list[str], str | None]] = []
    result = launch.to(
        "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        which=_which("C:/npm/fakechief.cmd"), spawn=_spawn(recorded), git=_git(root=tmp_path),
    )  # fmt: skip
    assert result.mode == "file"
    assert t("handoff.to.warning.cmd") in result.warnings
    assert recorded[0][0][-1] == launch.BRIEF_INSTRUCTION


def test_a_missing_launcher_is_a_usage_error_and_writes_nothing(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _handoff(tmp_path)
    with pytest.raises(UsageError) as exc_info:
        launch.to(
            "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
            which=lambda command: None, spawn=_spawn([]), git=_git(root=tmp_path),
        )  # fmt: skip
    assert exc_info.value.message == t(
        "handoff.error.launch_missing", chief="fake", command="fakechief"
    )
    assert not (tmp_path / ".orkestra" / "BRIEF.md").exists()
    assert _rows(conn) == []


def test_print_only_does_not_need_the_launcher_and_records_nothing(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _handoff(tmp_path)

    def must_not_spawn(argv: list[str], stdin_text: str | None) -> int:
        raise AssertionError("print-only started the chief")

    result = launch.to(
        "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        print_only=True, which=lambda command: None, spawn=must_not_spawn,
        git=_git(root=tmp_path),
    )  # fmt: skip
    assert result.brief == _expected_brief(path, _config(), conn, tmp_path)
    assert result.brief_path is None
    assert result.exit_code == 0
    assert _rows(conn) == []


def test_a_dirty_tree_stops_the_handoff_and_allow_dirty_continues(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _handoff(tmp_path)
    recorded: list[tuple[list[str], str | None]] = []
    with pytest.raises(HandoffNotClean) as exc_info:
        launch.to(
            "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
            which=_which(), spawn=_spawn(recorded), git=_git(status=" M a.txt\n", root=tmp_path),
        )  # fmt: skip
    assert exc_info.value.exit_code == 5
    assert exc_info.value.message == t("handoff.error.dirty", count=1)
    assert recorded == []
    assert _rows(conn) == []
    result = launch.to(
        "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        allow_dirty=True, which=_which(), spawn=_spawn(recorded),
        git=_git(status=" M a.txt\n", root=tmp_path),
    )  # fmt: skip
    assert result.exit_code == 0
    assert len(recorded) == 1


def test_the_brief_file_alone_does_not_make_the_tree_dirty(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _handoff(tmp_path)
    recorded: list[tuple[list[str], str | None]] = []
    launch.to(
        "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        which=_which(), spawn=_spawn(recorded),
        git=_git(status="?? .orkestra/BRIEF.md\n", root=tmp_path),
    )  # fmt: skip
    assert len(recorded) == 1


def test_the_handoff_row_has_every_field(tmp_path: Path, conn: sqlite3.Connection) -> None:
    path = _handoff(tmp_path)
    launch.to(
        "fake", _config("file"), conn, NOW, path=path, cwd=tmp_path, from_chief="codex",
        which=_which(), spawn=_spawn([]), git=_git(root=tmp_path),
    )  # fmt: skip
    rows = _rows(conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["from_chief"] == "codex"
    assert row["to_chief"] == "fake"
    assert row["at"] == NOW.isoformat()
    assert row["commit"] == "abc123"
    assert row["brief_path"] == str(tmp_path / ".orkestra" / "BRIEF.md")


def test_the_child_exit_code_becomes_the_result_exit_code(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _handoff(tmp_path)
    result = launch.to(
        "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        which=_which(), spawn=_spawn([], code=3), git=_git(root=tmp_path),
    )  # fmt: skip
    assert result.exit_code == 3


def test_the_record_is_written_before_the_chief_starts(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _handoff(tmp_path)
    seen: list[int] = []

    def spawn(argv: list[str], stdin_text: str | None) -> int:
        seen.append(len(_rows(conn)))  # the row must already be visible to the new chief
        return 0

    launch.to(
        "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        which=_which(), spawn=spawn, git=_git(root=tmp_path),
    )  # fmt: skip
    assert seen == [1]


def test_before_start_runs_with_the_final_mode_just_before_the_child(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _handoff(tmp_path)
    events: list[tuple[str, list[str]]] = []

    def before_start(mode: str, warnings: list[str]) -> None:
        assert len(_rows(conn)) == 1  # the row exists before the terminal changes hands
        events.append((mode, warnings))

    def spawn(argv: list[str], stdin_text: str | None) -> int:
        events.append(("spawn", []))
        return 0

    launch.to(
        "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        which=_which("C:/npm/fakechief.cmd"), spawn=spawn, git=_git(root=tmp_path),
        before_start=before_start,
    )  # fmt: skip
    assert events == [("file", [t("handoff.to.warning.cmd")]), ("spawn", [])]


def test_an_unknown_chief_is_a_usage_error(tmp_path: Path, conn: sqlite3.Connection) -> None:
    path = _handoff(tmp_path)
    with pytest.raises(UsageError) as exc_info:
        launch.to(
            "nobody", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
            which=_which(), spawn=_spawn([]), git=_git(root=tmp_path),
        )  # fmt: skip
    assert exc_info.value.message == t(
        "handoff.error.unknown_chief", name="nobody", choices=", ".join(sorted(_config().chiefs))
    )


def test_a_missing_handoff_file_is_a_usage_error(tmp_path: Path, conn: sqlite3.Connection) -> None:
    path = tmp_path / ".orkestra" / "HANDOFF.md"
    with pytest.raises(UsageError) as exc_info:
        launch.to(
            "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
            which=_which(), spawn=_spawn([]), git=_git(root=tmp_path),
        )  # fmt: skip
    assert exc_info.value.message == t("handoff.error.missing", path=path)


def test_the_unix_launch_uses_execvp_with_the_same_arguments() -> None:
    calls: list[tuple[str, list[str]]] = []

    def execvp(program: str, argv: list[str]) -> int:
        calls.append((program, argv))
        return 0

    code = launch.default_spawn(
        ["C:/tools/fakechief.exe", "arg", "the brief"], None, platform="posix", execvp=execvp
    )
    assert code == 0
    assert calls == [("C:/tools/fakechief.exe", ["C:/tools/fakechief.exe", "arg", "the brief"])]


# --- install-hook -----------------------------------------------------------------------


def _hooks_git(path: str = ".git/hooks") -> Git:
    def run(args: list[str], cwd: Path) -> tuple[bool, str]:
        if "rev-parse" in args and "--git-path" in args:
            return True, f"{path}\n"
        return False, f"unexpected git call: {args}"

    return run


def test_install_hook_without_a_repository_is_a_usage_error(tmp_path: Path) -> None:
    def no_git(args: list[str], cwd: Path) -> tuple[bool, str]:
        return False, "not a git repository"

    with pytest.raises(UsageError) as exc_info:
        launch.install_hook(tmp_path, git=no_git)
    assert exc_info.value.message == t("handoff.error.no_git")


def test_install_hook_creates_a_new_pre_commit_hook(tmp_path: Path) -> None:
    result = launch.install_hook(tmp_path, git=_hooks_git())
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    assert result.created is True
    assert result.updated is False
    text = hook.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert launch.HOOK_MARKER_START in text
    assert launch.HOOK_MARKER_END in text
    assert "orkestra handoff check --warn-only" in text
    assert "|| true" in text  # a missing or failing orkestra never blocks a commit


def test_install_hook_appends_to_an_existing_hook_and_keeps_its_content(tmp_path: Path) -> None:
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    existing = "#!/bin/sh\necho my own check\nexit 1\n"
    hook.write_text(existing, encoding="utf-8")
    result = launch.install_hook(tmp_path, git=_hooks_git())
    text = hook.read_text(encoding="utf-8")
    assert result.created is False
    assert result.updated is True
    assert text.startswith(existing)  # the old hook is not overwritten
    assert launch.HOOK_MARKER_START in text


def test_install_hook_twice_changes_nothing(tmp_path: Path) -> None:
    launch.install_hook(tmp_path, git=_hooks_git())
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    before = hook.read_bytes()
    result = launch.install_hook(tmp_path, git=_hooks_git())
    assert result.updated is False
    assert result.created is False
    assert hook.read_bytes() == before


def test_install_hook_uses_the_hooks_directory_git_reports(tmp_path: Path) -> None:
    worktree_hooks = tmp_path / "main" / ".git" / "worktrees" / "wt" / "hooks"
    launch.install_hook(tmp_path, git=_hooks_git(str(worktree_hooks)))
    assert (worktree_hooks / "pre-commit").exists()
    assert not (tmp_path / ".git").exists()


def test_install_hook_resolves_a_relative_hooks_directory_from_the_repository_root(
    tmp_path: Path,
) -> None:
    launch.install_hook(tmp_path, git=_hooks_git(".git/hooks"))
    assert (tmp_path / ".git" / "hooks" / "pre-commit").exists()


def test_install_hook_prints_a_json_ready_result(tmp_path: Path) -> None:
    result = launch.install_hook(tmp_path, git=_hooks_git())
    assert json.loads(json.dumps({"path": str(result.path), "created": result.created})) == {
        "path": str(tmp_path / ".git" / "hooks" / "pre-commit"),
        "created": True,
    }
