"""Start the next chief with the brief, and install the optional git hook (Faz 10b).

``handoff to`` never captures the child's output: the new chief needs the user's terminal.
On Windows the child is a normal subprocess and its exit code becomes ``to``'s exit code; on
Unix ``os.execvp`` replaces the process. Three ways to give the brief exist (Mimari §17):

- ``arg``: the brief is the last command-line argument. A ``.cmd``/``.bat`` launcher (Windows
  quoting trap, BatBadBut) or a brief over ``ARG_MAX_CHARS`` falls back to ``file``.
- ``stdin``: the brief is written to the child's stdin.
- ``file``: the brief is written to ``.orkestra/BRIEF.md`` and the child gets one short
  English instruction to read it.

The handoff row is written *before* the child starts (``execvp`` never returns), and never for
``--print-only``. A dirty working tree stops the handoff unless ``--allow-dirty`` is given;
``.orkestra/BRIEF.md`` alone never counts as dirty.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from orkestra.config.schema import Config
from orkestra.errors import HandoffNotClean, UsageError
from orkestra.handoff import brief, store
from orkestra.i18n import t
from orkestra.state import db

ARG_MAX_CHARS = 8000  # Windows allows 32767; stay well below for quoting and environment
BRIEF_RELATIVE = Path(".orkestra") / "BRIEF.md"
BRIEF_INSTRUCTION = "Read .orkestra/BRIEF.md and continue from the next step there."
HOOK_MARKER_START = "# >>> orkestra handoff >>>"
HOOK_MARKER_END = "# <<< orkestra handoff <<<"
HOOK_BLOCK = (
    f"{HOOK_MARKER_START}\n"
    "# Reminds whoever commits to update the handoff file; it never blocks a commit.\n"
    "if command -v orkestra >/dev/null 2>&1; then\n"
    "  orkestra handoff check --warn-only >/dev/null 2>&1 || true\n"
    "fi\n"
    f"{HOOK_MARKER_END}\n"
)
SHELL_SCRIPTS = (".cmd", ".bat")

Spawn = Callable[[list[str], str | None], int]
Which = Callable[[str], str | None]
Git = Callable[[list[str], Path], tuple[bool, str]]


@dataclass(frozen=True)
class ToResult:
    chief: str
    mode: str  # the mode actually used, which may have fallen back to "file"
    brief: str
    brief_path: Path | None
    exit_code: int
    warnings: list[str]


@dataclass(frozen=True)
class InstallResult:
    path: Path
    created: bool
    updated: bool


def default_spawn(
    argv: list[str],
    stdin_text: str | None,
    *,
    platform: str = os.name,
    execvp: Callable[[str, list[str]], int] = os.execvp,
) -> int:
    """Run the child in the user's terminal without a shell.

    Unix replaces the process (``execvp``); a child that needs stdin cannot be fed after
    ``execvp``, so stdin mode stays a subprocess there too.
    """
    if platform != "nt" and stdin_text is None:
        return execvp(argv[0], argv)
    data = stdin_text.encode("utf-8") if stdin_text is not None else None
    done = subprocess.run(argv, input=data, check=False)
    return done.returncode


def to(
    chief: str,
    config: Config,
    conn: sqlite3.Connection,
    now: datetime,
    *,
    path: Path,
    cwd: Path,
    from_chief: str | None,
    allow_dirty: bool = False,
    print_only: bool = False,
    which: Which = shutil.which,
    spawn: Spawn | None = None,
    git: Git | None = None,
    environ: Mapping[str, str] | None = None,
    before_start: Callable[[str, list[str]], None] | None = None,
) -> ToResult:
    """Build the brief and start ``chief`` (or only print the brief with ``print_only``).

    ``before_start`` runs after the row is written and just before the child is spawned, so a
    caller can print warnings while the terminal still belongs to Orkestra.
    """
    if chief not in config.chiefs:
        raise UsageError(
            t(
                "handoff.error.unknown_chief",
                name=chief,
                choices=", ".join(sorted(config.chiefs)),
            )
        )
    if not path.exists():
        raise UsageError(t("handoff.error.missing", path=path))
    run_git = brief.default_git if git is None else git
    run_child = default_spawn if spawn is None else spawn
    settings = config.chiefs[chief]
    content = brief.build(config, conn, now, path=path, cwd=cwd, git=run_git, environ=environ)

    if print_only:
        return ToResult(chief, settings.prompt_mode, content.text, None, 0, [])

    resolved = which(settings.launch[0])
    if resolved is None:
        raise UsageError(t("handoff.error.launch_missing", chief=chief, command=settings.launch[0]))
    root = store.project_root(cwd, run_git)
    if not allow_dirty:
        dirty = _dirty_lines(root, run_git)
        if dirty:
            raise HandoffNotClean(t("handoff.error.dirty", count=len(dirty)))

    mode = settings.prompt_mode
    warnings: list[str] = []
    if mode == "arg":
        if resolved.lower().endswith(SHELL_SCRIPTS):
            mode = "file"
            warnings.append(t("handoff.to.warning.cmd"))
        elif len(content.text) > ARG_MAX_CHARS:
            mode = "file"
            warnings.append(t("handoff.to.warning.long"))

    brief_path: Path | None = None
    stdin_text: str | None = None
    argv = [resolved, *settings.launch[1:]]
    if mode == "arg":
        argv.append(content.text)
    elif mode == "stdin":
        stdin_text = content.text
    else:
        brief_path = root / BRIEF_RELATIVE
        brief_path.parent.mkdir(parents=True, exist_ok=True)
        brief_path.write_bytes(content.text.encode("utf-8"))
        argv.append(BRIEF_INSTRUCTION)

    db.record_handoff(
        conn,
        from_chief=from_chief,
        to_chief=chief,
        at=now,
        commit=brief.head_commit(cwd, run_git),
        brief_path=str(brief_path) if brief_path is not None else None,
    )
    if before_start is not None:
        before_start(mode, warnings)
    exit_code = run_child(argv, stdin_text)
    return ToResult(chief, mode, content.text, brief_path, exit_code, warnings)


def _dirty_lines(root: Path, git: Git) -> list[str]:
    """Uncommitted changes; ``.orkestra/BRIEF.md`` is written by us, so it does not count."""
    ok, output = git(["status", "--porcelain"], root)
    if not ok:
        return []  # outside a repository there is nothing to be dirty against
    wanted = BRIEF_RELATIVE.as_posix()
    lines: list[str] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        changed = line[3:].strip().strip('"')
        if changed == wanted or changed.endswith(f"/{wanted}"):
            continue
        lines.append(line)
    return lines


def install_hook(cwd: Path, *, git: Git | None = None) -> InstallResult:
    """Add the reminder block to the repository's pre-commit hook, never overwriting it."""
    run_git = brief.default_git if git is None else git
    ok, output = run_git(["rev-parse", "--git-path", "hooks"], cwd)
    if not ok or not output.strip():
        raise UsageError(t("handoff.error.no_git"))
    hooks = Path(output.strip())
    if not hooks.is_absolute():
        hooks = cwd / hooks
    hook = hooks / "pre-commit"
    if hook.exists():
        text = hook.read_bytes().decode("utf-8", errors="surrogateescape")
        if HOOK_MARKER_START in text:
            return InstallResult(hook, False, False)
        newline = "\r\n" if "\r\n" in text else "\n"
        if not text.endswith(("\n", "\r")):
            text += newline
        hook.write_bytes(
            (text + HOOK_BLOCK.replace("\n", newline)).encode("utf-8", errors="surrogateescape")
        )
        _make_executable(hook)
        return InstallResult(hook, False, True)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_bytes(("#!/bin/sh\n" + HOOK_BLOCK).encode("utf-8"))
    _make_executable(hook)
    return InstallResult(hook, True, False)


def _make_executable(path: Path) -> None:
    with contextlib.suppress(OSError):  # Windows has no executable bit
        path.chmod(0o755)
