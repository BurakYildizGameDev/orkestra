"""``orkestra exec -- <command>``: run a command, keep its long output out of the chief's
context (Faz 13i-a, D-088).

The command runs without a shell (its program is found on PATH, so ``uv``, ``npm.cmd`` …
work on Windows), stdout and stderr together, with a timeout. Its whole output, with keys
masked, goes to ``runs/<id>/output.log``; the answer always says where, and the exit code is
the command's own (127: program not found, 124: timed out).

What the chief reads instead of the output:
- up to ``exec.max_lines`` lines: the output as it is;
- output a rule knows (``outparse``: pytest, ruff, pyright, compilers): its headline and
  every finding with ``file:line``; no model, no mistakes, no failed test name dropped;
- anything else: a worker's summary (``exec.tier``, through the router, so secrets stay
  local); without a worker, or with ``--no-model``, the first and last lines.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from orkestra import paths
from orkestra.chief import outparse
from orkestra.chief.call import query_chief_model
from orkestra.config import loader
from orkestra.config.schema import Config, ExecCfg
from orkestra.errors import ConfigError, OrkestraError
from orkestra.i18n import t
from orkestra.providers.cli_agent import KILL_GRACE_S, kill_tree
from orkestra.security.redact import Redactor, configured_secrets, secret_env_values
from orkestra.tasks.runner import new_run_id

LOG_FILE = "output.log"
META_FILE = "exec.json"
CHARS_PER_LINE = 300  # "short" also means at most max_lines * this many characters
MODEL_LINES = 400  # the last lines a worker reads
MODEL_CHARS = 40_000
NOT_FOUND, CANNOT_RUN, TIMED_OUT = 127, 126, 124
NOTE_CHARS = 160

SUMMARY_SYSTEM = (
    "You summarise the output of a command for a programmer who will not read it. "
    "Write at most 12 short lines. Start with what happened (succeeded, failed, how far it "
    "got). List every error, failed test or warning that matters, each with its file:line "
    "when the output gives one, and keep names exactly as written. No advice, no guessing, "
    "nothing that is not in the output."
)

Runner = Callable[[list[str], Path, float], "Completed"]
Summarizer = Callable[..., Awaitable[tuple[str, str]]]


@dataclass(frozen=True)
class Completed:
    code: int
    output: bytes
    timed_out: bool = False


@dataclass
class ExecResult:
    exit_code: int
    lines: int
    log: Path
    kind: str  # full | digest | model | head_tail
    summary: str
    parser: str | None = None
    headline: str | None = None
    items: list[outparse.Item] = field(default_factory=list)
    model: str | None = None
    note: str | None = None  # why there is no worker summary
    timed_out: bool = False


def run_command(argv: list[str], cwd: Path, timeout_s: float) -> Completed:
    """Run ``argv`` without a shell; output of stdout and stderr together, in order."""
    program = shutil.which(argv[0])
    if program is None:  # as a shell would say it, with its code
        return Completed(NOT_FOUND, t("exec.error.not_found", command=argv[0]).encode("utf-8"))
    try:
        proc = subprocess.Popen(
            [program, *argv[1:]], cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )  # fmt: skip
    except (OSError, ValueError) as exc:  # found, but not a program (no exec bit, a .txt …)
        message = t("exec.error.cannot_run", command=argv[0], error=exc)
        return Completed(CANNOT_RUN, message.encode("utf-8"))
    try:
        output, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        finished = proc.poll() is not None  # it ended; a process it left holds the output
        kill_tree(proc.pid)  # its children too (a test runner's workers)
        output = _drain(proc)
        if finished:
            return Completed(proc.returncode, output)
        return Completed(TIMED_OUT, output, timed_out=True)
    except BaseException:
        kill_tree(proc.pid)  # Ctrl+C: leave no test run behind
        raise
    return Completed(proc.returncode, output or b"")


def _drain(proc: subprocess.Popen[bytes]) -> bytes:
    """Output of a stopped command, waiting at most ``KILL_GRACE_S``: a process outside its
    tree (a server it started) may hold the pipe open, and then the output is given up
    instead of waiting forever (as the ``command`` check does)."""
    try:
        output, _ = proc.communicate(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        return b""
    return output or b""


def load(config_flag: Path | None = None) -> tuple[Config | None, str | None]:
    """The config and, when it does not load, why. ``exec`` works without one (no worker
    summary then); a broken one is named instead of being taken for a missing one."""
    if not loader.find_sources(config_flag):
        return None, None
    try:
        return loader.load_config(config_flag).config, None
    except ConfigError as exc:
        first = exc.details[0] if exc.details else exc.message
        return None, _one_line(first or type(exc).__name__)


def execute(
    argv: list[str],
    *,
    cwd: Path,
    config: Config | None,
    config_problem: str | None = None,
    max_lines: int | None = None,
    use_model: bool | None = None,
    timeout_s: float | None = None,
    now: datetime | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Runner = run_command,
) -> ExecResult:
    settings = config.exec if config is not None else ExecCfg()
    limit = max_lines or settings.max_lines
    done = runner(argv, cwd, timeout_s or settings.timeout_s)
    # Keys the config names, and any variable that looks like one: also without a config.
    secrets = configured_secrets(config, environ) if config is not None else []
    redact = Redactor([*secrets, *secret_env_values(environ)])
    text = redact(done.output.decode("utf-8", errors="replace").replace("\r\n", "\n"))
    log = _record(argv, text, done, redact, now)
    lines = text.splitlines()
    result = ExecResult(done.code, len(lines), log, "full", text.rstrip("\n"),
                        timed_out=done.timed_out)  # fmt: skip
    if len(lines) <= limit and len(text) <= limit * CHARS_PER_LINE:
        return result
    digest = outparse.parse(text, cwd=str(cwd))
    if digest is not None:
        result.kind, result.parser, result.headline = "digest", digest.tool, digest.headline
        result.items = digest.items
        body = outparse.render_items(digest)
        result.summary = "\n".join(x for x in (digest.headline, body) if x)
        return result
    wanted = settings.model if use_model is None else use_model
    if wanted and config is not None:
        try:
            answer, label = asyncio.run(_summarize(config, settings, lines, done.code, environ))
        except OrkestraError as exc:
            first = exc.details[0] if exc.details else exc.message
            result.note = _one_line(first or type(exc).__name__)
        else:
            result.kind, result.summary, result.model = "model", answer.strip(), label
            return result
    elif wanted:
        problem = config_problem
        result.note = (
            t("exec.note.config_error", error=problem) if problem else t("exec.note.no_config")
        )
    result.kind, result.summary = "head_tail", _head_tail(lines, limit)
    return result


async def _summarize(
    config: Config,
    settings: ExecCfg,
    lines: list[str],
    code: int,
    environ: Mapping[str, str] | None,
) -> tuple[str, str]:
    tail = "\n".join(lines[-MODEL_LINES:])[-MODEL_CHARS:]
    user = f"exit code: {code}\nlines: {len(lines)} (the last {MODEL_LINES} below)\n\n{tail}"
    return await query_chief_model(
        config, tier=settings.tier, system=SUMMARY_SYSTEM, user=user, environ=environ,
        agents=False, work="summary",
    )  # fmt: skip


def _one_line(text: str, limit: int = NOTE_CHARS) -> str:
    first = (text.strip().splitlines() or [""])[0].strip()
    return first if len(first) <= limit else first[: limit - 1] + "…"


def _head_tail(lines: list[str], limit: int) -> str:
    """The first quarter and the last three quarters of ``limit`` lines, each line cut to
    ``CHARS_PER_LINE`` (one huge line must not come through whole either)."""
    head = max(1, limit // 4)
    tail = max(1, limit - head)
    clipped = [line if len(line) <= CHARS_PER_LINE else line[: CHARS_PER_LINE - 1] + "…"
               for line in lines]  # fmt: skip
    skipped = len(clipped) - head - tail
    if skipped <= 0:
        return "\n".join(clipped)
    return "\n".join([*clipped[:head], t("exec.skipped", count=skipped), *clipped[-tail:]])


def _record(
    argv: list[str], text: str, done: Completed, redact: Redactor, now: datetime | None
) -> Path:
    folder = paths.run_dir(new_run_id(now))
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / LOG_FILE
    log.write_bytes(text.encode("utf-8"))
    meta: dict[str, Any] = {
        "command": [redact(a) for a in argv], "exit_code": done.code,
        "timed_out": done.timed_out, "lines": len(text.splitlines()),
    }  # fmt: skip
    (folder / META_FILE).write_bytes(json.dumps(meta, indent=2).encode("utf-8"))
    return log


def header(result: ExecResult) -> str:
    """The first line the chief reads: exit code, size, how it was shortened, the log."""
    how = result.parser or result.model or t(f"exec.kind.{result.kind}")  # full, head_tail
    return t("exec.header", code=result.exit_code, lines=result.lines, how=how, log=result.log)


def render(result: ExecResult) -> str:
    parts = [header(result)]
    if result.timed_out:
        parts.append(t("exec.timed_out"))
    if result.note:
        parts.append(t("exec.note.fallback", reason=result.note))
    if result.summary:
        parts.append(result.summary)
    return "\n".join(parts)


def to_dict(result: ExecResult) -> dict[str, Any]:
    return {
        "exit_code": result.exit_code, "lines": result.lines, "log": str(result.log),
        "kind": result.kind, "parser": result.parser, "headline": result.headline,
        "items": [{"pointer": i.pointer, "file": i.file, "line": i.line, "text": i.text}
                  for i in result.items],
        "summary": result.summary, "model": result.model, "note": result.note,
        "timed_out": result.timed_out,
    }  # fmt: skip
