"""``file:line`` pointers in a worker's answer, checked against the files (Faz 13i-b, D-090).

A worker may point at a line that does not exist (a guess, a miscount). Every pointer in the
answer is looked up: a valid one comes back with the line it names, so the chief sees what
it points at without opening the file; an invalid one is marked, so it is not trusted.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

LINE_CHARS = 120
# A path whose extension starts with a letter (so "3.12:1" is not one), then :line[-line].
_POINTER = re.compile(r"(?<![\w/.\\-])((?:[\w.-]+[/\\])*[\w.-]+\.[A-Za-z]\w*):(\d+)(?:-(\d+))?")


@dataclass(frozen=True)
class Pointer:
    pointer: str
    valid: bool
    line: str | None  # the line it names, stripped and shortened


def check(answer: str, files: Mapping[str, list[str]]) -> list[Pointer]:
    """Each distinct pointer in ``answer``, in order; ``files`` maps a path to its lines."""
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
        found.append(Pointer(shown, True, _short(lines[first - 1])))
    return found


def _by_suffix(path: str, files: Mapping[str, list[str]]) -> list[str] | None:
    """``calc.py:2`` for ``src/calc.py``: only when exactly one file ends that way."""
    matches = [lines for name, lines in files.items() if name.endswith("/" + path)]
    return matches[0] if len(matches) == 1 else None


def _short(line: str) -> str:
    text = line.strip()
    return text if len(text) <= LINE_CHARS else text[: LINE_CHARS - 1] + "…"


def numbered(path: str, lines: list[str]) -> str:
    """A file as the worker sees it: its path, then each line with its number."""
    body = "\n".join(f"{n:>5}| {line}" for n, line in enumerate(lines, start=1))
    return f'<file path="{path}">\n{body}\n</file>'
