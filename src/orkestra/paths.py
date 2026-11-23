"""Locations of Orkestra's per-user files (Mimari §3).

Nothing here creates directories; callers create what they need.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

HOME_ENV = "ORKESTRA_HOME"


def orkestra_home() -> Path:
    """``$ORKESTRA_HOME`` if set and non-empty, otherwise ``~/.orkestra``."""
    value = os.environ.get(HOME_ENV, "").strip()
    if value:
        home = Path(value).expanduser()
        if home.exists() and not home.is_dir():  # B-19, D-140
            from orkestra.errors import UsageError
            from orkestra.i18n import t

            raise UsageError(t("paths.error.home_not_dir", path=home))
        return home
    return Path.home() / ".orkestra"


PROJECT_DIR = ".orkestra"
_PROJECT_IGNORE = (
    "# Written by Orkestra: its generated files stay out of git.\n"
    "# HANDOFF.md and templates/ are yours to commit.\n"
    ".gitignore\ncache/\nBRIEF.md\nMAP.md\ntasks/\n"
)


def ensure_project_dir(root: Path) -> Path:
    """``<root>/.orkestra``, created with a ``.gitignore`` for Orkestra's own generated files,
    so ``map``, ``delegate`` and the brief leave ``git status`` clean (B-22, D-141)."""
    folder = root / PROJECT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    ignore = folder / ".gitignore"
    if not ignore.exists():
        with contextlib.suppress(OSError):  # only tidiness is lost
            ignore.write_text(_PROJECT_IGNORE, encoding="utf-8")
    return folder


def global_config_path() -> Path:
    return orkestra_home() / "config.yaml"


def state_db_path() -> Path:
    return orkestra_home() / "state.db"


def runs_dir() -> Path:
    return orkestra_home() / "runs"


def run_dir(run_id: str) -> Path:
    return runs_dir() / run_id


def worktrees_dir() -> Path:
    return orkestra_home() / "worktrees"


def cache_dir() -> Path:
    return orkestra_home() / "cache"
