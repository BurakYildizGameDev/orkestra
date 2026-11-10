"""Collect context files for workers (Mimari §11, size and binary rules).

Binary files are skipped with a warning. Exceeding ``max_context_bytes`` is an error: context
is never cut silently. Files matched by the ignore file (``security.ignore_file``,
``.orkestraignore``) are never sent, not even when named explicitly; glob matches also skip
what ``.gitignore`` ignores, and ``.git/`` always. Only the ignore files in the base
directory are read (D-038). The secret scan runs on the result (``tasks/runner.py``).
"""

from __future__ import annotations

import glob
import html
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pathspec

from orkestra.errors import UsageError
from orkestra.i18n import t

BINARY_SNIFF_BYTES = 8192
GITIGNORE = ".gitignore"


@dataclass(frozen=True)
class ContextFile:
    path: Path
    display: str  # path shown to the worker, relative to cwd when possible
    text: str
    size: int


@dataclass(frozen=True)
class Context:
    files: tuple[ContextFile, ...] = ()
    skipped_binary: tuple[str, ...] = ()
    skipped_ignored: tuple[tuple[str, str], ...] = ()  # (path, ignore file that excluded it)

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)


def _display(path: Path, cwd: Path) -> str:
    try:
        return path.relative_to(cwd).as_posix()
    except ValueError:
        return path.as_posix()


def _is_binary(path: Path) -> bool:
    with path.open("rb") as stream:
        return b"\0" in stream.read(BINARY_SNIFF_BYTES)


def _ignore_spec(base: Path, name: str) -> pathspec.GitIgnoreSpec | None:
    path = base / name
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise UsageError(t("context.error.read", path=name, reason=exc)) from exc
    return pathspec.GitIgnoreSpec.from_lines(lines)


def _ignored_by(display: str, specs: Sequence[tuple[str, pathspec.GitIgnoreSpec | None]]) -> str:
    """Name of the ignore file that excludes ``display`` (a base-relative path), or ``""``."""
    if display.startswith("/") or display.startswith("../") or ":" in display:
        return ""  # outside the base directory: its ignore files do not apply
    for name, spec in specs:
        if spec is not None and spec.match_file(display):
            return name
    return ""


def glob_regex(pattern: str) -> re.Pattern[str]:
    """A glob pattern as a regex over ``/``-separated relative paths.

    ``**`` spans directories, ``*`` and ``?`` stay inside one, ``[...]`` is a character class.
    Hidden files match like any other (the ignore files decide what is left out).
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif char == "*":
            out.append("[^/]*")
            i += 1
        elif char == "?":
            out.append("[^/]")
            i += 1
        elif char == "[" and "]" in pattern[i + 1 :]:
            end = pattern.index("]", i + 1)
            body = pattern[i + 1 : end]
            out.append("[^" + body[1:] + "]" if body.startswith("!") else "[" + body + "]")
            i = end + 1
        else:
            out.append(re.escape(char))
            i += 1
    return re.compile("".join(out) + r"\Z")


def expand_globs(
    globs: Sequence[str],
    base: Path,
    specs: Sequence[tuple[str, pathspec.GitIgnoreSpec | None]] = (),
) -> list[Path]:
    """Files matching the glob patterns under ``base``, sorted.

    The walk never enters ``.git/`` or a directory the ignore ``specs`` exclude (``.venv/``,
    ``node_modules/``…), so a ``**`` pattern stays fast in a big repository.
    """
    found: set[Path] = set()
    patterns: list[re.Pattern[str]] = []
    for pattern in globs:
        if Path(pattern).is_absolute():
            raise UsageError(t("context.error.glob_absolute", pattern=pattern))
        if glob.has_magic(pattern):
            patterns.append(glob_regex(pattern.replace("\\", "/")))
        else:
            found.add(base / pattern)
    if patterns:
        for root, dirs, files in os.walk(base):
            rel = Path(root).relative_to(base).as_posix()
            prefix = "" if rel == "." else f"{rel}/"
            dirs[:] = sorted(
                d for d in dirs if d != ".git" and not _ignored_by(f"{prefix}{d}/", specs)
            )
            for name in files:
                path = f"{prefix}{name}"
                if any(p.match(path) for p in patterns):
                    found.add(base / path)
    return sorted(found)


def _specs(
    base: Path, ignore_file: str | None
) -> tuple[list[tuple[str, pathspec.GitIgnoreSpec | None]], ...]:
    """Ignore specs for listed files (the ignore file) and for globs (it plus .gitignore)."""
    explicit = [(ignore_file, _ignore_spec(base, ignore_file))] if ignore_file else []
    return explicit, [*explicit, (GITIGNORE, _ignore_spec(base, GITIGNORE))]


def glob_files(globs: Sequence[str], base: Path, ignore_file: str | None = None) -> list[Path]:
    """The files ``context.globs`` stands for, exactly as ``collect_context`` finds them."""
    root = base.resolve()
    return expand_globs(globs, root, _specs(root, ignore_file)[1])


def collect_context(
    paths: Sequence[Path],
    *,
    max_bytes: int,
    cwd: Path | None = None,
    globs: Sequence[str] = (),
    ignore_file: str | None = None,
) -> Context:
    """Read the context files. Sizes are checked before any file is read in full."""
    base = (Path.cwd() if cwd is None else cwd).resolve()
    explicit_specs, glob_specs = _specs(base, ignore_file)
    candidates = [(raw, explicit_specs) for raw in paths]
    candidates += [(p, glob_specs) for p in expand_globs(globs, base, glob_specs)]
    found: list[tuple[Path, str, int]] = []
    skipped: list[str] = []
    ignored: list[tuple[str, str]] = []
    seen: set[Path] = set()
    for raw, specs in candidates:
        path = (raw if raw.is_absolute() else base / raw).resolve()
        if path in seen:
            continue
        seen.add(path)
        display = _display(path, base)
        if not path.is_file():
            raise UsageError(t("context.error.not_found", path=raw))
        excluded_by = _ignored_by(display, specs)
        if excluded_by:
            ignored.append((display, excluded_by))
            continue
        try:
            if _is_binary(path):
                skipped.append(display)
                continue
            found.append((path, display, path.stat().st_size))
        except OSError as exc:
            raise UsageError(t("context.error.read", path=display, reason=exc)) from exc
    total = sum(size for _, _, size in found)
    if total > max_bytes:
        largest = sorted(found, key=lambda item: -item[2])
        raise UsageError(
            t("context.error.too_large", total=total, limit=max_bytes),
            details=[t("context.error.file_size", path=d, size=s) for _, d, s in largest],
        )
    files: list[ContextFile] = []
    for path, display, _ in found:
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise UsageError(t("context.error.read", path=display, reason=exc)) from exc
        text = data.decode("utf-8-sig", errors="replace")
        files.append(ContextFile(path, display, text, len(data)))
    return Context(tuple(files), tuple(skipped), tuple(ignored))


def render_context(context: Context) -> str:
    """``<file path="…">`` blocks (Mimari §8.1).

    The path is escaped as an attribute, and a ``</file>`` inside a file is written as
    ``<\\/file>`` so file content can never close its own block early (D-036).
    """
    blocks = []
    for f in context.files:
        text = f.text.replace("</file>", "<\\/file>")
        newline = "" if text.endswith("\n") else "\n"
        blocks.append(f'<file path="{html.escape(f.display, quote=True)}">\n{text}{newline}</file>')
    return "\n\n".join(blocks)
