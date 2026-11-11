"""Answer cache for ``ask`` tasks (Mimari §19, Faz 8a).

- Key: ``sha256`` of provider, model, system prompt, user prompt, JSON mode and the task's
  checks. The user prompt holds the context files' contents and the system prompt the
  answer schema, so a changed file, schema or check is a new question (no stale answers).
- Only an answer that passed the task's checks is stored, and only for ``ask`` tasks of chat
  workers: an ``edit`` changes files, and a code agent's answer depends on its working
  directory. A cached answer that fails its checks later is dropped (``forget``).
- An entry is valid for ``cache.ttl_days`` days (0: never). A hit costs nothing and sends
  nothing; the envelope says ``cached: true``.
- Files: ``~/.orkestra/cache/responses/<key>.json`` (the answer with secrets masked, as in
  the run records, and no prompt). Written atomically; a broken file is a miss.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from orkestra import paths

VERSION = 1


def cache_root() -> Path:
    return paths.cache_dir() / "responses"


def make_key(
    provider: str, model: str, system: str, user: str, *, json_mode: bool, checks: Any = None
) -> str:
    """``checks``: the task's checks (JSON-able), so an answer is only reused for a task that
    checks it the same way."""
    payload = json.dumps(
        {"v": VERSION, "provider": provider, "model": model, "system": system, "user": user,
         "json_mode": json_mode, "checks": checks},
        sort_keys=True, ensure_ascii=False,
    )  # fmt: skip
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _path(key: str, root: Path | None) -> Path:
    return (root or cache_root()) / f"{key}.json"


def load(key: str, *, now: datetime, ttl_days: int, root: Path | None = None) -> str | None:
    """The cached answer, or ``None`` (missing, expired, unreadable)."""
    try:
        data = json.loads(_path(key, root).read_bytes())
        created = datetime.fromisoformat(data["created_at"])
        text = data["text"]
        expired = now - created >= timedelta(days=ttl_days)  # no time zone: TypeError
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(text, str) or expired:
        return None
    return text


def forget(key: str, root: Path | None = None) -> None:
    """Drop one entry (a cached answer that no longer passes its checks)."""
    with contextlib.suppress(OSError):
        _path(key, root).unlink()


def store(
    key: str, text: str, *, now: datetime, provider: str, model: str, root: Path | None = None
) -> None:
    """Save an answer (best effort: a cache that cannot be written is only a miss later)."""
    path = _path(key, root)
    data = {"created_at": now.isoformat(), "provider": provider, "model": model, "text": text}
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()


def clear(root: Path | None = None) -> int:
    """Remove every cached answer; the number of entries removed."""
    removed = 0
    for path in (root or cache_root()).glob("*.json"):
        with contextlib.suppress(OSError):
            path.unlink()
            removed += 1
    return removed
