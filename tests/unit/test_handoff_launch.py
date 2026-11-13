"""Launching the next chief and the git hook (Faz 10b, Mimari §17 "Başlatma")."""

from __future__ import annotations

import json
import signal
import sqlite3
import subprocess
from collections.abc import Callable, Iterator, Mapping
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
Spawn = Callable[[list[str], str | None, Path, Mapping[str, str]], int]


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


def _spawn(
    recorded: list[tuple[list[str], str | None]], code: int = 0,
    context: list[tuple[Path, Mapping[str, str]]] | None = None,
) -> Spawn:  # fmt: skip
    def run(argv: list[str], stdin_text: str | None, cwd: Path, env: Mapping[str, str]) -> int:
        recorded.append((argv, stdin_text))
        if context is not None:
            context.append((cwd, env))
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

    def must_not_spawn(
        argv: list[str], stdin_text: str | None, cwd: Path, env: Mapping[str, str]
    ) -> int:
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
    assert exc_info.value.message == t("handoff.error.dirty", count=1, files="a.txt")
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

    def spawn(argv: list[str], stdin_text: str | None, cwd: Path, env: Mapping[str, str]) -> int:
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

    def spawn(argv: list[str], stdin_text: str | None, cwd: Path, env: Mapping[str, str]) -> int:
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


def test_the_unix_launch_uses_execvp_with_the_same_arguments(tmp_path: Path) -> None:
    calls: list[tuple[str, list[str], Mapping[str, str]]] = []
    chdirs: list[Path] = []

    def execvpe(program: str, argv: list[str], env: Mapping[str, str]) -> int:
        calls.append((program, argv, env))
        return 0

    code = launch.default_spawn(
        ["C:/tools/fakechief.exe", "arg", "the brief"], None, tmp_path,
        {"ORKESTRA_CHIEF": "fake"}, platform="posix", execvpe=execvpe, chdir=chdirs.append,
    )  # fmt: skip
    assert code == 0
    assert chdirs == [tmp_path]  # the new chief starts in the repository root (D-066)
    assert calls == [
        ("C:/tools/fakechief.exe", ["C:/tools/fakechief.exe", "arg", "the brief"],
         {"ORKESTRA_CHIEF": "fake"}),
    ]  # fmt: skip


