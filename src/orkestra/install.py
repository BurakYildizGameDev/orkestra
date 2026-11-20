"""Where the running ``orkestra`` comes from (düzeltme-fable a, D-104).

``uv tool install --editable .`` runs whatever branch the repository has checked out, so
the daily tool silently changes when a feature branch is checked out. ``doctor`` warns about
that; the lasting fix is a normal install (Faz 14).
"""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

DISTRIBUTION = "orkestra-cli"
GIT_TIMEOUT_S = 5
DETACHED = "HEAD"  # shown for a detached HEAD
SYMREF_DETACHED = 1  # ``git symbolic-ref --quiet``: HEAD is not a branch; 128: no repository


@dataclass(frozen=True)
class InstallInfo:
    source: Path  # the editable source directory
    prefix: Path  # the environment that runs it
    branch: str | None  # DETACHED, or None: not a git checkout / git missing or failing


def _direct_url() -> str | None:
    try:
        return importlib.metadata.distribution(DISTRIBUTION).read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return None


def _branch(repo: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == SYMREF_DETACHED:
        return DETACHED
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _source(raw: str | None) -> Path | None:
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        return None
    if not isinstance(data, dict) or not (data.get("dir_info") or {}).get("editable"):
        return None
    parts = urlsplit(str(data.get("url", "")))
    if parts.scheme != "file":
        return None
    netloc = f"//{parts.netloc}" if parts.netloc else ""
    return Path(url2pathname(unquote(netloc + parts.path)))


def detect(
    *,
    read_direct_url: Callable[[], str | None] = _direct_url,
    prefix: Path | None = None,
) -> InstallInfo | None:
    """The editable source, the running environment and the source's branch; ``None`` for
    a normal install."""
    source = _source(read_direct_url())
    if source is None:
        return None
    return InstallInfo(source, prefix or Path(sys.prefix), _branch(source))
