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
