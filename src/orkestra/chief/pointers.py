"""``file:line`` pointers in a worker's answer, checked against the files (Faz 13i-b, D-090).

A worker may point at a line that does not exist (a guess, a miscount). Every pointer in the
answer is looked up: a valid one comes back with the line it names, so the chief sees what
it points at without opening the file; an invalid one is marked, so it is not trusted.
"""

from __future__ import annotations

import html
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

LINE_CHARS = 120
# A path whose extension starts with a letter (so "3.12:1" is not one), then :line[-line].
_POINTER = re.compile(r"(?<![\w/.\\-])((?:[\w.-]+[/\\])*[\w.-]+\.[A-Za-z]\w*):(\d+)(?:-(\d+))?")


@dataclass(frozen=True)
class Pointer:
    pointer: str
    valid: bool
    line: str | None  # the line it names, stripped and shortened


def check(
    answer: str, files: Mapping[str, list[str]], *, redact: Callable[[str], str] = str
) -> list[Pointer]:
    """Each distinct pointer in ``answer``, in order; ``files`` maps a path to its lines.
    ``redact`` masks keys in the line shown (the worker may point at one, D-091)."""
    by_name = {path.replace("\\", "/"): lines for path, lines in files.items()}
    found: list[Pointer] = []
    seen: set[str] = set()
    for match in _POINTER.finditer(answer):
        path = match[1].replace("\\", "/")
        first = int(match[2])
        shown = f"{path}:{first}" + (f"-{match[3]}" if match[3] else "")
        if shown in seen:
            continue
        seen.add(shown)
        lines = by_name.get(path) or _by_suffix(path, by_name)
        last = int(match[3]) if match[3] else first
        if lines is None or not 1 <= first <= last <= len(lines):
            found.append(Pointer(shown, False, None))
            continue
        found.append(Pointer(shown, True, _short(redact(lines[first - 1]))))
    return found


def _by_suffix(path: str, files: Mapping[str, list[str]]) -> list[str] | None:
    """``calc.py:2`` for ``src/calc.py``: only when exactly one file ends that way."""
    matches = [lines for name, lines in files.items() if name.endswith("/" + path)]
    return matches[0] if len(matches) == 1 else None


def _short(line: str) -> str:
    text = line.strip()
    return text if len(text) <= LINE_CHARS else text[: LINE_CHARS - 1] + "…"


def numbered(path: str, lines: list[str]) -> str:
    """A file as the worker sees it: its path, then each line with its number. As in task
    context (D-036), the path is escaped and a ``</file>`` inside cannot close the block."""
    safe = [line.replace("</file>", "<\\/file>") for line in lines]
    body = "\n".join(f"{n:>5}| {line}" for n, line in enumerate(safe, start=1))
    return f'<file path="{html.escape(path, quote=True)}">\n{body}\n</file>'


def lines(text: str) -> list[str]:
    """Lines as editors and grep count them: split on newlines only (``splitlines`` also
    splits on form feeds and other separators, which shifts every later line number)."""
    parts = text.replace("\r\n", "\n").split("\n")
    return parts[:-1] if parts and parts[-1] == "" else parts


def relative(path: Path, cwd: Path) -> str:
    """``path`` as the chief would type it from ``cwd`` (``../other/x.py``); only its name
    when it is on another drive: no absolute (home) path goes to a worker."""
    try:
        return os.path.relpath(path, cwd).replace("\\", "/")
    except ValueError:
        return path.name
