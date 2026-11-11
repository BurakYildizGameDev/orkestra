"""Code agents run as subprocesses in the task's workdir (Mimari §5.3-5.5).

Common rules (``run_process``):
- ``asyncio.create_subprocess_exec`` with the full path of the program (``shutil.which``, so
  ``codex.cmd`` works on Windows); never a shell.
- The prompt never goes on the command line (Windows limits it to ~32K characters): it goes
  to stdin, or for agents that cannot read stdin into a file next to the run's records.
- stdout and stderr go to files in the attempt directory, not into memory.
- On timeout, Ctrl+C or cancellation the whole process tree is terminated, then killed
  after ``KILL_GRACE_S``.
- An agent may have a watcher, asked every ``watch_interval_s`` while it runs; when it
  reports an error, the tree is stopped the same way and that error is raised (agy waiting
  for an MCP server that cannot connect, D-055).
- Environment: the parent's, without ``ORKESTRA_*``, plus ``NO_COLOR=1`` and ``CI=1``.

Kinds: ``codex`` (``codex exec``), ``agy`` (Antigravity, experimental), ``generic`` (any
program: prompt on stdin, final message on stdout; used by the test fake agent).
Flags were checked against codex-cli 0.160.0 and agy 1.5.3 (D-044).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import psutil

from orkestra.config.schema import CliAgentProvider
from orkestra.errors import ProviderBadOutput, ProviderError, ProviderTimeout, ProviderUnavailable
from orkestra.i18n import t
from orkestra.providers.base import AgentRequest, AgentResult, Usage

KILL_GRACE_S = 5.0
VERSION_TIMEOUT_S = 15.0
STDERR_TAIL = 500
PROMPT_FILE = "agent_prompt.md"  # agy: the prompt, next to the run's records
STDOUT_FILE = "agent.stdout"
STDERR_FILE = "agent.stderr"
AGENT_LOG = "agent.log"  # agy: its own log (--log-file), next to the run's records
WATCH_INTERVAL_S = 1.0
_AGY_TEXT_KEYS = ("result", "response", "text", "output", "message", "content")
# agy reports every 30 s while MCP servers have not connected; nothing is sent until they do.
_AGY_MCP_STALL = re.compile(r"MCP: \d+ server\(s\) still connecting after \S+: (.+?)\s*$", re.M)

Watcher = Callable[[], "ProviderError | None"]


# --- process handling ------------------------------------------------------------------


def clean_env(environ: Mapping[str, str]) -> dict[str, str]:
    env = {k: v for k, v in environ.items() if not k.upper().startswith("ORKESTRA_")}
    env.update(NO_COLOR="1", CI="1")  # no colours, no interactive prompts
    return env


def kill_tree(pid: int, grace_s: float = KILL_GRACE_S) -> None:
    """Terminate a process and all its descendants; kill what is left after ``grace_s``."""
    try:
        parent = psutil.Process(pid)
        procs = [*parent.children(recursive=True), parent]
    except psutil.Error:
        return
    for proc in procs:
        with contextlib.suppress(psutil.Error):
            proc.terminate()
    _, alive = psutil.wait_procs(procs, timeout=grace_s)
    for proc in alive:
        with contextlib.suppress(psutil.Error):
            proc.kill()
    psutil.wait_procs(alive, timeout=grace_s)


@dataclass(frozen=True)
class Invocation:
    argv: list[str]
    stdin: bytes | None = None


async def _feed_and_wait(proc: asyncio.subprocess.Process, data: bytes | None) -> int:
    if data is not None and proc.stdin is not None:
        try:
            proc.stdin.write(data)
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the agent stopped reading; its exit code tells the rest
        finally:
            proc.stdin.close()
    return await proc.wait()


async def _wait_watched(
    proc: asyncio.subprocess.Process, data: bytes | None, watch: Watcher | None, interval: float
) -> int:
    """The exit code; raises the watcher's error as soon as it reports one."""
    done = asyncio.ensure_future(_feed_and_wait(proc, data))
    if watch is None:
        return await done
    try:
        while True:
            finished, _ = await asyncio.wait({done}, timeout=interval)
            if finished:
                return done.result()
            if (error := watch()) is not None:
                raise error
    finally:
        done.cancel()  # no-op when it finished


