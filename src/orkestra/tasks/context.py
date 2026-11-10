"""Collect context files for workers (Mimari §11, size and binary rules).

Binary files are skipped with a warning. Exceeding ``max_context_bytes`` is an error: context
is never cut silently. Ignore files and secret scanning arrive in later phases.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from orkestra.errors import UsageError
from orkestra.i18n import t

BINARY_SNIFF_BYTES = 8192


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


def collect_context(paths: Sequence[Path], *, max_bytes: int, cwd: Path | None = None) -> Context:
    """Read the context files. Sizes are checked before any file is read in full."""
    base = (Path.cwd() if cwd is None else cwd).resolve()
    found: list[tuple[Path, str, int]] = []
    skipped: list[str] = []
    seen: set[Path] = set()
    for raw in paths:
        path = (raw if raw.is_absolute() else base / raw).resolve()
        if path in seen:
            continue
        seen.add(path)
        display = _display(path, base)
        if not path.is_file():
            raise UsageError(t("context.error.not_found", path=raw))
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
    return Context(tuple(files), tuple(skipped))


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
