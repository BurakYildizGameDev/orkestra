"""File verifiers: change limits, protected and forbidden paths, required files (Mimari §10).

Changed files come from the task's workspace (edit tasks, Faz 5b/5c); an ``ask`` task changes
nothing, so the change checks pass trivially. Patterns use ``.gitignore`` syntax.
"""

from __future__ import annotations

import glob
from collections.abc import Sequence
from dataclasses import dataclass

import pathspec

from orkestra.verify.base import CheckResult, FileChange, Message, VerifyContext, failed, passed


def _matching(patterns: Sequence[str], changes: Sequence[FileChange]) -> list[str]:
    spec = pathspec.GitIgnoreSpec.from_lines(patterns)
    return [c.path for c in changes if spec.match_file(c.path)]


def _names(paths: Sequence[str]) -> str:
    return ", ".join(paths)


@dataclass(frozen=True)
class MaxChangedFilesCheck:
    value: int
    type: str = "max_changed_files"

    async def check(self, ctx: VerifyContext) -> CheckResult:
        count = len(ctx.changes)
        if count <= self.value:
            return passed(self.type)
        message = Message("verify.files.too_many", {"count": count, "limit": self.value})
        return failed(self.type, message)


@dataclass(frozen=True)
class MaxDiffLinesCheck:
    value: int
    type: str = "max_diff_lines"

    async def check(self, ctx: VerifyContext) -> CheckResult:
        lines = sum(c.insertions + c.deletions for c in ctx.changes)
        if lines <= self.value:
            return passed(self.type)
        return failed(
            self.type, Message("verify.files.too_many_lines", {"count": lines, "limit": self.value})
        )


@dataclass(frozen=True)
class PathsCheck:
    """``protect_paths`` and ``forbid_paths``: no changed file may match."""

    type: str
    paths: tuple[str, ...]

    async def check(self, ctx: VerifyContext) -> CheckResult:
        hits = _matching(self.paths, ctx.changes)
        if not hits:
            return passed(self.type)
        key = "verify.files.protected" if self.type == "protect_paths" else "verify.files.forbidden"
        return failed(self.type, Message(key, {"files": _names(hits)}))


@dataclass(frozen=True)
class FilesExistCheck:
    paths: tuple[str, ...]
    type: str = "files_exist"

    async def check(self, ctx: VerifyContext) -> CheckResult:
        missing = [p for p in self.paths if not _exists(ctx, p)]
        if not missing:
            return passed(self.type)
        return failed(self.type, Message("verify.files.missing", {"files": _names(missing)}))


def _exists(ctx: VerifyContext, path: str) -> bool:
    """Relative paths are under the workdir; absolute ones (and absolute globs) are allowed."""
    target = str(ctx.workdir / path)  # an absolute ``path`` replaces the workdir
    if glob.has_magic(path):
        return bool(glob.glob(target, recursive=True))
    return (ctx.workdir / path).exists()
