"""Repository map generator (Mimari §19).

Extracts model-free structural information (Python AST, heuristics for other files)
and 1-2 sentence purpose summaries using a local model.
Summaries are cached by SHA256 of file content in ``.orkestra/cache/map/<hash>.json``.
If no local provider is available under ``privacy: local_only``, remote models are NEVER
called; only structural information is generated.

After the code review (D-062): paths are relative to the current directory and must be
inside the project; one failed summary skips only that file; a file holding a key is
never sent; mapping some paths keeps the rest of the map (``index.json``).
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pathspec

from orkestra.chief.call import prompt_has_secrets, query_chief_model
from orkestra.config.loader import find_git_root
from orkestra.config.schema import Config
from orkestra.errors import ConsentRequired, NoProviderAvailable, ProviderError, UsageError
from orkestra.i18n import t
from orkestra.state import db
from orkestra.tasks.runner import ProviderSlots

MAP_FILE_NAME = "MAP.md"
MAP_CACHE_SUBDIR = Path(".orkestra") / "cache" / "map"
INDEX_FILE_NAME = "index.json"  # the last map's entries, for ``map <paths>`` (D-062)
MAX_FILE_CHARS_FOR_SUMMARY = 50_000
BINARY_CHECK_BYTES = 8192

_SYSTEM_PROMPT = (
    "You are an assistant creating a concise project map. "
    "Summarize the single purpose of this file in 1-2 direct sentences. "
    "Avoid preamble."
)

_GENERIC_PATTERNS = re.compile(
    r"^\s*(export\s+)?(default\s+)?(async\s+)?(function\s+\w+|class\s+\w+|def\s+\w+|fn\s+\w+|type\s+\w+|interface\s+\w+)",
    re.MULTILINE,
)

Progress = Callable[[int, int, str], None]  # (file number, file count, relative path)


@dataclass(frozen=True)
class FileMap:
    path: str  # relative path, forward slashes
    summary: str
    symbols: list[str] = field(default_factory=list)
    cached: bool = False


@dataclass(frozen=True)
class RepoMapResult:
    files: list[FileMap]  # the files mapped by this run
    total_files: int
    summarized_files: int
    cached_files: int
    model_used: str | None
    warnings: list[str] = field(default_factory=list)
    map_files: list[FileMap] = field(default_factory=list)  # everything MAP.md lists
    truncated: bool = False


@dataclass(frozen=True)
class Collected:
    files: list[Path]
    truncated: bool  # ``max_files`` left eligible files out


def project_root(cwd: Path) -> Path:
    """The project the map belongs to: the git root, else ``cwd`` (``map``, ``cache clear``)."""
    return (find_git_root(cwd) or cwd).resolve()


def hash_content(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_map_cache_dir(project_root: Path) -> Path:
    return project_root / MAP_CACHE_SUBDIR


def get_cached_summary(content_hash: str, *, cache_dir: Path) -> str | None:
    """The cached summary; a missing or unreadable entry is a miss (it is asked again)."""
    cache_file = cache_dir / f"{content_hash}.json"
    if not cache_file.is_file():
        return None
    try:
        data = json.loads(cache_file.read_bytes())
    except (OSError, ValueError):
        return None
    summary = data.get("summary") if isinstance(data, dict) else None
    return summary if isinstance(summary, str) and summary.strip() else None


def save_cached_summary(content_hash: str, summary: str, rel_path: str, *, cache_dir: Path) -> None:
    data = {"hash": content_hash, "path": rel_path, "summary": summary}
    _write_json(cache_dir / f"{content_hash}.json", data)


def _write_json(path: Path, data: object) -> None:
    """Atomic; the map works without its cache, so a failed write only loses the entry."""
    tmp_file = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_file.write_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        os.replace(tmp_file, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp_file.unlink()


def clear_cache(project_root: Path) -> int:
    """Clear map cache files in ``.orkestra/cache/map/``; returns number of removed entries."""
    cache_dir = get_map_cache_dir(project_root)
    removed = 0
    if cache_dir.is_dir():
        for path in cache_dir.glob("*.json"):
            with contextlib.suppress(OSError):
                path.unlink()
                removed += 1
    return removed


def extract_python_symbols(code: str) -> list[str]:
    """Extract top-level functions and classes with their methods using AST."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []

    symbols: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(_signature(node))
        elif isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            bases_str = f"({', '.join(bases)})" if bases else ""
            symbols.append(f"class {node.name}{bases_str}")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(f"  {_signature(item)}")
    return symbols


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix}{node.name}({ast.unparse(node.args)}){ret}"


