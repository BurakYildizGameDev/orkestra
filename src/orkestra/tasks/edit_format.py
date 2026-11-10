"""Full-file edits from API workers (Mimari §8.2).

Models break unified diffs, so an API worker answers with whole files::

    {"files": [{"path": "src/util.py", "content": "<the WHOLE file>"}], "note": "short summary"}

- ``parse``: code fences and prose around the JSON are fine; the first balanced ``{…}``
  object with a ``files`` key is taken. Anything else raises ``EditFormatError``, whose
  ``problem`` goes back to the worker as feedback (English) and into the envelope (user's
  language).
- ``check_paths``: every path is relative, has no ``..`` or ``.git`` part, stays inside the
  workdir (symlinks resolved), does not match a forbidden pattern, and is either a context
  file or a new file (when the task allows new files). An existing file the worker never saw
  is never overwritten.
- ``write``: keeps the original file's line endings (CRLF/LF) and UTF-8 BOM; a path that
  cannot be written is an ``EditFormatError`` too.
- ``cannot_do``: ``{"cannot_do": "<reason>"}``, the JSON form of ``CANNOT_DO: <reason>``.

SEARCH/REPLACE edits (Faz 9c; ``edit_format: auto`` picks them for files longer than
``security.max_api_edit_lines``): the worker sends only the places it changes::

    src/util.py
    <<<<<<< SEARCH
    <lines exactly as they are in the file>
    =======
    <the new lines>
    >>>>>>> REPLACE

- ``parse_replace``: blocks in order; fences and prose around them are fine (the prose is the
  note). A block without a path line reuses the previous block's path.
- ``paths_only``: one ``FileEdit`` per file, for ``check_paths`` before anything is read.
- ``resolve_replace``: applies the blocks to the files in memory and returns whole files, so
  ``write`` keeps line endings and BOM as for whole-file answers. A SEARCH matches whole lines
  exactly once (line endings ignored; a second pass also ignores trailing whitespace); an
  empty SEARCH creates a new file. Any block that does not fit is an ``EditFormatError`` and
  nothing of that answer is used.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import pathspec

from orkestra.errors import InternalError, ProviderBadOutput
from orkestra.i18n import t
from orkestra.verify.base import Message

FORMAT_CHECK = "edit_format"  # verification entry for answers that are not a valid edit
BOM = b"\xef\xbb\xbf"

__all__ = [
    "FORMAT_CHECK",
    "EditAnswer",
    "EditFormatError",
    "FileEdit",
    "Message",
    "ReplaceAnswer",
    "ReplaceBlock",
    "cannot_do",
    "check_paths",
    "normalize_path",
    "parse",
    "parse_replace",
    "paths_only",
    "resolve_replace",
    "write",
]


@dataclass(frozen=True)
class FileEdit:
    path: str  # as the worker wrote it; ``normalize_path`` makes it safe
    content: str


@dataclass(frozen=True)
class EditAnswer:
    files: tuple[FileEdit, ...]
    note: str = ""


class EditFormatError(ProviderBadOutput):
    """The answer is not a valid edit; ``problem`` is sent back to the worker."""

    def __init__(self, problem: Message) -> None:
        super().__init__(problem.user())
        self.problem = problem


# --- parse -----------------------------------------------------------------------------


def _objects(text: str) -> tuple[list[dict[str, Any]], str | None]:
    """Every balanced JSON object in ``text`` (strings may contain braces), and the first error."""
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    first_error: str | None = None
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError as exc:
            first_error = first_error or str(exc)
        else:
            if isinstance(value, dict):
                found.append(value)
        start = text.find("{", start + 1)
    return found, first_error


def cannot_do(text: str) -> str | None:
    """The reason of a JSON ``{"cannot_do": "<reason>"}`` answer (JSON mode has no plain text)."""
    objects, _ = _objects(text)
    for data in objects:
        for key, value in data.items():
            if key.lower() == "cannot_do":
                return str(value).strip()
    return None


def parse(text: str) -> EditAnswer:
    objects, first_error = _objects(text)
    data = next((o for o in objects if "files" in o), None)
    if data is None:
        if first_error is None:
            raise EditFormatError(Message("edit.error.no_json"))
        raise EditFormatError(Message("edit.error.bad_json", {"error": first_error}))
    files = data["files"]
    if not isinstance(files, list):
        raise EditFormatError(Message("edit.error.files_not_list"))
    edits: list[FileEdit] = []
    seen: dict[str, int] = {}
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise EditFormatError(Message("edit.error.file_shape", {"index": index}))
        path, content = item.get("path"), item.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            raise EditFormatError(Message("edit.error.file_shape", {"index": index}))
        key = normalize_path(path) or path
        if key in seen:
            raise EditFormatError(Message("edit.error.duplicate", {"path": key}))
        seen[key] = index
        edits.append(FileEdit(path, content))
    note = data.get("note")
    return EditAnswer(tuple(edits), note if isinstance(note, str) else "")


# --- SEARCH/REPLACE --------------------------------------------------------------------

_HEAD = re.compile(r"^\s*<{5,9}\s*SEARCH\s*$")
_DIVIDER = re.compile(r"^\s*={5,9}\s*$")
_TAIL = re.compile(r"^\s*>{5,9}\s*REPLACE\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
NOTE_CHARS = 300
HINT_LINES = 3  # lines shown around the closest match when a SEARCH is not found


@dataclass(frozen=True)
class ReplaceBlock:
    path: str  # as the worker wrote it; ``normalize_path`` makes it safe
    search: str  # LF line endings; empty: a new file
    replace: str
    index: int  # 1-based, for feedback
    # Other (search, replace) splits when the content itself has a "=======" line (a setext
    # title underline): the first split that matches the file exactly once is used.
    alternatives: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ReplaceAnswer:
    blocks: tuple[ReplaceBlock, ...]
    note: str = ""


_HEADER = re.compile(r"^#+\s*")  # "### src/a.py"
_LABEL = re.compile(r"^(?:file|path)\s*:\s*", re.IGNORECASE)  # "File: src/a.py"
_EXTENSION = re.compile(r"\.\w+$")


def _path_line(line: str, known: Collection[str]) -> str | None:
    """A file path on a line of its own, in the forms models write it.

    ``src/a.py``, `` `src/a.py` ``, ``**src/a.py**:``, ``### src/a.py``, ``File: src/a.py``.
    A path with spaces counts only when it is one of the ``known`` (editable) paths;
    otherwise a line with spaces is prose.
    """
    text = _HEADER.sub("", line.strip()).replace("`", "").replace("**", "")
    text = _LABEL.sub("", text.strip()).rstrip(":").strip()
    if not text:
        return None
    if text in known:
        return text
    if any(c.isspace() for c in text):
        return None
    return text if ("/" in text or "\\" in text or _EXTENSION.search(text)) else None


def _join(lines: list[str]) -> str:
    return "\n".join(lines) + "\n" if lines else ""


def _block_at(lines: list[str], head: int, path: str, index: int) -> tuple[ReplaceBlock, int]:
    """The block starting at the SEARCH marker ``head``, and the line index after it."""
    dividers: list[int] = []
    for i in range(head + 1, len(lines)):
        if _TAIL.match(lines[i]):
            if not dividers:
                break
            splits = [(_join(lines[head + 1 : d]), _join(lines[d + 1 : i])) for d in dividers]
            (search, replace), others = splits[0], tuple(splits[1:])
            return ReplaceBlock(path, search, replace, index, others), i + 1
        if _HEAD.match(lines[i]):
            break  # a new block before this one ended
        if _DIVIDER.match(lines[i]):
            dividers.append(i)
    raise EditFormatError(Message("edit.error.block_unterminated", {"index": index}))


def parse_replace(text: str, *, known: Collection[str] = ()) -> ReplaceAnswer:
    """``known``: the editable paths, so that a path with spaces is still seen as a path."""
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: list[ReplaceBlock] = []
    prose: list[str] = []
    path: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if _HEAD.match(line):
            index = len(blocks) + 1
            if path is None:
                raise EditFormatError(Message("edit.error.block_no_path", {"index": index}))
            block, i = _block_at(lines, i, path, index)
            blocks.append(block)
            continue
        if _TAIL.match(line):
            index = len(blocks) + 1
            raise EditFormatError(Message("edit.error.block_unterminated", {"index": index}))
        if not _FENCE.match(line) and not _DIVIDER.match(line) and line.strip():
            found = _path_line(line, known)
            if found is not None:
                path = found
            else:
                prose.append(line.strip())
        i += 1
    if not blocks:
        raise EditFormatError(Message("edit.error.no_blocks"))
    return ReplaceAnswer(tuple(blocks), " ".join(prose)[:NOTE_CHARS])


def paths_only(answer: ReplaceAnswer) -> EditAnswer:
    """One entry per file the blocks touch, for ``check_paths`` (contents are not read yet)."""
    seen = dict.fromkeys(normalize_path(b.path) or b.path for b in answer.blocks)
    return EditAnswer(tuple(FileEdit(path, "") for path in seen), answer.note)


def _lines(text: str) -> list[str]:
    """Lines with their ``\\n`` (only ``\\n`` ends a line, unlike ``str.splitlines``)."""
    return re.findall(r"[^\n]*\n|[^\n]+$", text)


def _windows(lines: list[str], search: list[str], key: Callable[[str], str]) -> list[int]:
    wanted = [key(s) for s in search]
    size = len(wanted)
    return [
        start
        for start in range(len(lines) - size + 1)
        if all(key(lines[start + j]) == wanted[j] for j in range(size))
    ]


def _closest(lines: list[str], search: list[str]) -> str:
    """The file's lines around the one most like the SEARCH's first non-blank line."""
    first = next((s.strip() for s in search if s.strip()), "")
    scores = [difflib.SequenceMatcher(None, first, line.strip()).ratio() for line in lines]
    if not first or not scores or max(scores) < 0.5:
        return "-"
    best = scores.index(max(scores))
    low, high = max(0, best - 1), min(len(lines), best + HINT_LINES)
    return "\n".join(f"{n + 1}: {lines[n].rstrip()}" for n in range(low, high))


def _matches(lines: list[str], search: list[str]) -> list[int]:
    """Where the SEARCH lines are: exactly, else apart from trailing whitespace."""
    starts = _windows(lines, search, lambda s: s.removesuffix("\n"))
    return starts or _windows(lines, search, str.rstrip)


def _apply_block(text: str, block: ReplaceBlock, rel: str) -> str:
    lines = _lines(text)
    # With "=======" inside the content there are several ways to split the block; the
    # longest SEARCH that matches exactly once is what the worker copied from the file.
    fits: list[tuple[int, int, str]] = []  # (search lines, start, replace)
    for search_text, replace_text in [(block.search, block.replace), *block.alternatives]:
        search = [line.removesuffix("\n") for line in _lines(search_text)]
        starts = _matches(lines, search) if search else []
        if len(starts) == 1:
            fits.append((len(search), starts[0], replace_text))
    if fits:
        size, start, replacement = max(fits, key=lambda fit: fit[0])
        end = start + size
        if replacement and not lines[end - 1].endswith("\n"):
            replacement = replacement.removesuffix("\n")  # the last line had no newline
        return "".join(lines[:start]) + replacement + "".join(lines[end:])
    # Nothing fits: explain with the first split, the one the worker most likely meant.
    search = [line.removesuffix("\n") for line in _lines(block.search)]
    params: dict[str, object] = {"path": rel, "index": block.index}
    if not search:
        raise EditFormatError(Message("edit.error.search_empty", params))
    starts = _matches(lines, search)
    if starts:
        params["count"] = len(starts)
        raise EditFormatError(Message("edit.error.search_ambiguous", params))
    params["closest"] = _closest(lines, search)
    raise EditFormatError(Message("edit.error.search_not_found", params))


def _read_text(target: Path, rel: str) -> str:
    try:
        raw = target.read_bytes()
    except OSError as exc:  # locked or no permission: feedback, not a crash
        detail = exc.strerror or type(exc).__name__
        raise EditFormatError(
            Message("edit.error.cannot_read", {"path": rel, "error": detail})
        ) from exc
    return raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")


def resolve_replace(answer: ReplaceAnswer, workdir: Path) -> EditAnswer:
    """Whole files after the blocks (paths already checked). Nothing is written here."""
    root = workdir.resolve()
    texts: dict[str, str] = {}
    for block in answer.blocks:
        rel = normalize_path(block.path)
        target = (root / rel).resolve() if rel is not None else None
        if rel is None or target is None or not target.is_relative_to(root):
            raise InternalError(t("workspace.error.guard", path=block.path))
        if rel not in texts:
            if target.is_dir():
                raise EditFormatError(Message("edit.error.not_a_file", {"path": rel}))
            if target.is_file():
                texts[rel] = _read_text(target, rel)
            elif block.search:
                raise EditFormatError(Message("edit.error.missing_file", {"path": rel}))
            else:
                texts[rel] = block.replace  # an empty SEARCH: the new file
                continue
        texts[rel] = _apply_block(texts[rel], block, rel)
    return EditAnswer(tuple(FileEdit(rel, text) for rel, text in texts.items()), answer.note)


# --- paths -----------------------------------------------------------------------------


def normalize_path(raw: str) -> str | None:
    """``a/b.py`` form of a safe relative path, or ``None`` when it is unsafe."""
    if not raw or "\0" in raw:
        return None
    windows = PureWindowsPath(raw)
    if windows.drive or windows.root or raw.startswith(("/", "\\")):
        return None  # absolute, drive-relative (C:x) or UNC
    parts = [p for p in raw.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." or p.lower() == ".git" for p in parts):
        return None
    return PurePosixPath(*parts).as_posix()


def check_paths(
    answer: EditAnswer,
    workdir: Path,
    *,
    editable: Collection[str],
    allow_new: bool,
    forbidden: Sequence[str],
    protected: Sequence[str] = (),
    ignored: Collection[str] = (),
) -> list[Message]:
    """Problems with the answer's paths (empty: it may be written)."""
    root = workdir.resolve()
    spec = pathspec.GitIgnoreSpec.from_lines(forbidden)
    guarded = pathspec.GitIgnoreSpec.from_lines(protected)
    problems: list[Message] = []
    for edit in answer.files:
        rel = normalize_path(edit.path)
        if rel is None:
            problems.append(Message("edit.error.unsafe_path", {"path": edit.path}))
            continue
        target = (root / rel).resolve()
        if not target.is_relative_to(root):  # a symlink pointing out of the workdir
            problems.append(Message("edit.error.unsafe_path", {"path": edit.path}))
        elif spec.match_file(rel):
            problems.append(Message("edit.error.forbidden", {"path": rel}))
        elif guarded.match_file(rel):
            problems.append(Message("edit.error.protected", {"path": rel}))
        elif rel in ignored:  # never part of the change: git does not see it
            problems.append(Message("edit.error.ignored", {"path": rel}))
        elif rel not in editable and (root / rel).exists():
            problems.append(Message("edit.error.not_in_context", {"path": rel}))
        elif rel not in editable and not allow_new:
            problems.append(Message("edit.error.no_new_files", {"path": rel}))
    return problems


