"""Worktrees in real temporary git repositories (Mimari §9, Faz 5b)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import git

from orkestra import paths
from orkestra.errors import UsageError, WorkspaceConflict
from orkestra.workspace import git_worktree as gw

MakeRepo = Callable[..., Path]

FILES = {
    "src/app.py": "def f():\n    return 1\n\n\ndef g():\n    return 2\n",
    "README.md": "# demo\n",
    "old.txt": "to be deleted\n",
    ".gitignore": "build/\n",
}


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _status(repo: Path) -> str:
    return git(repo, "status", "--porcelain=v1", "--untracked-files=all")


def _dirty(repo: Path) -> None:
    """Uncommitted work of every kind: unstaged, staged, deleted, untracked, ignored."""
    (repo / "README.md").write_bytes(b"# demo\nuser edit\n")
    (repo / "staged.txt").write_bytes(b"staged\n")
    git(repo, "add", "staged.txt")
    (repo / "old.txt").unlink()
    (repo / "notes").mkdir()
    (repo / "notes" / "todo.txt").write_bytes(b"untracked\n")
    (repo / "build").mkdir()
    (repo / "build" / "out.bin").write_bytes(b"ignored")


# --- create ----------------------------------------------------------------------------


def test_create_carries_the_dirty_tree_and_untracked_files(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    _dirty(repo)
    before = _status(repo)
    wt = gw.create(repo, "20261110-120000-abcd")
    assert wt.path.is_relative_to(paths.worktrees_dir())
    assert wt.repo == repo.resolve()
    assert _read(wt.path / "README.md") == "# demo\nuser edit\n"
    assert _read(wt.path / "staged.txt") == "staged\n"
    assert not (wt.path / "old.txt").exists()
    assert _read(wt.path / "notes" / "todo.txt") == "untracked\n"
    assert not (wt.path / "build").exists()  # ignored files stay behind
    assert git(wt.path, "status", "--porcelain") == ""  # all of it is in the baseline commit
    assert git(wt.path, "rev-parse", "HEAD").strip() == wt.baseline
    assert _status(repo) == before  # the user's repository is untouched
    assert git(repo, "rev-parse", "HEAD").strip() != wt.baseline


def test_create_needs_a_git_repository_with_a_commit(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(UsageError):
        gw.create(plain, "20261110-120000-abcd")
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q")
    with pytest.raises(UsageError):
        gw.create(empty, "20261110-120000-abcd")


def test_create_from_a_subdirectory_uses_the_repository_root(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    wt = gw.create(repo / "src", "20261110-120000-abcd")
    assert wt.repo == repo.resolve()
    assert (wt.path / "README.md").is_file()


def test_lfs_and_submodules_are_reported(make_repo: MakeRepo) -> None:
    repo = make_repo({**FILES, ".gitattributes": "*.psd filter=lfs diff=lfs merge=lfs -text\n"})
    wt = gw.create(repo, "20261110-120000-abcd")
    assert any("lfs" in w.lower() for w in wt.warnings)


# --- diff and reset --------------------------------------------------------------------


def _work(wt: gw.Worktree) -> None:
    (wt.path / "src" / "app.py").write_bytes(
        b"def f():\n    return 10\n\n\ndef g():\n    return 2\n"
    )
    (wt.path / "src" / "new.py").write_bytes(b"x = 1\n")
    (wt.path / "README.md").unlink()
    (wt.path / gw.INTERNAL_FILES[0]).write_bytes(b"prompt")


def test_diff_lists_changes_against_the_baseline(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    wt = gw.create(repo, "20261110-120000-abcd")
    _work(wt)
    change = gw.diff(wt)
    by_path = {c.path: c for c in change.files}
    assert set(by_path) == {"src/app.py", "src/new.py", "README.md"}
    assert (by_path["src/app.py"].insertions, by_path["src/app.py"].deletions) == (1, 1)
    assert by_path["src/new.py"].status == "A" and by_path["README.md"].status == "D"
    assert b"return 10" in change.patch
    assert gw.INTERNAL_FILES[0].encode() not in change.patch


def test_reset_restores_the_baseline(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    wt = gw.create(repo, "20261110-120000-abcd")
    _work(wt)
    gw.reset(wt)
    assert _read(wt.path / "src" / "app.py") == FILES["src/app.py"]
    assert (wt.path / "README.md").is_file()
    assert not (wt.path / "src" / "new.py").exists()
    assert gw.diff(wt).files == ()


def test_destructive_git_never_runs_in_the_main_repository(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    (repo / "README.md").write_bytes(b"precious uncommitted work\n")
    fake = gw.Worktree(repo=repo, path=repo, baseline="HEAD", run_id="x")
    with pytest.raises(gw.WorkspaceGuardError):
        gw.reset(fake)
    with pytest.raises(gw.WorkspaceGuardError):
        gw.remove(fake)
    assert _read(repo / "README.md") == "precious uncommitted work\n"


def test_guard_rejects_a_directory_that_only_looks_like_a_worktree(
    make_repo: MakeRepo,
) -> None:
    repo = make_repo(FILES)
    inside = paths.worktrees_dir() / "x" / "y"
    inside.mkdir(parents=True)
    with pytest.raises(gw.WorkspaceGuardError):
        gw.reset(gw.Worktree(repo=repo, path=inside, baseline="HEAD", run_id="y"))


# --- apply -----------------------------------------------------------------------------


def test_apply_keeps_the_users_uncommitted_work(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    _dirty(repo)
    wt = gw.create(repo, "20261110-120000-abcd")
    _work(wt)
    applied = gw.apply(wt)
    assert sorted(applied.files) == ["README.md", "src/app.py", "src/new.py"]
    assert "return 10" in _read(repo / "src" / "app.py")
    assert _read(repo / "src" / "new.py") == "x = 1\n"
    assert not (repo / "README.md").exists()
    # The user's own uncommitted changes are all still there, and nothing was staged.
    assert _read(repo / "staged.txt") == "staged\n"
    assert _read(repo / "notes" / "todo.txt") == "untracked\n"
    assert not (repo / "old.txt").exists()
    assert git(repo, "diff", "--cached", "--name-only").split() == ["staged.txt"]


def test_apply_merges_a_later_edit_to_another_part_of_the_file(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    wt = gw.create(repo, "20261110-120000-abcd")
    _work(wt)
    # After the run the user edits g() in the same file (unstaged).
    (repo / "src" / "app.py").write_bytes(b"def f():\n    return 1\n\n\ndef g():\n    return 20\n")
    gw.apply(wt)
    text = _read(repo / "src" / "app.py")
    assert "return 10" in text and "return 20" in text
    assert git(repo, "diff", "--cached", "--name-only") == ""


def test_overlapping_edit_is_a_conflict_and_nothing_is_written(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    wt = gw.create(repo, "20261110-120000-abcd")
    _work(wt)
    (repo / "src" / "app.py").write_bytes(b"def f():\n    return 99\n\n\ndef g():\n    return 2\n")
    before = {p: (repo / p).read_bytes() for p in ("src/app.py", "README.md")}
    with pytest.raises(WorkspaceConflict) as exc_info:
        gw.apply(wt)
    assert exc_info.value.exit_code == 5
    assert "src/app.py" in exc_info.value.details
    assert {p: (repo / p).read_bytes() for p in before} == before
    assert not (repo / "src" / "new.py").exists()  # all or nothing
    assert wt.path.is_dir()  # kept for the user to look at


def test_new_file_that_the_user_also_created_is_a_conflict(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    wt = gw.create(repo, "20261110-120000-abcd")
    _work(wt)
    (repo / "src" / "new.py").write_bytes(b"user's own\n")
    with pytest.raises(WorkspaceConflict) as exc_info:
        gw.apply(wt)
    assert "src/new.py" in exc_info.value.details
    assert _read(repo / "src" / "new.py") == "user's own\n"


def test_crlf_files_keep_their_line_endings(make_repo: MakeRepo) -> None:
    repo = make_repo({"win.txt": b"one\r\ntwo\r\nthree\r\n"})
    wt = gw.create(repo, "20261110-120000-abcd")
    (wt.path / "win.txt").write_bytes(b"one\r\nTWO\r\nthree\r\n")
    gw.apply(wt)
    assert (repo / "win.txt").read_bytes() == b"one\r\nTWO\r\nthree\r\n"


def test_autocrlf_repository(make_repo: MakeRepo) -> None:
    # As on a real Windows checkout with autocrlf: CRLF on disk, LF in the repository.
    repo = make_repo({"a.txt": b"one\r\ntwo\r\nthree\r\n"}, autocrlf="true")
    original = (repo / "a.txt").read_bytes()
    wt = gw.create(repo, "20261110-120000-abcd")
    content = (wt.path / "a.txt").read_bytes().replace(b"two", b"TWO")
    (wt.path / "a.txt").write_bytes(content)
    change = gw.diff(wt)
    assert [c.path for c in change.files] == ["a.txt"]
    gw.apply(wt)
    assert (repo / "a.txt").read_bytes() == original.replace(b"two", b"TWO")


# --- remove ----------------------------------------------------------------------------


def test_remove_deletes_the_worktree_and_its_registration(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    wt = gw.create(repo, "20261110-120000-abcd")
    _work(wt)
    gw.remove(wt)
    assert not wt.path.exists()
    assert str(wt.path.name) not in git(repo, "worktree", "list", "--porcelain")
    assert _status(repo) == ""  # the repository itself is still clean


def test_record_round_trip(make_repo: MakeRepo, tmp_path: Path) -> None:
    repo = make_repo(FILES)
    wt = gw.create(repo, "20261110-120000-abcd")
    gw.save_record(tmp_path / "run", wt)
    record = gw.load_record(tmp_path / "run")
    assert record is not None
    assert (record.worktree, record.state) == (wt, "active")
    gw.save_record(tmp_path / "run", wt, state="applied")
    loaded = gw.load_record(tmp_path / "run")
    assert loaded is not None and loaded.state == "applied"
    assert gw.load_record(tmp_path / "missing") is None


# --- code review fixes (PR #7) -----------------------------------------------------------


def _rmtree(path: Path) -> None:
    import os
    import shutil
    import stat

    def force(func: Callable[[str], object], target: str, _exc: object) -> None:
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onerror=force)


def test_user_diff_config_does_not_change_the_patches(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    for key, value in (
        ("diff.noprefix", "true"),
        ("diff.mnemonicPrefix", "true"),
        ("color.ui", "always"),
        ("diff.external", "no-such-diff-tool"),
        ("apply.whitespace", "error"),
    ):
        git(repo, "config", key, value)
    (repo / "README.md").write_bytes(b"# demo\nuser edit   \n")  # trailing whitespace
    wt = gw.create(repo, "20261110-120000-abcd")
    assert _read(wt.path / "README.md") == "# demo\nuser edit   \n"
    (wt.path / "src" / "app.py").write_bytes(b"def f():   \n    return 10\n")
    change = gw.diff(wt)
    assert b"\x1b[" not in change.patch and b"a/src/app.py" in change.patch
    gw.apply(wt, change)
    assert _read(repo / "src" / "app.py") == "def f():   \n    return 10\n"


def test_only_files_the_user_also_changed_are_reported_as_merged(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    wt = gw.create(repo, "20261110-120000-abcd")
    _work(wt)  # changes src/app.py, adds src/new.py, deletes README.md
    (repo / "src" / "app.py").write_bytes(b"def f():\n    return 1\n\n\ndef g():\n    return 20\n")
    applied = gw.apply(wt)
    assert sorted(applied.files) == ["README.md", "src/app.py", "src/new.py"]
    assert applied.merged == ("src/app.py",)


def test_remove_works_when_the_repository_is_gone(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    wt = gw.create(repo, "20261110-120000-abcd")
    _rmtree(repo)
    gw.remove(wt)
    assert not wt.path.exists()


def test_remove_path_unregisters_without_knowing_the_repository(make_repo: MakeRepo) -> None:
    repo = make_repo(FILES)
    wt = gw.create(repo, "20261110-120000-abcd")
    gw.remove_path(wt.path)
    assert not wt.path.exists()
    assert wt.path.name not in git(repo, "worktree", "list", "--porcelain")


def test_remove_path_deletes_a_half_created_directory(tmp_path: Path) -> None:
    half = paths.worktrees_dir() / "0000" / "20261110-120000-abcd"
    (half / "src").mkdir(parents=True)
    gw.remove_path(half)
    assert not half.exists()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(gw.WorkspaceGuardError):
        gw.remove_path(outside)
    assert outside.is_dir()


def test_git_timeout_message_is_translated(
    make_repo: MakeRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from orkestra import i18n
    from orkestra.errors import InternalError

    def slow(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired("git", gw.GIT_TIMEOUT_S)

    i18n.set_language("tr")
    monkeypatch.setattr(gw.subprocess, "run", slow)
    with pytest.raises(InternalError) as exc_info:
        gw.repo_root(Path.cwd())
    assert "timeout" not in str(exc_info.value)
    assert str(gw.GIT_TIMEOUT_S) in str(exc_info.value)


# --- manual test fixes (Faz 9b) ----------------------------------------------------------


def test_line_endings_alone_are_not_a_later_change(make_repo: MakeRepo) -> None:
    # autocrlf: the checkout form is CRLF, but a tool wrote the user's file with LF.
    repo = make_repo({"a.txt": b"one\r\ntwo\r\nthree\r\n"}, autocrlf="true")
    (repo / "a.txt").write_bytes(b"one\ntwo\nthree\n")
    wt = gw.create(repo, "20261110-120000-abcd")
    content = (wt.path / "a.txt").read_bytes().replace(b"two", b"TWO")
    (wt.path / "a.txt").write_bytes(content)
    applied = gw.apply(wt)
    assert applied.files == ("a.txt",)
    assert applied.merged == ()
    assert (repo / "a.txt").read_bytes().replace(b"\r\n", b"\n") == b"one\nTWO\nthree\n"


def test_a_real_later_change_is_still_merged_despite_line_endings(make_repo: MakeRepo) -> None:
    repo = make_repo({"a.txt": b"one\r\ntwo\r\nthree\r\n"}, autocrlf="true")
    wt = gw.create(repo, "20261110-120000-abcd")
    (repo / "a.txt").write_bytes(b"ONE\ntwo\nthree\n")  # the user edits, with LF
    content = (wt.path / "a.txt").read_bytes().replace(b"three", b"THREE")
    (wt.path / "a.txt").write_bytes(content)
    applied = gw.apply(wt)
    assert applied.merged == ("a.txt",)
    assert (repo / "a.txt").read_bytes().replace(b"\r\n", b"\n") == b"ONE\ntwo\nTHREE\n"


def test_removing_the_last_worktree_of_a_repository_removes_its_folder(
    make_repo: MakeRepo,
) -> None:
    repo = make_repo(FILES)
    first = gw.create(repo, "20261110-120000-abcd")
    second = gw.create(repo, "20261110-120001-abcd")
    gw.remove(first)
    assert second.path.parent.is_dir()  # another worktree of the repository is still there
    gw.remove(second)
    assert not second.path.parent.exists()
    assert paths.worktrees_dir().is_dir()


# --- code review fixes (PR #10, Faz 9b) ----------------------------------------------------


def test_a_line_ending_change_is_real_for_a_file_git_does_not_convert(
    make_repo: MakeRepo,
) -> None:
    # "-text": git keeps the bytes, so the user's CRLF -> LF conversion is a real change and
    # must survive the worker's edit instead of being silently reverted.
    repo = make_repo(
        {".gitattributes": "*.bat -text\n", "a.bat": b"one\r\ntwo\r\nthree\r\n"},
        autocrlf="true",
    )
    wt = gw.create(repo, "20261110-120000-abcd")
    (repo / "a.bat").write_bytes(b"one\ntwo\nthree\n")
    (wt.path / "a.bat").write_bytes(b"one\r\nTWO\r\nthree\r\n")
    applied = gw.apply(wt)
    assert applied.merged == ("a.bat",)
    assert (repo / "a.bat").read_bytes() == b"one\nTWO\nthree\n"


def test_a_mostly_lf_file_with_one_crlf_line_merges_without_a_conflict(
    make_repo: MakeRepo,
) -> None:
    repo = make_repo({"a.txt": b"one\r\ntwo\r\nthree\r\n"})  # stored with CRLF
    wt = gw.create(repo, "20261110-120000-abcd")
    (repo / "a.txt").write_bytes(b"ONE\ntwo\r\nthree\n")  # the user: mostly LF now
    (wt.path / "a.txt").write_bytes(b"one\r\ntwo\r\nTHREE\r\n")
    gw.apply(wt)
    assert (repo / "a.txt").read_bytes().replace(b"\r\n", b"\n") == b"ONE\ntwo\nTHREE\n"


def test_one_crlf_line_does_not_turn_the_whole_file_into_crlf(make_repo: MakeRepo) -> None:
    lines = [b"1", b"2", b"3", b"4", b"5", b"6", b"7", b"8"]
    repo = make_repo({"a.txt": b"\n".join(lines) + b"\n"})
    wt = gw.create(repo, "20261110-120000-abcd")
    # The user's line 4 sits in the worker's patch context, so the three-way merge runs.
    user = [*lines[:3], b"FOUR\r", *lines[4:]]
    (repo / "a.txt").write_bytes(b"\n".join(user) + b"\n")
    worker = [*lines[:6], b"SEVEN", lines[7]]
    (wt.path / "a.txt").write_bytes(b"\n".join(worker) + b"\n")
    applied = gw.apply(wt)
    assert applied.merged == ("a.txt",)
    merged = (repo / "a.txt").read_bytes()
    assert merged.replace(b"\r\n", b"\n") == b"1\n2\n3\nFOUR\n5\n6\nSEVEN\n8\n"
    assert merged.count(b"\r\n") <= 1


def test_the_repository_folder_goes_when_the_worktree_was_deleted_by_hand(
    make_repo: MakeRepo,
) -> None:
    repo = make_repo(FILES)
    wt = gw.create(repo, "20261110-120000-abcd")
    _rmtree(wt.path)
    gw.remove_path(wt.path)
    assert not wt.path.parent.exists()


def test_a_failed_create_leaves_no_empty_folder(
    make_repo: MakeRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orkestra.errors import InternalError

    repo = make_repo(FILES)
    real = gw._git

    def failing(args, cwd, **kwargs):  # type: ignore[no-untyped-def]
        if list(args[:2]) == ["worktree", "add"]:
            raise InternalError("worktree add failed")
        return real(args, cwd, **kwargs)

    monkeypatch.setattr(gw, "_git", failing)
    with pytest.raises(InternalError):
        gw.create(repo, "20261110-120000-abcd")
    assert not gw.worktree_path(repo, "20261110-120000-abcd").parent.exists()