async def run_process(
    inv: Invocation,
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_s: float,
    stdout_path: Path,
    stderr_path: Path,
    watch: Watcher | None = None,
    watch_interval_s: float = WATCH_INTERVAL_S,
) -> int:
    """Run ``inv`` and return its exit code (output in the two files)."""
    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
        try:
            proc = await asyncio.create_subprocess_exec(
                *inv.argv,
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.PIPE if inv.stdin is not None else subprocess.DEVNULL,
                stdout=out,
                stderr=err,
            )
        except OSError as exc:
            reason = exc.strerror or type(exc).__name__
            raise ProviderUnavailable(
                t("agent.error.start", command=inv.argv[0], error=reason)
            ) from exc
        try:
            return await asyncio.wait_for(
                _wait_watched(proc, inv.stdin, watch, watch_interval_s), timeout_s
            )
        except TimeoutError:
            await asyncio.to_thread(kill_tree, proc.pid)
            raise ProviderTimeout(t("agent.error.timeout", seconds=timeout_s)) from None
        except ProviderError:  # the watcher stopped it
            await asyncio.to_thread(kill_tree, proc.pid)
            raise
        except BaseException:
            kill_tree(proc.pid)  # Ctrl+C or cancelled: leave nothing running
            raise


def _read(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""


# --- agents ----------------------------------------------------------------------------


class CliAgent:
    """Base class: ``generic`` protocol (prompt on stdin, final message on stdout)."""

    watch_interval_s = WATCH_INTERVAL_S

    def __init__(
        self, name: str, config: CliAgentProvider, environ: Mapping[str, str], *, executable: str
    ) -> None:
        self.name = name
        self.config = config
        self.environ = environ
        self.executable = executable

    def invocation(self, req: AgentRequest) -> Invocation:
        return Invocation([self.executable, *self.config.extra_args], req.prompt.encode("utf-8"))

    def final_message(self, req: AgentRequest, stdout_path: Path) -> str:
        return _read(stdout_path)

    def usage(self, stdout_path: Path) -> Usage:
        return Usage(None, None, None, estimated=True)

    def watcher(self, req: AgentRequest) -> Watcher | None:
        """Asked while the agent runs; an error it returns stops the agent. None: no watcher."""
        return None

    async def run(self, req: AgentRequest) -> AgentResult:
        records = req.output_file.parent
        records.mkdir(parents=True, exist_ok=True)
        stdout_path, stderr_path = records / STDOUT_FILE, records / STDERR_FILE
        code = await run_process(
            self.invocation(req), cwd=req.workdir, env=clean_env(self.environ),
            timeout_s=req.timeout_s, stdout_path=stdout_path, stderr_path=stderr_path,
            watch=self.watcher(req), watch_interval_s=self.watch_interval_s,
        )  # fmt: skip
        if code != 0:
            tail = _read(stderr_path).strip()[-STDERR_TAIL:] or _read(stdout_path)[-STDERR_TAIL:]
            raise ProviderBadOutput(t("agent.error.exit", code=code, detail=tail or "-"))
        message = self.final_message(req, stdout_path)
        if not message.strip():
            raise ProviderBadOutput(t("agent.error.empty", name=self.name))
        return AgentResult(message, code, stdout_path, stderr_path, self.usage(stdout_path))


class CodexAgent(CliAgent):
    """``codex exec`` (Mimari §5.4); the last message comes from ``--output-last-message``."""

    def invocation(self, req: AgentRequest) -> Invocation:
        argv = [
            self.executable, "exec",
            "--cd", str(req.workdir),
            "--sandbox", req.sandbox,
            "--json",
            "--color", "never",
            "--output-last-message", str(req.output_file),
            "--skip-git-repo-check",  # ask tasks may run outside a repository
        ]  # fmt: skip
        model = req.model or self.config.model
        if model:
            argv += ["--model", model]
        argv += [*self.config.extra_args, "-"]  # "-": the prompt comes from stdin
        return Invocation(argv, req.prompt.encode("utf-8"))

    def final_message(self, req: AgentRequest, stdout_path: Path) -> str:
        return _read(req.output_file)

    def usage(self, stdout_path: Path) -> Usage:
        return parse_codex_usage(_read(stdout_path))


def _prompt(name: str) -> str:
    return resources.files("orkestra").joinpath("prompts", name).read_text(encoding="utf-8")


class AgyAgent(CliAgent):
    """Antigravity CLI, experimental and defensive (Mimari §5.5).

    ``agy`` takes the prompt as a flag value, so the prompt is written to a file next to the
    run's records and agy is told to read it (``--add-dir`` gives it access). Print mode runs
    in agy's ``--sandbox``; edits use ``--mode accept-edits``, ask tasks ``--mode plan``.

    agy starts every MCP server in its settings before it sends anything, ignoring their
    ``disabled`` flag in print mode, and waits for all of them to connect. Its log goes next
    to the run's records; when it reports a server still connecting (after 30 s) the run is
    stopped as ``ProviderUnavailable`` naming the servers, so the router moves on (D-055).
    """

    def invocation(self, req: AgentRequest) -> Invocation:
        prompt_file = req.output_file.parent / PROMPT_FILE
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        edit = req.sandbox == "workspace-write"
        # Print mode rejects shell commands; agy then stops with an empty answer (D-048).
        rule = _prompt("agy_edit.md" if edit else "agy_read.md")
        prompt_file.write_bytes(f"{req.prompt}\n\n{rule}".encode())
        mode = "accept-edits" if edit else "plan"
        argv = [
            self.executable,
            "--output-format", "json",
            "--sandbox",
            "--disable-slash-commands",
            "--mode", mode,
            "--print-timeout", f"{int(req.timeout_s)}s",
            "--add-dir", str(prompt_file.parent),
            "--log-file", str(prompt_file.parent / AGENT_LOG),
        ]  # fmt: skip
        model = req.model or self.config.model
        if model:
            argv += ["--model", model]
        pointer = (
            f"Read the file {prompt_file} and follow the instructions in it exactly. "
            "Work in the current directory."
        )
        return Invocation([*argv, *self.config.extra_args, "--print", pointer])

    def final_message(self, req: AgentRequest, stdout_path: Path) -> str:
        return parse_agy_output(_read(stdout_path))

    def watcher(self, req: AgentRequest) -> Watcher:
        log = req.output_file.parent / AGENT_LOG

        def check() -> ProviderError | None:
            servers = agy_mcp_stall(_read(log))
            if not servers:
                return None
            return ProviderUnavailable(
                t("agent.error.agy_mcp_stall", servers=", ".join(servers), log=log)
            )

        return check


_KINDS: dict[str, type[CliAgent]] = {"codex": CodexAgent, "agy": AgyAgent, "generic": CliAgent}


def _which(command: str, environ: Mapping[str, str]) -> str | None:
    """Full path of the agent program (``codex.cmd`` on Windows); tests replace this."""
    return shutil.which(command, path=environ.get("PATH"))


def find_program(command: str, environ: Mapping[str, str]) -> str | None:
    return _which(command, environ)


def create_agent(name: str, config: CliAgentProvider, environ: Mapping[str, str]) -> CliAgent:
    """The adapter for ``config``; ``ProviderUnavailable`` when the program is not installed."""
    executable = _which(config.command, environ)
    if executable is None:
        raise ProviderUnavailable(t("agent.error.not_found", command=config.command))
    return _KINDS[config.kind or "generic"](name, config, environ, executable=executable)


# --- agent setup checks (doctor, consent) ----------------------------------------------

AGY_SETTINGS = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
AGY_MCP_CONFIG = Path.home() / ".gemini" / "config" / "mcp_config.json"  # read by agy 1.5.5
AGY_MUST_DENY = ("rm", "sudo")  # print mode approves tool calls by itself (Mimari §5.5)


def agy_disabled_mcp_servers(config: Path = AGY_MCP_CONFIG) -> list[str]:
    """MCP servers marked ``disabled`` in agy's config; print mode starts them anyway."""
    try:
        data = json.loads(config.read_bytes())
    except (OSError, ValueError):
        return []
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return []
    return [
        name for name, server in servers.items()
        if isinstance(server, dict) and server.get("disabled") is True
    ]  # fmt: skip


def agy_deny_gaps(settings: Path = AGY_SETTINGS) -> list[str]:
    """Commands from ``AGY_MUST_DENY`` that agy's ``permissions.deny`` list does not block.

    A command counts as blocked when an entry names it as a whole word (``Bash(rm:*)``,
    ``rm -rf``), not as part of another word (``npm run format``).
    """
    try:
        data = json.loads(settings.read_bytes())
    except (OSError, ValueError):
        return list(AGY_MUST_DENY)
    permissions = data.get("permissions") if isinstance(data, dict) else None
    deny = permissions.get("deny") if isinstance(permissions, dict) else None
    entries = [str(e) for e in deny] if isinstance(deny, list) else []
    return [
        cmd for cmd in AGY_MUST_DENY
        if not any(re.search(rf"(?<![\w-]){cmd}(?![\w-])", entry, re.I) for entry in entries)
    ]  # fmt: skip


def codex_logged_in(executable: str) -> bool | None:
    """``codex login status``: ``None`` when the question cannot be asked."""
    try:
        done = subprocess.run(
            [executable, "login", "status"], capture_output=True, stdin=subprocess.DEVNULL,
            timeout=VERSION_TIMEOUT_S, check=False,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.returncode == 0


# --- output parsing --------------------------------------------------------------------


def _find_usage(value: Any) -> dict[str, Any] | None:
    """The last ``{input_tokens, output_tokens}`` object anywhere in a JSON value."""
    found: dict[str, Any] | None = None
    if isinstance(value, dict):
        if "input_tokens" in value and "output_tokens" in value:
            found = value
        for item in value.values():
            found = _find_usage(item) or found
    elif isinstance(value, list):
        for item in value:
            found = _find_usage(item) or found
    return found


def parse_codex_usage(jsonl: str) -> Usage:
    """Token counts from ``codex exec --json`` events, when a version reports them.

    The event format changes between versions, so the numbers are only estimates; budgets
    for agents work through ``daily_runs`` (Mimari §5.4).
    """
    usage: dict[str, Any] | None = None
    for line in jsonl.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        usage = _find_usage(event) or usage
    if usage is None:
        return Usage(None, None, None, estimated=True)
    prompt, completion = usage.get("input_tokens"), usage.get("output_tokens")
    return Usage(
        prompt if isinstance(prompt, int) else None,
        completion if isinstance(completion, int) else None,
        None,
        estimated=True,
    )


def _text_of(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in _AGY_TEXT_KEYS:
            if key in value and (text := _text_of(value[key])) is not None:
                return text
    if isinstance(value, list):
        texts = [text for item in value if (text := _text_of(item))]
        return texts[-1] if texts else None
    return None


def agy_mcp_stall(log: str) -> list[str]:
    """MCP servers agy's log reports as still connecting (latest report); empty: none."""
    reports = _AGY_MCP_STALL.findall(log)
    if not reports:
        return []
    return [name.strip() for name in reports[-1].split(",") if name.strip()]


def parse_agy_output(stdout: str) -> str:
    """The final answer from ``agy --output-format json``; plain text is taken as it is."""
    stripped = stdout.strip()
    if not stripped:
        return ""
    try:
        data = json.loads(stripped)
    except ValueError:
        return stripped
    return (_text_of(data) or "").strip()
