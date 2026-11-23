"""Locations of Orkestra's per-user files (Mimari §3).

Nothing here creates directories; callers create what they need.
"""

from __future__ import annotations

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