def test_the_windows_launch_ignores_ctrl_c_while_the_child_runs(tmp_path: Path) -> None:
    """Ctrl+C belongs to the new chief; ``subprocess.run`` would kill it on KeyboardInterrupt."""
    seen: list[object] = []
    given: list[tuple[Path, Mapping[str, str]]] = []

    def runner(
        argv: list[str], *, input: bytes | None, check: bool, cwd: Path, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        seen.append(signal.getsignal(signal.SIGINT))
        given.append((cwd, env))
        return subprocess.CompletedProcess(argv, 4)

    before = signal.getsignal(signal.SIGINT)
    code = launch.default_spawn(
        ["C:/tools/fakechief.exe"], None, tmp_path, {"ORKESTRA_CHIEF": "fake"},
        platform="nt", runner=runner,
    )  # fmt: skip
    assert code == 4
    assert seen == [signal.SIG_IGN]
    assert signal.getsignal(signal.SIGINT) is before
    assert given == [(tmp_path, {"ORKESTRA_CHIEF": "fake"})]


def test_the_ctrl_c_handler_comes_back_when_the_child_fails_to_start(tmp_path: Path) -> None:
    def runner(
        argv: list[str], *, input: bytes | None, check: bool, cwd: Path, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        raise OSError("cannot start")

    before = signal.getsignal(signal.SIGINT)
    with pytest.raises(OSError):
        launch.default_spawn(["x"], None, tmp_path, {}, platform="nt", runner=runner)
    assert signal.getsignal(signal.SIGINT) is before


def test_the_chief_starts_in_the_repository_root_from_a_subfolder(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    """``file`` mode tells the chief a path relative to the root, so it must start there."""
    path = _handoff(tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    context: list[tuple[Path, Mapping[str, str]]] = []
    launch.to(
        "fake", _config("file"), conn, NOW, path=path, cwd=sub, from_chief="claude",
        which=_which(), spawn=_spawn([], context=context), git=_git(root=tmp_path),
    )  # fmt: skip
    assert context[0][0] == tmp_path
    assert (tmp_path / launch.BRIEF_RELATIVE).exists()
    assert not (sub / launch.BRIEF_RELATIVE).exists()


def test_the_new_chief_gets_its_own_name_in_orkestra_chief(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _handoff(tmp_path)
    context: list[tuple[Path, Mapping[str, str]]] = []
    launch.to(
        "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        which=_which(), spawn=_spawn([], context=context), git=_git(root=tmp_path),
        environ={"ORKESTRA_CHIEF": "claude", "KEEP_ME": "1"},
    )  # fmt: skip
    env = context[0][1]
    assert env["ORKESTRA_CHIEF"] == "fake"
    assert env["KEEP_ME"] == "1"


def test_the_handoff_file_and_its_archive_do_not_make_the_tree_dirty(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    """The usual flow is ``handoff update`` then ``handoff to``; that must not exit 5."""
    path = _handoff(tmp_path)
    recorded: list[tuple[list[str], str | None]] = []
    status = " M .orkestra/HANDOFF.md\n?? .orkestra/HANDOFF.archive.md\n?? .orkestra/BRIEF.md\n"
    launch.to(
        "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        which=_which(), spawn=_spawn(recorded), git=_git(status=status, root=tmp_path),
    )  # fmt: skip
    assert len(recorded) == 1


def test_the_dirty_error_names_the_changed_files(tmp_path: Path, conn: sqlite3.Connection) -> None:
    path = _handoff(tmp_path)
    status = ' M a.txt\n?? "notes/b c.txt"\n M .orkestra/HANDOFF.md\n'
    with pytest.raises(HandoffNotClean) as exc_info:
        launch.to(
            "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
            which=_which(), spawn=_spawn([]), git=_git(status=status, root=tmp_path),
        )  # fmt: skip
    assert exc_info.value.message == t("handoff.error.dirty", count=2, files="a.txt, notes/b c.txt")


def test_the_dirty_error_shortens_a_long_file_list(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    path = _handoff(tmp_path)
    status = "".join(f"?? f{n}.txt\n" for n in range(8))
    with pytest.raises(HandoffNotClean) as exc_info:
        launch.to(
            "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
            which=_which(), spawn=_spawn([]), git=_git(status=status, root=tmp_path),
        )  # fmt: skip
    files = t("handoff.error.dirty_more", files="f0.txt, f1.txt, f2.txt, f3.txt, f4.txt", count=3)
    assert exc_info.value.message == t("handoff.error.dirty", count=8, files=files)


def test_the_dirty_check_lists_untracked_files_one_by_one(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:  # fmt: skip
    """Without ``--untracked-files=all`` a new ``.orkestra/`` folder is one dirty line."""
    path = _handoff(tmp_path)
    calls: list[list[str]] = []
    inner = _git(root=tmp_path)

    def git(args: list[str], cwd: Path) -> tuple[bool, str]:
        calls.append(args)
        return inner(args, cwd)

    launch.to(
        "fake", _config(), conn, NOW, path=path, cwd=tmp_path, from_chief="claude",
        which=_which(), spawn=_spawn([]), git=git,
    )  # fmt: skip
    assert ["status", "--porcelain", "--untracked-files=all"] in calls


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
    assert text.replace(launch.HOOK_BLOCK, "") == existing  # the old hook is not overwritten
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


def test_install_hook_puts_the_block_right_after_the_shebang(tmp_path: Path) -> None:
    """An ``exit`` or ``exec`` at the end of the old hook must not skip the reminder."""
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\necho my own check\nexit 1\n", encoding="utf-8")
    launch.install_hook(tmp_path, git=_hooks_git())
    assert hook.read_text(encoding="utf-8") == (
        "#!/bin/sh\n" + launch.HOOK_BLOCK + "echo my own check\nexit 1\n"
    )


def test_install_hook_keeps_a_crlf_hook_crlf(tmp_path: Path) -> None:
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_bytes(b"#!/bin/sh\r\necho mine\r\n")
    launch.install_hook(tmp_path, git=_hooks_git())
    raw = hook.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert raw.startswith(b"#!/bin/sh\r\n# >>> orkestra handoff >>>\r\n")
    assert raw.endswith(b"echo mine\r\n")


@pytest.mark.parametrize(
    "first_line", ["#!/usr/bin/env python", "#!/usr/bin/node", "#!/usr/bin/env -S python3 -u", ""]
)
def test_install_hook_refuses_a_hook_that_is_not_a_shell_script(
    tmp_path: Path, first_line: str,
) -> None:  # fmt: skip
    """Shell lines added to a Python hook are a syntax error, and that blocks every commit."""
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text(f"{first_line}\nprint('mine')\n", encoding="utf-8")
    before = hook.read_bytes()
    with pytest.raises(UsageError) as exc_info:
        launch.install_hook(tmp_path, git=_hooks_git())
    assert exc_info.value.message == t(
        "handoff.error.hook_not_shell", path=hook, command=launch.HOOK_COMMAND
    )
    assert hook.read_bytes() == before


@pytest.mark.parametrize(
    "first_line", ["#!/bin/sh", "#!/bin/bash", "#!/usr/bin/env bash", "#! /bin/sh -e", "#!/bin/zsh"]
)
def test_install_hook_accepts_every_shell_hook(tmp_path: Path, first_line: str) -> None:
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text(f"{first_line}\necho mine\n", encoding="utf-8")
    result = launch.install_hook(tmp_path, git=_hooks_git())
    assert result.updated is True
    assert hook.read_text(encoding="utf-8").startswith(f"{first_line}\n{launch.HOOK_MARKER_START}")


def test_the_hook_does_not_hide_the_reminder() -> None:
    """The hook only reminds; sending the output to /dev/null would make it do nothing."""
    lines = [line.strip() for line in launch.HOOK_BLOCK.splitlines() if "handoff check" in line]
    assert lines == [f"{launch.HOOK_COMMAND} || true"]
    assert launch.HOOK_COMMAND == "orkestra handoff check --warn-only"