# --- write -----------------------------------------------------------------------------


def _encode(content: str, original: bytes | None) -> bytes:
    data = content.replace("\r\n", "\n")
    if original is not None:
        if b"\r\n" in original:
            data = data.replace("\n", "\r\n")
        encoded = data.encode("utf-8")
        keep_bom = original.startswith(BOM) and not encoded.startswith(BOM)
        return BOM + encoded if keep_bom else encoded
    return content.encode("utf-8")  # a new file: as the worker wrote it


def write(answer: EditAnswer, workdir: Path) -> list[str]:
    """Write the files (paths already checked); returns their normalized paths."""
    root = workdir.resolve()
    written: list[str] = []
    for edit in answer.files:
        rel = normalize_path(edit.path)
        target = (root / rel).resolve() if rel is not None else None
        if rel is None or target is None or not target.is_relative_to(root):
            raise InternalError(t("workspace.error.guard", path=edit.path))
        try:
            original = target.read_bytes() if target.is_file() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_encode(edit.content, original))
        except OSError as exc:  # e.g. "a.py/b.py", or a name Windows does not allow
            detail = exc.strerror or type(exc).__name__
            raise EditFormatError(
                Message("edit.error.cannot_write", {"path": rel, "error": detail})
            ) from exc
        written.append(rel)
    return written
