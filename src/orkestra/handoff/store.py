"""Reading and writing the handoff file safely (Mimari §17, Faz 10a).

Every write is atomic (a temporary file in the same folder, then ``os.replace``) and happens
under a short file lock, because two chiefs (or two terminals) may update it at the same time
and an update that read the file before another write would silently lose that entry. The lock
is a plain ``O_CREAT | O_EXCL`` file; no new dependency. A lock left behind by a crash is
removed after ``stale_after_s``. ``Done`` and ``Decisions`` that outgrow ``max_lines`` move
their oldest entries to ``HANDOFF.archive.md`` (appended, never deleted). Every text goes
through the redactor before it is written.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from orkestra.config.schema import Config
from orkestra.errors import HandoffLocked, UsageError
from orkestra.handoff import model
from orkestra.i18n import t
from orkestra.security.redact import Redactor, configured_secrets

LOCK_TIMEOUT_S = 10.0
STALE_LOCK_S = 30.0
POLL_S = 0.05
ARCHIVE_SUFFIX = ".archive.md"


@dataclass(frozen=True)
class UpdateResult:
    section: str
    action: str  # "add" | "set"
    last_updated: model.LastUpdated
    archived: int


def lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


def archive_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}{ARCHIVE_SUFFIX}")


def init_file(path: Path, *, project: str, chief: str, at: datetime, commit: str | None) -> Path:
    """Create the template; an existing file is never overwritten."""
    if path.exists():
        raise UsageError(t("handoff.error.exists", path=path))
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, model.template(project, chief, at, commit))
    return path


def update(
    path: Path,
    *,
    config: Config,
    section: str,
    chief: str,
    now: datetime,
    add: str | None = None,
    set_text: str | None = None,
    commit: str | None = None,
    environ: Mapping[str, str] | None = None,
    lock_timeout_s: float = LOCK_TIMEOUT_S,
    stale_after_s: float = STALE_LOCK_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> UpdateResult:
    """Change one section under the lock, then write the file atomically."""
    if not path.exists():
        raise UsageError(t("handoff.error.missing", path=path))
    _validate(section, add=add, set_text=set_text)
    redact = Redactor(configured_secrets(config, environ))

    lock = lock_path(path)
    _acquire(lock, now=now, timeout_s=lock_timeout_s, stale_after_s=stale_after_s,
             clock=clock, sleep=sleep)  # fmt: skip
    try:
        document = model.parse(path.read_text(encoding="utf-8"))
        if add is not None:
            item = redact(add)
            model.add_item(document, section, f"[{now.date().isoformat()} {chief}] {item}")
        else:
            model.set_section(document, section, redact(set_text or ""))
        archived = _archive(document, config, path, redact)
        model.set_last_updated(document, chief, now, commit)
        _atomic_write(path, model.render(document))
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock.unlink()
    last_updated = model.parse_last_updated(document)
    if last_updated is None:  # set_last_updated always writes it
        raise UsageError(t("handoff.error.missing_section", section=model.LAST_UPDATED))
    return UpdateResult(section, "add" if add is not None else "set", last_updated, archived)


def _validate(section: str, *, add: str | None, set_text: str | None) -> None:
    if section not in model.SECTION_HEADINGS:
        raise UsageError(
            t(
                "handoff.error.unknown_section",
                section=section,
                choices=", ".join(model.SECTION_ORDER),
            )
        )
    if add is not None and set_text is not None:
        raise UsageError(t("handoff.error.add_and_set"))
    is_list = section in model.LIST_SECTIONS
    if is_list and add is None:
        raise UsageError(t("handoff.error.list_needs_add", section=section))
    if not is_list and set_text is None:
        raise UsageError(t("handoff.error.text_needs_set", section=section))


def _acquire(
    lock: Path,
    *,
    now: datetime,
    timeout_s: float,
    stale_after_s: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> None:
    start = clock()
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return
        except FileExistsError:
            try:
                age = now.timestamp() - lock.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > stale_after_s:
                with contextlib.suppress(FileNotFoundError):
                    lock.unlink()
                continue
            if clock() - start >= timeout_s:
                raise HandoffLocked(t("handoff.error.locked", path=lock)) from None
            sleep(POLL_S)


def _archive(
    document: model.Document, config: Config, path: Path, redact: Callable[[str], str]
) -> int:
    """Move the oldest entries of every list section over ``max_lines`` to the archive."""
    collapsed: list[tuple[str, list[str]]] = []
    for slug in model.LIST_SECTIONS:
        text = model.section_text(document, slug) or ""
        lines = [line for line in text.splitlines() if line.strip()]
        limit = config.handoff.max_lines
        if len(lines) <= limit:
            continue
        overflow = lines[: len(lines) - limit]
        collapsed.append((slug, overflow))
        model.set_section(document, slug, "\n".join(lines[len(lines) - limit :]))
    if not collapsed:
        return 0
    archive = archive_path(path)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with open(archive, "a", encoding="utf-8", newline="\n") as handle:
        for slug, lines in collapsed:
            handle.write(f"\n## {model.SECTION_HEADINGS[slug]} (archived)\n")
            for line in lines:
                handle.write(redact(line) + "\n")
    return sum(len(lines) for _, lines in collapsed)


def _atomic_write(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