def extract_generic_symbols(code: str, filename: str) -> list[str]:
    """Heuristic symbol extraction for non-Python files."""
    symbols: list[str] = []
    for line in code.splitlines()[:300]:
        if _GENERIC_PATTERNS.search(line):
            clean = line.strip().rstrip("{;").strip()
            if clean and len(clean) < 120:
                symbols.append(clean)
        if len(symbols) >= 15:
            break
    return symbols


def is_binary_content(data: bytes) -> bool:
    return b"\x00" in data[:BINARY_CHECK_BYTES]


def _is_binary_file(path: Path) -> bool | None:
    """``None`` when the file cannot be read."""
    try:
        with path.open("rb") as handle:
            return is_binary_content(handle.read(BINARY_CHECK_BYTES))
    except OSError:
        return None


def _load_spec(root: Path, filename: str) -> pathspec.PathSpec | None:
    path = root / filename
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


_IGNORED_DIRS = {
    ".git",
    ".orkestra",
    "__pycache__",
    ".venv",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
}


def resolve_paths(root: Path, paths: Sequence[Path], cwd: Path) -> list[Path]:
    """Absolute paths inside ``root``; relative ones are relative to ``cwd`` (exit code 2
    for a missing path or one outside the project)."""
    resolved: list[Path] = []
    for raw in paths:
        path = (raw if raw.is_absolute() else cwd / raw).resolve()
        if not path.exists():
            raise UsageError(t("map.error.not_found", path=str(raw)))
        if not path.is_relative_to(root):
            raise UsageError(t("map.error.outside_root", path=str(raw)))
        resolved.append(path)
    return resolved


def collect_repo_files(
    root: Path,
    paths: Sequence[Path] | None = None,
    ignore_file: str = ".orkestraignore",
    max_files: int | None = None,
) -> Collected:
    """Non-ignored, non-binary files under ``root`` (or under ``paths``, already resolved
    with ``resolve_paths``), in a stable order, at most ``max_files``."""
    root = root.resolve()
    gitignore = _load_spec(root, ".gitignore")
    orkignore = _load_spec(root, ignore_file)

    def is_ignored(rel: str) -> bool:
        if any(part in _IGNORED_DIRS for part in rel.split("/")):
            return True
        if gitignore and gitignore.match_file(rel):
            return True
        return bool(orkignore and orkignore.match_file(rel))

    found: list[Path] = []
    seen: set[Path] = set()

    def take(file_path: Path) -> bool:
        """Add the file; ``False`` once one more than ``max_files`` is found."""
        if file_path in seen or is_ignored(file_path.relative_to(root).as_posix()):
            return True
        if _is_binary_file(file_path) is not False:  # binary or unreadable
            return True
        seen.add(file_path)
        found.append(file_path)
        return max_files is None or len(found) <= max_files

    for base in paths or [root]:
        if base.is_file():
            if not take(base):
                break
            continue
        stop = False
        for dirpath, dirnames, filenames in os.walk(base):
            current = Path(dirpath)
            rel_dir = current.relative_to(root).as_posix()
            prefix = "" if rel_dir == "." else f"{rel_dir}/"
            dirnames[:] = sorted(
                d for d in dirnames if d not in _IGNORED_DIRS and not is_ignored(f"{prefix}{d}")
            )
            for name in sorted(filenames):
                if not take(current / name):
                    stop = True
                    break
            if stop:
                break
        if stop:
            break

    truncated = max_files is not None and len(found) > max_files
    files = found[:max_files] if max_files is not None else found
    return Collected(sorted(files, key=lambda p: p.relative_to(root).as_posix()), truncated)


