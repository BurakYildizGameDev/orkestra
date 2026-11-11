"""Unified diff parsing for the chief's review tools (Mimari §19, D-062).

A patch is split into one block per file. A block starts at ``diff --git`` or, for a plain
unified diff, at a ``--- `` line followed by ``+++ ``. Hunk bodies are counted from their
``@@ -a,b +c,d @@`` header, so a removed line that itself starts with ``-- `` (``--- …`` in
the diff) stays in its hunk.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_NO_NEWLINE = "\\"


@dataclass
class Hunk:
    header: str
    new_start: int
    lines: list[str] = field(default_factory=list)


@dataclass
class FilePatch:
    path: str
    header: list[str] = field(default_factory=list)
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def text(self) -> str:
        parts = list(self.header)
        for hunk in self.hunks:
            parts.append(hunk.header)
            parts.extend(hunk.lines)
        return "".join(parts)


def numbered(hunk: Hunk) -> Iterator[tuple[int, str]]:
    """Each body line with the new-file line number it is at (removed lines: the next one)."""
    line_no = hunk.new_start
    for line in hunk.lines:
        yield line_no, line
        if line[:1] in (" ", "+"):
            line_no += 1


def parse_patch(patch: str) -> list[FilePatch]:
    files: list[FilePatch] = []
    current: FilePatch | None = None
    old_left = new_left = 0  # body lines still expected in the current hunk
    lines = patch.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if old_left > 0 or new_left > 0:
            assert current is not None and current.hunks
            current.hunks[-1].lines.append(line)
            tag = line[:1]
            if tag in (" ", "-"):
                old_left -= 1
            if tag in (" ", "+"):
                new_left -= 1
            continue
        nxt = lines[index + 1] if index + 1 < len(lines) else ""
        starts_file = line.startswith("diff --git ") or (
            line.startswith("--- ")
            and nxt.startswith("+++ ")
            and (current is None or current.hunks or _has_file_headers(current))
        )
        if starts_file:
            current = FilePatch(path="")
            files.append(current)
        if current is None:  # text before any header: keep it as its own block
            current = FilePatch(path="")
            files.append(current)
        match = _HUNK.match(line)
        if match:
            old_left = int(match.group(1)) if match.group(1) is not None else 1
            new_left = int(match.group(3)) if match.group(3) is not None else 1
            current.hunks.append(Hunk(line, int(match.group(2))))
        elif line.startswith(_NO_NEWLINE) and current.hunks:
            current.hunks[-1].lines.append(line)
        else:
            current.header.append(line)
    for file in files:
        file.path = _path_of(file.header)
    return files


def _has_file_headers(file: FilePatch) -> bool:
    return any(line.startswith("+++ ") for line in file.header)


def _path_of(header: list[str]) -> str:
    """The file's path: ``+++ b/…`` (``--- a/…`` for a deletion), else the git header."""
    new = old = None
    for line in header:
        if line.startswith("+++ "):
            new = _header_path(line[4:])
        elif line.startswith("--- "):
            old = _header_path(line[4:])
    if new and new != "/dev/null":
        return _strip_prefix(new)
    if old and old != "/dev/null":
        return _strip_prefix(old)
    for line in header:
        if line.startswith("diff --git "):
            return _git_header_path(line.rstrip("\r\n")[len("diff --git ") :])
    return ""


def _header_path(raw: str) -> str:
    # git ends the name with a tab when it holds a space; quotes it when it is unusual.
    text = raw.rstrip("\r\n").removesuffix("\t")
    return _unquote(text) if text.startswith('"') else text


def _strip_prefix(path: str) -> str:
    return path[2:] if path.startswith(("a/", "b/")) else path


def _git_header_path(rest: str) -> str:
    if rest.startswith('"'):
        end = _quoted_end(rest)
        return _strip_prefix(_unquote(rest[: end + 1]))
    # ``a/<path> b/<path>`` with the same path twice (a rename has ---/+++ lines instead).
    size = (len(rest) - 1) // 2
    first, second = rest[:size], rest[size + 1 :]
    if first.startswith("a/") and second == "b/" + first[2:]:
        return first[2:]
    return _strip_prefix(rest.split(" ")[0])


def _quoted_end(text: str) -> int:
    index = 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == '"':
            return index
        index += 1
    return len(text) - 1


_ESCAPES = {"n": b"\n", "t": b"\t", '"': b'"', "\\": b"\\", "a": b"\a", "b": b"\b"}
_ESCAPES |= {"f": b"\f", "r": b"\r", "v": b"\v"}


def _unquote(text: str) -> str:
    """git's C-style quoted name: octal escapes are UTF-8 bytes."""
    body = text[1:-1] if text.endswith('"') and len(text) > 1 else text[1:]
    out = bytearray()
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            nxt = body[index + 1]
            octal = body[index + 1 : index + 4]
            if len(octal) == 3 and all(c in "01234567" for c in octal):
                out.append(int(octal, 8))
                index += 4
                continue
            out += _ESCAPES.get(nxt, nxt.encode("utf-8"))
            index += 2
            continue
        out += char.encode("utf-8")
        index += 1
    return out.decode("utf-8", errors="replace")
