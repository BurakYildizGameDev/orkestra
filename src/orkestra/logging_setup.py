"""Per-run log file with redaction (Mimari §14).

Log messages are English and go to ``runs/<run_id>/orkestra.log``. Prompts and responses are
not logged; they live in ``attempts/<n>/``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from orkestra.security.redact import RedactFilter, Redactor

LOGGER_NAME = "orkestra"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


@contextmanager
def run_log(run_dir: Path, redactor: Redactor) -> Iterator[logging.Logger]:
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    handler = logging.FileHandler(run_dir / "orkestra.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(RedactFilter(redactor))
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield logger
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        handler.close()