def has_local_provider(config: Config) -> bool:
    """Whether any enabled provider is marked local: true."""
    return any(p.enabled and p.local for p in config.providers.values())


async def generate_repomap(
    root: Path,
    paths: Sequence[Path] | None,
    config: Config,
    max_files: int | None = None,
    *,
    cwd: Path | None = None,
    on_progress: Progress | None = None,
) -> RepoMapResult:
    """Map the files of ``root`` (or of ``paths``, relative to ``cwd``).

    ``on_progress`` is called before each file that is sent for a summary.
    """
    root = root.resolve()
    targets = resolve_paths(root, paths, (cwd or root).resolve()) if paths else None
    collected = collect_repo_files(
        root, targets, ignore_file=config.security.ignore_file, max_files=max_files
    )
    warnings: list[str] = []
    if collected.truncated and max_files is not None:
        warnings.append(t("map.warning.truncated", max=max_files))

    # Privacy constraint (Mimari §19): map.privacy is local_only by default. Without a local
    # provider no summary is asked for, and no content goes to a remote provider.
    privacy = config.map.privacy
    can_summarize = not (privacy == "local_only" and not has_local_provider(config))
    if not can_summarize:
        warnings.append(t("map.warning.no_local_provider"))

    conn = db.connect() if can_summarize else None
    summarizer = _Summarizer(root, config, conn, warnings, on_progress)
    results: list[FileMap] = []
    try:
        total = len(collected.files)
        for number, file_path in enumerate(collected.files, 1):
            rel = file_path.relative_to(root).as_posix()
            try:
                raw_bytes = file_path.read_bytes()
            except OSError as exc:
                warnings.append(t("map.warning.unreadable", path=rel, reason=exc))
                continue
            text = raw_bytes.decode("utf-8", errors="replace")
            symbols = (
                extract_python_symbols(text)
                if file_path.suffix == ".py"
                else extract_generic_symbols(text, file_path.name)
            )
            summary, cached = ("", False)
            if can_summarize:
                summary, cached = await summarizer.summary(rel, raw_bytes, text, number, total)
                can_summarize = summarizer.active
            results.append(FileMap(path=rel, summary=summary, symbols=symbols, cached=cached))
    finally:
        if conn is not None:
            conn.close()

    return RepoMapResult(
        files=results,
        total_files=len(results),
        summarized_files=summarizer.summarized,
        cached_files=summarizer.cached,
        model_used=summarizer.model_used,
        warnings=warnings,
        map_files=_merged(root, targets, results),
        truncated=collected.truncated,
    )


