"""Start the next chief with the brief, and install the optional git hook (Faz 10b).

``handoff to`` never captures the child's output: the new chief needs the user's terminal.
On Windows the child is a normal subprocess and its exit code becomes ``to``'s exit code; on
Unix ``os.execvp`` replaces the process. Three ways to give the brief exist (Mimari §17):

- ``arg``: the brief is the last command-line argument. A ``.cmd``/``.bat`` launcher (Windows
  quoting trap, BatBadBut) or a brief over ``ARG_MAX_CHARS`` falls back to ``file``.
- ``stdin``: the brief is written to the child's stdin.
- ``file``: the brief is written to ``.orkestra/BRIEF.md`` and the child gets one short
  English instruction to read it.

The child always starts in the repository root (the instruction's path is relative to it) and
gets ``ORKESTRA_CHIEF`` set to its own name. While a Windows child runs, Orkestra ignores
Ctrl+C: the key belongs to the new chief (D-066).

The handoff row is written *before* the child starts (``execvp`` never returns), and never for
``--print-only``. A dirty working tree stops the handoff unless ``--allow-dirty`` is given;
the files ``handoff`` itself writes (the handoff file, its archive and lock, ``BRIEF.md``)
never count as dirty.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
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
CHIEF_ENV = "ORKESTRA_CHIEF"
DIRTY_SHOWN = 5  # file names in the dirty-tree error before "and N more"
HOOK_MARKER_START = "# >>> orkestra handoff >>>"
HOOK_MARKER_END = "# <<< orkestra handoff <<<"
HOOK_COMMAND = "orkestra handoff check --warn-only"
HOOK_BLOCK = (
    f"{HOOK_MARKER_START}\n"
    "# Reminds whoever commits to update the handoff file; it never blocks a commit.\n"
    "if command -v orkestra >/dev/null 2>&1; then\n"
    f"  {HOOK_COMMAND} || true\n"
    "fi\n"
    f"{HOOK_MARKER_END}\n"
)
SHELL_SCRIPTS = (".cmd", ".bat")
SHELLS = frozenset({"sh", "bash", "dash", "zsh", "ksh", "ash", "mksh"})
_SHEBANG = re.compile(r"^#!\s*(\S+)(.*)$")

Spawn = Callable[[list[str], str | None, Path, Mapping[str, str]], int]
Which = Callable[[str], str | None]
Git = Callable[[list[str], Path], tuple[bool, str]]
Runner = Callable[..., "subprocess.CompletedProcess[bytes]"]


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
    cwd: Path,
    env: Mapping[str, str],
    *,
    platform: str = os.name,
    execvpe: Callable[[str, list[str], Mapping[str, str]], object] = os.execvpe,
    chdir: Callable[[Path], object] = os.chdir,
    runner: Runner = subprocess.run,
) -> int:
    """Run the child in the user's terminal without a shell, in ``cwd`` with ``env``.

    Unix replaces the process (``execvpe``); a child that needs stdin cannot be fed after
    ``execvpe``, so stdin mode stays a subprocess there too. While the subprocess runs,
    Ctrl+C is ignored here: ``subprocess.run`` kills the child on ``KeyboardInterrupt``,
    and the key press is meant for the new chief, which gets it from the console itself.
    """
    if platform != "nt" and stdin_text is None:
        chdir(cwd)
        execvpe(argv[0], argv, env)
        return 0  # only reached when execvpe is replaced in a test
    data = stdin_text.encode("utf-8") if stdin_text is not None else None
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        done = runner(argv, input=data, check=False, cwd=cwd, env=env)
    finally:
        signal.signal(signal.SIGINT, previous)
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
        dirty = _dirty_files(root, run_git, _own_files(path, root))
        if dirty:
            raise HandoffNotClean(t("handoff.error.dirty", count=len(dirty),
                                    files=_file_list(dirty)))  # fmt: skip

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
    child_env = {**(os.environ if environ is None else environ), CHIEF_ENV: chief}
    if before_start is not None:
        before_start(mode, warnings)
    exit_code = run_child(argv, stdin_text, root, child_env)
    return ToResult(chief, mode, content.text, brief_path, exit_code, warnings)


def _own_files(path: Path, root: Path) -> set[str]:
    """Repository-relative paths ``handoff`` writes itself; they never make the tree dirty."""
    own = {BRIEF_RELATIVE.as_posix()}
    for candidate in (path, store.archive_path(path), store.lock_path(path)):
        try:
            own.add(candidate.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:  # a handoff file configured outside the repository
            continue
    return own


def _dirty_files(root: Path, git: Git, own: set[str]) -> list[str]:
    """Changed files, one per line (``--untracked-files=all`` lists a new folder's files)."""
    ok, output = git(["status", "--porcelain", "--untracked-files=all"], root)
    if not ok:
        return []  # outside a repository there is nothing to be dirty against
    files: list[str] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        changed = line[3:].split(" -> ")[-1].strip().strip('"')
        if changed in own:
            continue
        files.append(changed)
    return files


def _file_list(files: list[str]) -> str:
    shown = ", ".join(files[:DIRTY_SHOWN])
    if len(files) <= DIRTY_SHOWN:
        return shown
    return t("handoff.error.dirty_more", files=shown, count=len(files) - DIRTY_SHOWN)


def install_hook(cwd: Path, *, git: Git | None = None) -> InstallResult:
    """Put the reminder block into the repository's pre-commit hook, never overwriting it.

    The block goes right after the shebang, so an ``exit`` or ``exec`` later in the old hook
    cannot skip it. A hook that is not a shell script is left alone (shell lines in a Python
    hook are a syntax error, and that would block every commit).
    """
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
        first, separator, rest = text.partition(newline)
        if not _is_shell_shebang(first):
            raise UsageError(t("handoff.error.hook_not_shell", path=hook, command=HOOK_COMMAND))
        block = HOOK_BLOCK.replace("\n", newline)
        hook.write_bytes(
            (first + newline + block + rest).encode("utf-8", errors="surrogateescape")
            if separator
            else (first + newline + block).encode("utf-8", errors="surrogateescape")
        )
        _make_executable(hook)
        return InstallResult(hook, False, True)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_bytes(("#!/bin/sh\n" + HOOK_BLOCK).encode("utf-8"))
    _make_executable(hook)
    return InstallResult(hook, True, False)


def _is_shell_shebang(line: str) -> bool:
    match = _SHEBANG.match(line.strip())
    if match is None:
        return False
    program = match.group(1).rsplit("/", 1)[-1]
    if program == "env":
        program = next((arg for arg in match.group(2).split() if not arg.startswith("-")), "")
    return program in SHELLS


def _make_executable(path: Path) -> None:
    try:
        path.chmod(0o755)
    except OSError:  # Windows has no executable bit; git for Windows runs the hook anyway
        return
