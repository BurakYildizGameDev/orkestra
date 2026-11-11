"""Repository map generator (Mimari §19).

Extracts model-free structural information (Python AST, heuristics for other files)
and 1-2 sentence purpose summaries using a local model.
Summaries are cached by SHA256 of file content in ``.orkestra/cache/map/<hash>.json``.
If no local provider is available under ``privacy: local_only``, remote models are NEVER
called; only structural information is generated.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pathspec

from orkestra.chief.call import query_chief_model
from orkestra.config.schema import Config
from orkestra.errors import NoProviderAvailable
from orkestra.i18n import t

MAP_FILE_NAME = "MAP.md"
MAP_CACHE_SUBDIR = Path(".orkestra") / "cache" / "map"
MAX_FILE_CHARS_FOR_SUMMARY = 50_000
BINARY_CHECK_BYTES = 8192

_GENERIC_PATTERNS = re.compile(
    r"^\s*(export\s+)?(default\s+)?(async\s+)?(function\s+\w+|class\s+\w+|def\s+\w+|fn\s+\w+|type\s+\w+|interface\s+\w+)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class FileMap:
    path: str  # relative path, forward slashes
    summary: str
    symbols: list[str] = field(default_factory=list)
    cached: bool = False


@dataclass(frozen=True)
class RepoMapResult:
    files: list[FileMap]
    total_files: int
    summarized_files: int
    cached_files: int
    model_used: str | None
    warnings: list[str] = field(default_factory=list)


def hash_content(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_map_cache_dir(project_root: Path) -> Path:
    return project_root / MAP_CACHE_SUBDIR


def get_cached_summary(content_hash: str, *, cache_dir: Path) -> str | None:
    cache_file = cache_dir / f"{content_hash}.json"
    if not cache_file.is_file():
        return None
    try:
        data = json.loads(cache_file.read_bytes())
        summary = data.get("summary")
        return summary if isinstance(summary, str) else None
    except (OSError, ValueError):
        return None


def save_cached_summary(content_hash: str, summary: str, rel_path: str, *, cache_dir: Path) -> None:
    cache_file = cache_dir / f"{content_hash}.json"
    data = {"hash": content_hash, "path": rel_path, "summary": summary}
    tmp_file = cache_file.with_name(f"{cache_file.name}.{os.getpid()}.tmp")
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp_file.write_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        os.replace(tmp_file, cache_file)
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
            prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
            args_str = ast.unparse(node.args)
            ret_str = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            symbols.append(f"{prefix}{node.name}({args_str}){ret_str}")
        elif isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            bases_str = f"({', '.join(bases)})" if bases else ""
            symbols.append(f"class {node.name}{bases_str}")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m_prefix = "async def " if isinstance(item, ast.AsyncFunctionDef) else "def "
                    m_args = ast.unparse(item.args)
                    m_ret = f" -> {ast.unparse(item.returns)}" if item.returns else ""
                    symbols.append(f"  {m_prefix}{item.name}({m_args}){m_ret}")
    return symbols


def extract_generic_symbols(code: str, filename: str) -> list[str]:
    """Heuristic symbol extraction for non-Python files."""
    lines = code.splitlines()
    symbols: list[str] = []
    for line in lines[:300]:
        match = _GENERIC_PATTERNS.search(line)
        if match:
            clean = line.strip().rstrip("{;").strip()
            if clean and len(clean) < 120:
                symbols.append(clean)
        if len(symbols) >= 15:
            break
    return symbols


def is_binary_content(data: bytes) -> bool:
    return b"\x00" in data[:BINARY_CHECK_BYTES]


def _load_spec(root: Path, filename: str) -> pathspec.PathSpec | None:
    path = root / filename
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)
    except OSError:
        return None


_IGNORED_DIRS = {
    ".git",
    ".orkestra",
    "__pycache__",
    ".venv",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
}


def collect_repo_files(
    root: Path,
    paths: Sequence[Path] | None = None,
    ignore_file: str = ".orkestraignore",
    max_files: int | None = None,
) -> list[Path]:
    """Collect non-ignored, non-binary source files to map."""
    gitignore = _load_spec(root, ".gitignore")
    orkignore = _load_spec(root, ignore_file)

    collected: list[Path] = []

    def is_ignored(rel_str: str) -> bool:
        parts = rel_str.split("/")
        if any(p in _IGNORED_DIRS for p in parts):
            return True
        if gitignore and gitignore.match_file(rel_str):
            return True
        return bool(orkignore and orkignore.match_file(rel_str))

    search_dirs: list[Path] = []
    if paths:
        for p in paths:
            abs_p = (p if p.is_absolute() else (root / p)).resolve()
            if abs_p.is_file():
                try:
                    rel = abs_p.relative_to(root).as_posix()
                except ValueError:
                    rel = abs_p.name
                if not is_ignored(rel):
                    collected.append(abs_p)
            elif abs_p.is_dir():
                search_dirs.append(abs_p)
    else:
        search_dirs.append(root)

    for base_dir in search_dirs:
        for dirpath, dirnames, filenames in os.walk(base_dir):
            try:
                rel_dir = Path(dirpath).relative_to(root).as_posix()
            except ValueError:
                rel_dir = Path(dirpath).name
            prefix = "" if rel_dir == "." else f"{rel_dir}/"
            dirnames[:] = [
                d for d in dirnames if d not in _IGNORED_DIRS and not is_ignored(f"{prefix}{d}")
            ]
            for fname in filenames:
                rel = f"{prefix}{fname}"
                if is_ignored(rel):
                    continue
                file_path = Path(dirpath) / fname
                try:
                    data = file_path.read_bytes()
                except OSError:
                    continue
                if is_binary_content(data):
                    continue
                collected.append(file_path)
                if max_files is not None and len(collected) >= max_files:
                    return sorted(collected)

    return sorted(collected)


def has_local_provider(config: Config) -> bool:
    """Whether any enabled provider is marked local: true."""
    return any(p.enabled and p.local for p in config.providers.values())


async def generate_repomap(
    root: Path,
    paths: Sequence[Path] | None,
    config: Config,
    max_files: int | None = None,
) -> RepoMapResult:
    """Generate repository map for files in ``root``."""
    files_to_map = collect_repo_files(
        root, paths, ignore_file=config.security.ignore_file, max_files=max_files
    )
    cache_dir = get_map_cache_dir(root)
    warnings: list[str] = []

    # Privacy constraint (Mimari §19):
    # map.privacy is local_only by default. If no local provider is available,
    # skip model summaries and never send content to remote providers.
    privacy = config.map.privacy
    can_summarize = True
    if privacy == "local_only" and not has_local_provider(config):
        can_summarize = False
        warnings.append(t("map.warning.no_local_provider"))

    results: list[FileMap] = []
    summarized_count = 0
    cached_count = 0
    model_used: str | None = None

    for file_path in files_to_map:
        try:
            raw_bytes = file_path.read_bytes()
            text = raw_bytes.decode("utf-8", errors="replace")
            rel = file_path.relative_to(root).as_posix()
        except OSError:
            continue

        # 1. Structural information (always extracted models-free)
        if file_path.suffix == ".py":
            symbols = extract_python_symbols(text)
        else:
            symbols = extract_generic_symbols(text, file_path.name)

        summary = ""
        is_cached = False

        if can_summarize:
            content_hash = hash_content(raw_bytes)
            cached_sum = get_cached_summary(content_hash, cache_dir=cache_dir)
            if cached_sum is not None:
                summary = cached_sum
                is_cached = True
                cached_count += 1
            else:
                try:
                    system_prompt = (
                        "You are an assistant creating a concise project map. "
                        "Summarize the single purpose of this file in 1-2 direct sentences. "
                        "Avoid preamble."
                    )
                    summary_resp, label = await query_chief_model(
                        config,
                        tier=config.map.tier,
                        system=system_prompt,
                        user=f"File: {rel}\n\n{text[:MAX_FILE_CHARS_FOR_SUMMARY]}",
                        privacy=privacy,
                    )
                    summary = " ".join(summary_resp.strip().split())
                    save_cached_summary(content_hash, summary, rel, cache_dir=cache_dir)
                    summarized_count += 1
                    model_used = label
                except NoProviderAvailable:
                    can_summarize = False
                    warnings.append(t("map.warning.no_local_provider"))
                except Exception as exc:  # Provider error during summary
                    warnings.append(f"{rel}: {exc}")

        results.append(FileMap(path=rel, summary=summary, symbols=symbols, cached=is_cached))

    return RepoMapResult(
        files=results,
        total_files=len(results),
        summarized_files=summarized_count,
        cached_files=cached_count,
        model_used=model_used,
        warnings=warnings,
    )


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
