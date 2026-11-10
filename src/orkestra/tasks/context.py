"""Collect context files for workers (Mimari §11, size and binary rules).

Binary files are skipped with a warning. Exceeding ``max_context_bytes`` is an error: context
is never cut silently. Ignore files and secret scanning arrive in later phases.
"""

from __future__ import annotations

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


def collect_context(paths: Sequence[Path], *, max_bytes: int, cwd: Path | None = None) -> Context:
    base = (Path.cwd() if cwd is None else cwd).resolve()
    files: list[ContextFile] = []
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
            data = path.read_bytes()
        except OSError as exc:
            raise UsageError(t("context.error.read", path=display, reason=exc)) from exc
        if b"\0" in data[:BINARY_SNIFF_BYTES]:
            skipped.append(display)
            continue
        text = data.decode("utf-8-sig", errors="replace")
        files.append(ContextFile(path, display, text, len(data)))
    context = Context(tuple(files), tuple(skipped))
    if context.total_bytes > max_bytes:
        largest = sorted(files, key=lambda f: -f.size)
        raise UsageError(
            t("context.error.too_large", total=context.total_bytes, limit=max_bytes),
            details=[t("context.error.file_size", path=f.display, size=f.size) for f in largest],
        )
    return context


def render_context(context: Context) -> str:
    """``<file path="…">`` blocks (Mimari §8.1)."""
    blocks = []
    for f in context.files:
        newline = "" if f.text.endswith("\n") else "\n"
        blocks.append(f'<file path="{f.display}">\n{f.text}{newline}</file>')
    return "\n\n".join(blocks)
