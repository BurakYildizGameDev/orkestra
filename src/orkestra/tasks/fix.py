"""Run fix commands before verifiers (Faz 13r-b1, plan item 9)."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Sequence
from pathlib import Path

from orkestra.tasks.spec import FixCommand
from orkestra.verify.command import _args, _drain, _kill_tree


async def run_fix_commands(fixes: Sequence[FixCommand], workdir: Path, attempt_dir: Path) -> None:
    """Run each fix command sequentially in the worktree. Exit code is ignored."""
    if not fixes:
        return

    log_entries: list[str] = []
    for fix in fixes:
        cmd_args = _args(fix.run, fix.shell)
        try:
            proc = subprocess.Popen(
                cmd_args,
                cwd=workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                shell=fix.shell,
            )
        except (OSError, ValueError) as exc:
            log_entries.append(f"== fix: {fix.run} (failed to start) ==\n{exc}\n")
            continue

        try:
            raw, _ = await asyncio.to_thread(proc.communicate, timeout=fix.timeout_s)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            raw = await _drain(proc)
            output = raw.decode("utf-8", errors="replace")
            log_entries.append(
                f"== fix: {fix.run} (timed out after {fix.timeout_s}s) ==\n{output}\n"
            )
        except BaseException:
            _kill_tree(proc)
            raise
        else:
            output = raw.decode("utf-8", errors="replace")
            log_entries.append(f"== fix: {fix.run} (exit {proc.returncode}) ==\n{output}\n")

    attempt_dir.mkdir(parents=True, exist_ok=True)
    fix_log_path = attempt_dir / "fix.log"
    with open(fix_log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log_entries))