class _Summarizer:
    """The model summaries of one ``map`` run: one connection and one set of slots."""

    def __init__(
        self,
        root: Path,
        config: Config,
        conn: sqlite3.Connection | None,
        warnings: list[str],
        on_progress: Progress | None,
    ) -> None:
        self.cache_dir = get_map_cache_dir(root)
        self.config = config
        self.conn = conn
        self.slots = ProviderSlots(config)
        self.warnings = warnings
        self.on_progress = on_progress
        self.active = conn is not None
        self.summarized = 0
        self.cached = 0
        self.model_used: str | None = None

    async def summary(
        self, rel: str, raw: bytes, text: str, number: int, total: int
    ) -> tuple[str, bool]:
        content_hash = hash_content(raw)
        cached = get_cached_summary(content_hash, cache_dir=self.cache_dir)
        if cached is not None:
            self.cached += 1
            return cached, True
        if self.on_progress is not None:
            self.on_progress(number, total, rel)
        user = f"File: {rel}\n\n{text[:MAX_FILE_CHARS_FOR_SUMMARY]}"
        try:
            answer, label = await query_chief_model(
                self.config,
                tier=self.config.map.tier,
                system=_SYSTEM_PROMPT,
                user=user,
                privacy=self.config.map.privacy,
                slots=self.slots,
                conn=self.conn,
            )
        except (NoProviderAvailable, ConsentRequired) as exc:
            if prompt_has_secrets(self.config, f"{_SYSTEM_PROMPT}\n{user}"):
                self.warnings.append(t("map.warning.secret_skipped", path=rel))
            else:  # nothing can summarize (budget, consent, paused): structure only from here
                self.active = False
                self.warnings.append(t("map.warning.summaries_stopped", reason=exc.message))
            return "", False
        except ProviderError as exc:
            self.warnings.append(t("map.warning.summary_failed", path=rel, reason=exc.message))
            return "", False
        summary = " ".join(answer.split())
        if not summary:
            self.warnings.append(t("map.warning.empty_summary", path=rel))
            return "", False
        save_cached_summary(content_hash, summary, rel, cache_dir=self.cache_dir)
        self.summarized += 1
        self.model_used = label
        return summary, False


def _merged(root: Path, targets: Sequence[Path] | None, files: list[FileMap]) -> list[FileMap]:
    """What MAP.md lists: this run's files, plus (for ``map <paths>``) the last map's other
    files that still exist."""
    if targets is None:
        return list(files)
    scopes = [target.relative_to(root).as_posix() for target in targets]

    def in_scope(rel: str) -> bool:
        return any(scope in (".", rel) or rel.startswith(f"{scope}/") for scope in scopes)

    mapped = {f.path for f in files}
    kept = [
        old
        for old in _read_index(root)
        if old.path not in mapped and not in_scope(old.path) and (root / old.path).is_file()
    ]
    return sorted([*kept, *files], key=lambda f: f.path)


def _read_index(root: Path) -> list[FileMap]:
    """The last map's entries; a missing or broken index is an empty one (it is a cache)."""
    path = get_map_cache_dir(root) / INDEX_FILE_NAME
    try:
        data = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return []
    entries = data.get("files") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    result: list[FileMap] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        rel, summary, symbols = entry.get("path"), entry.get("summary"), entry.get("symbols")
        if isinstance(rel, str) and isinstance(summary, str) and isinstance(symbols, list):
            result.append(FileMap(rel, summary, [str(s) for s in symbols]))
    return result


def save_map(root: Path, result: RepoMapResult) -> Path:
    """Write ``.orkestra/MAP.md`` and the index the next ``map <paths>`` builds on."""
    root = root.resolve()
    index = {
        "version": 1,
        "files": [
            {"path": f.path, "summary": f.summary, "symbols": f.symbols} for f in result.map_files
        ],
    }
    _write_json(get_map_cache_dir(root) / INDEX_FILE_NAME, index)
    return write_map_file(root, render_markdown(result.map_files))


def render_markdown(files: list[FileMap]) -> str:
    """Render list of FileMap items into MAP.md markdown string."""
    lines = ["# Project Map", ""]

    # Group by top-level directory
    by_dir: dict[str, list[FileMap]] = {}
    for f in files:
        parts = f.path.split("/")
        dir_name = parts[0] + "/" if len(parts) > 1 else "."
        by_dir.setdefault(dir_name, []).append(f)

    for dir_name in sorted(by_dir):
        lines.append(f"## {dir_name}")
        for f in by_dir[dir_name]:
            summary_part = f": {f.summary}" if f.summary else ""
            lines.append(f"- `{f.path}`{summary_part}")
            for sym in f.symbols:
                lines.append(f"  - `{sym.strip()}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_map_file(root: Path, content: str) -> Path:
    out_dir = root / ".orkestra"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / MAP_FILE_NAME
    out_file.write_text(content, encoding="utf-8")
    return out_file
