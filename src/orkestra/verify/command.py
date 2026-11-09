"""``command`` verifier: run the user's check command (Mimari §10).

No shell by default. POSIX: the command is split with ``shlex``; Windows: the string goes to
``CreateProcess`` as it is, which splits it like ``subprocess.list2cmdline`` writes it. Pipes
and ``&&`` need ``shell: true`` in the task (the only place Orkestra uses a shell, AGENTS.md).
On timeout or interruption the whole process tree is killed.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

import psutil

from orkestra.verify.base import DETAIL_CHARS, CheckResult, Message, VerifyContext, failed, passed


def _args(run: str, shell: bool) -> str | list[str]:
    if shell or os.name == "nt":
        return run
    return shlex.split(run)


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    try:
        children = psutil.Process(proc.pid).children(recursive=True)
    except psutil.Error:
        children = []
    for child in children:
        with contextlib.suppress(psutil.Error):  # already gone
            child.kill()
    if proc.poll() is None:
        proc.kill()


def _tail(text: str) -> str:
    return text[-DETAIL_CHARS:]


@dataclass(frozen=True)
class CommandCheck:
    run: str
    timeout_s: int
    shell: bool = False
    type: str = "command"

    async def check(self, ctx: VerifyContext) -> CheckResult:
        try:
            proc = subprocess.Popen(  # the user's own check command
                _args(self.run, self.shell),
                cwd=ctx.workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                shell=self.shell,  # only when the task says shell: true
            )
        except (OSError, ValueError) as exc:
            name = _program(self.run)
            return failed(self.type, Message("verify.command.not_found", {"command": name}),
                          log=str(exc))  # fmt: skip
        try:
            raw, _ = await asyncio.to_thread(proc.communicate, timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            raw, _ = proc.communicate()
            output = raw.decode("utf-8", errors="replace")
            message = Message("verify.command.timeout", {"seconds": self.timeout_s})
            return failed(self.type, message, f"\n{_tail(output)}".rstrip(), log=output)
        except BaseException:
            _kill_tree(proc)  # Ctrl+C: leave no test run behind
            raise
        output = raw.decode("utf-8", errors="replace")
        if proc.returncode == 0:
            return passed(self.type, _tail(output), log=output)
        message = Message("verify.command.exit", {"code": proc.returncode})
        return failed(self.type, message, f"\n{_tail(output)}".rstrip(), log=output)


def _program(run: str) -> str:
    try:
        parts = shlex.split(run, posix=os.name != "nt")
    except ValueError:
        parts = run.split()
    return Path(parts[0].strip('"')).name if parts else run
