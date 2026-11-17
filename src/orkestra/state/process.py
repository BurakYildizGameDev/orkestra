"""Is a process that holds a lock or a slot still there? (Faz 12a; shared since Faz 13l)

A pid alone can be reused, so the owner is ``(pid, process start time)``. Used by the night
queue's lock and by the machine-wide slots of local models.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import psutil

Owner = tuple[int, float | None]  # pid, process start time
Alive = Callable[[int, "float | None"], bool]
_CREATE_TIME_SLACK_S = 1.0


def process_alive(pid: int, created: float | None) -> bool:
    """Is ``pid`` still the process that took the lock (same start time)?"""
    try:
        process = psutil.Process(pid)
        if created is None:
            return process.is_running()
        return abs(process.create_time() - created) <= _CREATE_TIME_SLACK_S
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:  # another user's or a system process: never our runner
        return False
    except (psutil.Error, OverflowError, ValueError):
        return False


def current_owner() -> Owner:
    return os.getpid(), psutil.Process().create_time()
