"""Cross-process locks for config files, using only the Python standard library."""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def process_lock(path: Path) -> Iterator[None]:
    """Lock a config path across processes on this machine."""
    normalized = os.path.normcase(str(path.expanduser().resolve()))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    lock_dir = Path(tempfile.gettempdir()) / "orkestra-config-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{digest}.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
