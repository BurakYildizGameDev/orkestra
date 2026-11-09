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
        return Path(value).expanduser()
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
