"""MCP probe for ``doctor --mcp`` (Faz 6b): does each of agy's MCP servers answer?

agy waits for every MCP server in its config before it answers (D-055). A server that cannot
connect (Unity closed, a wrapper overwritten by Unity's "configure MCP clients" button) stalls
every agy run until ``mcp_wait_s``. The probe starts each enabled stdio server, sends the
JSON-RPC ``initialize`` request and waits briefly for the answer. It starts the user's real
servers, so ``doctor`` runs it only when asked (``--mcp``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from orkestra.providers.cli_agent import AGY_MCP_CONFIG, kill_tree

DEFAULT_TIMEOUT_S = 15.0  # npx/uvx servers can take a while on the first start
PROTOCOL_VERSION = "2025-06-18"
WINDOWS_BATCH = (".cmd", ".bat")

Status = Literal["ok", "timeout", "exited", "bad_output", "error"]


@dataclass(frozen=True)
class McpServer:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ProbeResult:
    name: str
    status: Status
    detail: str  # server name (ok), exit code (exited), error text (error)
    pid: int | None


Prober = Callable[[list[McpServer], float], Awaitable[list[ProbeResult]]]


def agy_mcp_servers(config: Path = AGY_MCP_CONFIG) -> list[McpServer]:
    """Enabled stdio servers in agy's MCP config; URL servers and broken entries are skipped,
    and a missing or unreadable file gives none."""
    try:
        data = json.loads(config.read_bytes())
    except (OSError, ValueError):
        return []
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return []
    found: list[McpServer] = []
    for name, entry in servers.items():
        if not isinstance(entry, dict) or entry.get("disabled") is True:
            continue
        command = entry.get("command")
        if not isinstance(command, str) or not command:
            continue
        raw_args, raw_env = entry.get("args"), entry.get("env")
        args = raw_args if isinstance(raw_args, list) else []
        env = raw_env if isinstance(raw_env, dict) else {}
        found.append(McpServer(
            str(name), command, tuple(str(a) for a in args),
            tuple((str(k), str(v)) for k, v in env.items()),
        ))  # fmt: skip
    return found


def server_argv(
    server: McpServer,
    *,
    which: Callable[[str], str | None] = shutil.which,
    platform: str = sys.platform,
) -> list[str]:
    """The command line; on Windows a ``.cmd``/``.bat`` (``npx`` is ``npx.cmd``) starts
    through ``cmd.exe /d /c``, which agy needs too (D-055)."""
    resolved = which(server.command) or server.command
    if platform == "win32" and resolved.lower().endswith(WINDOWS_BATCH):
        return ["cmd.exe", "/d", "/c", resolved, *server.args]
    return [resolved, *server.args]


def _initialize() -> bytes:
    request = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                   "clientInfo": {"name": "orkestra-doctor", "version": "1"}},
    }  # fmt: skip
    return (json.dumps(request) + "\n").encode("utf-8")


async def _answer(stdout: asyncio.StreamReader) -> tuple[Status, str]:
    """Read lines until the answer to ``initialize`` (MCP stdio: one JSON message a line)."""
    while True:
        line = await stdout.readline()
        if not line:
            return "exited", ""
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except ValueError:
            return "bad_output", ""
        if isinstance(message, dict) and message.get("id") == 1:
            if "error" in message:
                return "bad_output", ""
            result = message.get("result")
            info = result.get("serverInfo") if isinstance(result, dict) else None
            name = info.get("name") if isinstance(info, dict) else None
            return "ok", str(name or "")
        # a notification or a log message: keep reading


async def probe_server(server: McpServer, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> ProbeResult:
    """Start ``server``, send ``initialize``, wait at most ``timeout_s``; the process tree is
    always stopped afterwards. stderr is ignored (servers log there)."""
    env = {**os.environ, **dict(server.env)}
    try:
        proc = await asyncio.create_subprocess_exec(
            *server_argv(server), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env,
        )  # fmt: skip
    except OSError as exc:
        return ProbeResult(server.name, "error", type(exc).__name__, None)
    assert proc.stdin is not None and proc.stdout is not None
    try:
        with contextlib.suppress(OSError):  # a server that already exited
            proc.stdin.write(_initialize())
            await proc.stdin.drain()
        try:
            status, detail = await asyncio.wait_for(_answer(proc.stdout), timeout_s)
        except TimeoutError:
            status, detail = "timeout", ""
        if status == "exited":
            code = await proc.wait()
            detail = str(code)
        return ProbeResult(server.name, status, detail, proc.pid)
    finally:
        if proc.returncode is None:
            await asyncio.to_thread(kill_tree, proc.pid)
            with contextlib.suppress(ProcessLookupError):
                await proc.wait()


async def probe_all(
    servers: Sequence[McpServer], timeout_s: float = DEFAULT_TIMEOUT_S
) -> list[ProbeResult]:
    """Probe every server at the same time; results in the given order."""
    return list(await asyncio.gather(*(probe_server(s, timeout_s=timeout_s) for s in servers)))
