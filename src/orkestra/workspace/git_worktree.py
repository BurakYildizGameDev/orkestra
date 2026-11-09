"""Isolated git worktrees for edit tasks (Mimari §9).

A worker never touches the user's checkout. Each edit run gets a detached worktree under
``~/.orkestra/worktrees/<repo hash>/<run_id>`` that starts from the user's *current* state
(HEAD plus uncommitted changes plus untracked files), recorded as a "baseline" commit. The
worker's changes are the diff against that baseline.

Safety rules:
- every git command gets an explicit ``cwd``; there is no global ``chdir``;
- destructive commands (``reset --hard``, ``clean``, ``worktree remove``) only run through
  ``_destructive_git``, which refuses anything that is not a linked worktree under the
  worktrees directory, so they can never hit the user's repository;
- hooks never run (``core.hooksPath`` points to an empty directory);
- ``apply`` never touches the user's index and writes nothing unless the whole change fits:
  plain ``git apply`` first, then a per-file three-way merge (``git merge-file``); any
  conflict leaves the user's files as they were (D-040).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from orkestra import paths
from orkestra.errors import InternalError, UsageError, WorkspaceConflict
from orkestra.i18n import t
from orkestra.verify.base import FileChange

BASELINE_MESSAGE = "orkestra baseline"
IDENTITY = ("-c", "user.name=orkestra", "-c", "user.email=orkestra@localhost")
# Files Orkestra itself may put into a worktree; never part of the worker's change.
INTERNAL_FILES = (".orkestra_prompt.md",)
RECORD_FILE = "worktree.json"
GIT_TIMEOUT_S = 120

RecordState = Literal["active", "applied", "discarded"]


class WorkspaceGuardError(InternalError):
    """A destructive git command was about to run outside an Orkestra worktree (a bug)."""


@dataclass(frozen=True)
class Worktree:
    repo: Path  # the user's repository root
    path: Path  # the worktree
    baseline: str  # commit with the user's state at the start of the run
    run_id: str
    warnings: tuple[str, ...] = field(default=(), compare=False)


@dataclass(frozen=True)
class ChangeSet:
    patch: bytes  # binary diff against the baseline
    files: tuple[FileChange, ...]


@dataclass(frozen=True)
class ApplyResult:
    files: tuple[str, ...]
    merged: tuple[str, ...] = ()  # files that needed a three-way merge


@dataclass(frozen=True)
class Record:
    worktree: Worktree
    state: RecordState


# --- running git -----------------------------------------------------------------------


def _hooks_dir() -> Path:
    path = paths.worktrees_dir() / ".no-hooks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _git(
    args: Sequence[str], cwd: Path, *, stdin: bytes | None = None, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    command = [
        "git", "-c", f"core.hooksPath={_hooks_dir()}", "-c", "core.quotepath=false",
        "-c", "commit.gpgsign=false", *args,
    ]  # fmt: skip
    try:
        done = subprocess.run(  # no shell; cwd is always explicit
            command, cwd=cwd, input=stdin, capture_output=True, env=env,
            timeout=GIT_TIMEOUT_S, check=False,
        )  # fmt: skip
    except FileNotFoundError as exc:
        raise UsageError(t("workspace.error.no_git")) from exc
    except subprocess.TimeoutExpired as exc:
        raise InternalError(
            t("workspace.error.git", command=" ".join(args), detail="timeout")
        ) from exc
    if check and done.returncode != 0:
        detail = done.stderr.decode("utf-8", errors="replace").strip()[:500]
        raise InternalError(t("workspace.error.git", command=" ".join(args), detail=detail))
    return done


def _out(args: Sequence[str], cwd: Path) -> str:
    return _git(args, cwd).stdout.decode("utf-8", errors="replace").strip()


def _is_linked_worktree(path: Path) -> bool:
    """``path`` is the top of a linked worktree under the worktrees directory."""
    try:
        resolved = path.resolve()
        resolved.relative_to(paths.worktrees_dir().resolve())
    except (OSError, ValueError):
        return False
    if not (resolved / ".git").is_file():  # linked worktrees have a .git *file*
        return False
    done = _git(["rev-parse", "--show-toplevel", "--git-dir", "--git-common-dir"], resolved,
                check=False)  # fmt: skip
    if done.returncode != 0:
        return False
    top, git_dir, common = done.stdout.decode("utf-8").splitlines()[:3]
    same_top = Path(top).resolve() == resolved
    return same_top and Path(resolved, git_dir).resolve() != Path(resolved, common).resolve()


def _destructive_git(args: Sequence[str], worktree: Path) -> None:
    if not _is_linked_worktree(worktree):
        raise WorkspaceGuardError(t("workspace.error.guard", path=worktree))
    _git(args, worktree)


# --- create ----------------------------------------------------------------------------


def repo_root(path: Path) -> Path:
    done = _git(["rev-parse", "--show-toplevel"], path, check=False)
    if done.returncode != 0:
        raise UsageError(t("workspace.error.not_a_repo", path=path))
    return Path(done.stdout.decode("utf-8").strip()).resolve()


def worktree_path(repo: Path, run_id: str) -> Path:
    digest = hashlib.sha1(str(repo).encode("utf-8")).hexdigest()[:8]
    return paths.worktrees_dir() / digest / run_id


def _warnings(repo: Path) -> list[str]:
    warnings: list[str] = []
    if (repo / ".gitmodules").is_file():
        warnings.append(t("workspace.warning.submodules"))
    attributes = repo / ".gitattributes"
    if attributes.is_file() and "filter=lfs" in attributes.read_text("utf-8", errors="replace"):
        warnings.append(t("workspace.warning.lfs"))
    return warnings


def _copy_untracked(repo: Path, target: Path) -> None:
    listing = _git(["ls-files", "--others", "--exclude-standard", "-z"], repo).stdout
    for raw in filter(None, listing.split(b"\0")):
        rel = raw.decode("utf-8", errors="surrogateescape")
        source, dest = repo / rel, target / rel
        if not source.is_file() and not source.is_symlink():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest, follow_symlinks=False)


def create(path: Path, run_id: str) -> Worktree:
    """Worktree for ``run_id`` with the user's current state as the baseline commit."""
    repo = repo_root(path)
    if _git(["rev-parse", "--verify", "--quiet", "HEAD"], repo, check=False).returncode != 0:
        raise UsageError(t("workspace.error.no_commits", path=repo))
    target = worktree_path(repo, run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", "--detach", str(target), "HEAD"], repo)
    try:
        # Without this the worker would see the last commit, not the code on disk.
        snapshot = _git(["diff", "--binary", "HEAD"], repo).stdout
        if snapshot:
            _git(["apply", "--binary", "--whitespace=nowarn", "-"], target, stdin=snapshot)
        _copy_untracked(repo, target)
        _git(["add", "-A"], target)
        _git([*IDENTITY, "commit", "--allow-empty", "--no-verify", "-q", "-m", BASELINE_MESSAGE],
             target)  # fmt: skip
        baseline = _out(["rev-parse", "HEAD"], target)
    except BaseException:
        _git(["worktree", "remove", "--force", str(target)], repo, check=False)
        raise
    return Worktree(repo, target, baseline, run_id, tuple(_warnings(repo)))


# --- diff and reset --------------------------------------------------------------------

_EXCLUDES = tuple(f":(exclude){name}" for name in INTERNAL_FILES)


def _stage(wt: Worktree) -> None:
    _git(["add", "-A", "--", ".", *_EXCLUDES], wt.path)


def diff(wt: Worktree) -> ChangeSet:
    """The worker's change: everything in the worktree against the baseline."""
    _stage(wt)
    base = ["diff", "--cached", "--no-renames", wt.baseline]
    patch = _git([*base, "--binary", "--", ".", *_EXCLUDES], wt.path).stdout
    numstat = _git([*base, "--numstat", "-z", "--", ".", *_EXCLUDES], wt.path).stdout
    names = _git([*base, "--name-status", "-z", "--", ".", *_EXCLUDES], wt.path).stdout
    statuses = _pairs(names)
    files: list[FileChange] = []
    for entry in filter(None, numstat.split(b"\0")):
        added, deleted, rel = entry.decode("utf-8", errors="surrogateescape").split("\t", 2)
        files.append(
            FileChange(
                rel,
                insertions=int(added) if added.isdigit() else 0,  # "-" for binary files
                deletions=int(deleted) if deleted.isdigit() else 0,
                status=statuses.get(rel, "M"),
            )
        )
    return ChangeSet(patch, tuple(files))


def _pairs(name_status: bytes) -> dict[str, str]:
    parts = [p.decode("utf-8", errors="surrogateescape") for p in name_status.split(b"\0")]
    return {parts[i + 1]: parts[i][:1] for i in range(0, len(parts) - 1, 2) if parts[i]}


def reset(wt: Worktree) -> None:
    """Back to the baseline between attempts (inside the worktree only)."""
    _destructive_git(["reset", "-q", "--hard", wt.baseline], wt.path)
    _destructive_git(["clean", "-q", "-fdx"], wt.path)


# --- apply -----------------------------------------------------------------------------


def _blob(wt: Worktree, rev: str, rel: str) -> bytes | None:
    """File content at ``rev`` as it would be checked out (line endings included)."""
    done = _git(["cat-file", "--filters", f"{rev}:{rel}"], wt.path, check=False)
    return done.stdout if done.returncode == 0 else None


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


_CONFLICT = object()  # _merge result: the file cannot be merged


def _merge(base: bytes | None, ours: bytes | None, theirs: bytes | None, cwd: Path) -> object:
    """Three-way merge of one file (``None`` = the file is absent).

    Returns the merged content, ``None`` for "delete the file", or ``_CONFLICT``.
    """
    if ours == base:
        return theirs  # only the worker changed (or deleted) it
    if theirs in (ours, base):
        return ours  # same change on both sides, or only the user changed it
    if base is None or ours is None or theirs is None:
        return _CONFLICT  # created on both sides, or deleted on one side and edited on the other
    if b"\0" in base + ours + theirs:
        return _CONFLICT  # binary: no line merge
    scratch = paths.worktrees_dir() / ".merge"
    scratch.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for name, data in (("ours", ours), ("base", base), ("theirs", theirs)):
        file = scratch / f"{os.getpid()}-{name}"
        file.write_bytes(data)
        files.append(file)
    try:
        done = _git(["merge-file", "-p", *map(str, files)], cwd, check=False)
    finally:
        for file in files:
            file.unlink(missing_ok=True)
    return done.stdout if done.returncode == 0 else _CONFLICT


def _write(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.exists() else None
    path.write_bytes(content)
    if mode is not None:
        path.chmod(stat.S_IMODE(mode))


def apply(wt: Worktree, change: ChangeSet | None = None) -> ApplyResult:
    """Bring the worker's change into the user's working tree; the index is never touched.

    Raises ``WorkspaceConflict`` (exit code 5) listing the conflicting files; then nothing
    was written.
    """
    change = change if change is not None else diff(wt)
    files = tuple(c.path for c in change.files)
    if not change.patch:
        return ApplyResult(files)
    check = _git(["apply", "--check", "--binary", "-"], wt.repo, stdin=change.patch, check=False)
    if check.returncode == 0:
        _git(["apply", "--binary", "-"], wt.repo, stdin=change.patch)
        return ApplyResult(files)
    # The user changed some of these files after the run started: merge each file three
    # ways (baseline, the user's file now, the worker's file), all or nothing.
    results: dict[str, bytes | None] = {}
    conflicts: list[str] = []
    for rel in files:
        merged = _merge(
            _blob(wt, wt.baseline, rel), _read(wt.repo / rel), _read(wt.path / rel), wt.repo
        )
        if merged is _CONFLICT:
            conflicts.append(rel)
        else:
            results[rel] = merged if isinstance(merged, bytes) else None
    if conflicts:
        raise WorkspaceConflict(t("workspace.error.conflict", count=len(conflicts)),
                                details=conflicts)  # fmt: skip
    for rel, content in results.items():
        _write(wt.repo / rel, content)
    return ApplyResult(files, merged=files)


# --- remove ----------------------------------------------------------------------------


def remove(wt: Worktree) -> None:
    """Delete the worktree and unregister it from the repository."""
    if not wt.path.exists():
        _git(["worktree", "prune"], wt.repo, check=False)
        return
    if not _is_linked_worktree(wt.path):
        raise WorkspaceGuardError(t("workspace.error.guard", path=wt.path))
    done = _git(["worktree", "remove", "--force", str(wt.path)], wt.repo, check=False)
    if done.returncode != 0 or wt.path.exists():
        remove_directory(wt.path)
    _git(["worktree", "prune"], wt.repo, check=False)


def remove_directory(path: Path) -> None:
    """``rmtree`` for a directory under the worktrees directory (read-only files included)."""
    resolved = path.resolve()
    try:
        resolved.relative_to(paths.worktrees_dir().resolve())
    except ValueError as exc:
        raise WorkspaceGuardError(t("workspace.error.guard", path=path)) from exc

    def force(func: Callable[[str], object], target: str, _exc: object) -> None:
        os.chmod(target, stat.S_IWRITE)  # git marks object files read-only (Windows)
        func(target)

    shutil.rmtree(resolved, onerror=force)


# --- records ---------------------------------------------------------------------------


def save_record(run_dir: Path, wt: Worktree, state: RecordState = "active") -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "repo": str(wt.repo),
        "path": str(wt.path),
        "baseline": wt.baseline,
        "run_id": wt.run_id,
        "state": state,
    }
    (run_dir / RECORD_FILE).write_bytes(json.dumps(data, indent=2).encode("utf-8"))


def load_record(run_dir: Path) -> Record | None:
    try:
        data = json.loads((run_dir / RECORD_FILE).read_text(encoding="utf-8"))
        wt = Worktree(Path(data["repo"]), Path(data["path"]), data["baseline"], data["run_id"])
        state = data.get("state", "active")
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return Record(wt, state if state in ("active", "applied", "discarded") else "active")


def main_repo_of(worktree: Path) -> Path | None:
    """The repository a worktree belongs to (from its ``.git`` file), if it still exists."""
    done = _git(["rev-parse", "--git-common-dir"], worktree, check=False)
    if done.returncode != 0:
        return None
    common = Path(worktree, done.stdout.decode("utf-8").strip()).resolve()
    repo = common.parent
    return repo if repo.is_dir() else None
