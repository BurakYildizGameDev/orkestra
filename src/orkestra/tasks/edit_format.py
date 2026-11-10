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
- ``write``: keeps the original file's line endings (CRLF/LF) and UTF-8 BOM.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
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
    "check_paths",
    "normalize_path",
    "parse",
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


def _first_object(text: str) -> dict[str, Any]:
    """The first balanced JSON object with a ``files`` key; strings may contain braces."""
    decoder = json.JSONDecoder()
    first_error: str | None = None
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError as exc:
            first_error = first_error or str(exc)
        else:
            if isinstance(value, dict) and "files" in value:
                return value
        start = text.find("{", start + 1)
    if first_error is None:
        raise EditFormatError(Message("edit.error.no_json"))
    raise EditFormatError(Message("edit.error.bad_json", {"error": first_error}))


def parse(text: str) -> EditAnswer:
    data = _first_object(text)
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
) -> list[Message]:
    """Problems with the answer's paths (empty: it may be written)."""
    root = workdir.resolve()
    spec = pathspec.GitIgnoreSpec.from_lines(forbidden)
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
        original = target.read_bytes() if target.is_file() else None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_encode(edit.content, original))
        written.append(rel)
    return written
