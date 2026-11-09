"""Collect context files for workers (Mimari §11, size and binary rules).

Binary files are skipped with a warning. Exceeding ``max_context_bytes`` is an error: context
is never cut silently. Files matched by the ignore file (``security.ignore_file``,
``.orkestraignore``) are never sent, not even when named explicitly; glob matches also skip
what ``.gitignore`` ignores, and ``.git/`` always. Only the ignore files in the base
directory are read (D-038). The secret scan runs on the result (``tasks/runner.py``).
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pathspec

from orkestra.errors import UsageError
from orkestra.i18n import t

BINARY_SNIFF_BYTES = 8192
GITIGNORE = ".gitignore"
_GLOB_CHARS = frozenset("*?[")


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


def expand_globs(globs: Sequence[str], base: Path) -> list[Path]:
    """Files matching the glob patterns under ``base``, sorted, ``.git/`` never included."""
    found: set[Path] = set()
    for pattern in globs:
        if Path(pattern).is_absolute():
            raise UsageError(t("context.error.glob_absolute", pattern=pattern))
        if not _GLOB_CHARS & set(pattern):
            found.add(base / pattern)
            continue
        found.update(
            p for p in base.glob(pattern) if p.is_file() and ".git" not in p.relative_to(base).parts
        )
    return sorted(found)


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
    explicit_specs = [(ignore_file, _ignore_spec(base, ignore_file))] if ignore_file else []
    glob_specs = [*explicit_specs, (GITIGNORE, _ignore_spec(base, GITIGNORE))]
    candidates = [(raw, explicit_specs) for raw in paths]
    candidates += [(p, glob_specs) for p in expand_globs(globs, base)]
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
