"""`doctor --mcp` (Faz 6b): start agy's MCP servers, try the `initialize` handshake.

Every server here is a fake stdio server (a small Python script): the probe never starts the
developer's real servers.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import psutil
import pytest

from orkestra import doctor
from orkestra.providers import mcp_probe

SERVERS = {
    "good": """
import json, sys
sys.stderr.write("starting\\n"); sys.stderr.flush()
request = json.loads(sys.stdin.readline())
print(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                  "result": {"protocolVersion": "2025-06-18",
                             "serverInfo": {"name": "fake-unity", "version": "1.0"}}}),
      flush=True)
sys.stdin.readline()
""",
    "silent": "import time\ntime.sleep(60)\n",
    "exits": "import sys\nsys.exit(3)\n",
    "garbage": "print('hello, this is not json', flush=True)\nimport time\ntime.sleep(60)\n",
    "detached": "import os, sys, time\nsys.stdout.flush()\nos.close(1)\ntime.sleep(60)\n",
}


def _server(tmp_path: Path, kind: str) -> mcp_probe.McpServer:
    script = tmp_path / f"{kind}.py"
    script.write_text(SERVERS[kind], encoding="utf-8")
    return mcp_probe.McpServer(kind, sys.executable, (str(script),))


def _probe(server: mcp_probe.McpServer, timeout_s: float = 5.0) -> mcp_probe.ProbeResult:
    return asyncio.run(mcp_probe.probe_server(server, timeout_s=timeout_s))


def test_a_server_that_answers_initialize_is_ok(tmp_path: Path) -> None:
    result = _probe(_server(tmp_path, "good"))
    assert result.status == "ok" and result.detail == "fake-unity"


def test_a_silent_server_times_out_and_its_process_tree_is_gone(tmp_path: Path) -> None:
    result = _probe(_server(tmp_path, "silent"), timeout_s=1.0)
    assert result.status == "timeout"
    assert result.pid is not None and not psutil.pid_exists(result.pid)


def test_a_server_that_exits_at_once_is_reported_with_its_code(tmp_path: Path) -> None:
    result = _probe(_server(tmp_path, "exits"))
    assert result.status == "exited" and result.detail == "3"


def test_a_server_that_writes_no_json_is_bad_output(tmp_path: Path) -> None:
    result = _probe(_server(tmp_path, "garbage"))
    assert result.status == "bad_output"
    assert result.pid is not None and not psutil.pid_exists(result.pid)


def test_a_missing_command_is_an_error_not_a_crash(tmp_path: Path) -> None:
    result = _probe(mcp_probe.McpServer("ghost", str(tmp_path / "no-such-program"), ()))
    assert result.status == "error"


def test_servers_are_probed_together(tmp_path: Path) -> None:
    servers = [_server(tmp_path, "silent"), _server(tmp_path, "good")]
    results = asyncio.run(mcp_probe.probe_all(servers, timeout_s=1.5))
    assert [(r.name, r.status) for r in results] == [("silent", "timeout"), ("good", "ok")]


def test_agy_config_gives_enabled_stdio_servers_and_skips_the_rest(tmp_path: Path) -> None:
    config = tmp_path / "mcp_config.json"
    config.write_text(json.dumps({"mcpServers": {
        "unity": {"command": "unity-mcp-guard.cmd", "args": ["--mcp"], "env": {"A": "1"}},
        "old": {"command": "x", "disabled": True},
        "web": {"serverUrl": "https://example.invalid/mcp"},
        "broken": "not an object",
    }}), encoding="utf-8")  # fmt: skip
    servers = mcp_probe.agy_mcp_servers(config)
    assert servers == [mcp_probe.McpServer("unity", "unity-mcp-guard.cmd", ("--mcp",),
                                           (("A", "1"),))]  # fmt: skip
    assert mcp_probe.agy_mcp_servers(tmp_path / "missing.json") == []


@pytest.mark.parametrize(
    ("resolved", "platform", "expected"),
    [
        ("C:/x/npx.CMD", "win32", ["cmd.exe", "/d", "/c", "C:/x/npx.CMD", "-y", "srv"]),
        ("C:/x/guard.bat", "win32", ["cmd.exe", "/d", "/c", "C:/x/guard.bat", "-y", "srv"]),
        ("C:/x/node.exe", "win32", ["C:/x/node.exe", "-y", "srv"]),
        ("/usr/bin/npx", "linux", ["/usr/bin/npx", "-y", "srv"]),
    ],
)
def test_windows_batch_files_start_through_cmd(
    resolved: str, platform: str, expected: list[str]
) -> None:
    server = mcp_probe.McpServer("s", "npx", ("-y", "srv"))
    assert mcp_probe.server_argv(server, which=lambda _: resolved, platform=platform) == expected


# --- doctor ---------------------------------------------------------------------------------

CONFIG = """
version: 1
providers:
  agy:
    type: cli_agent
    command: agy
    kind: agy
    experimental: true
"""


def _doctor(tmp_path: Path, mcp: bool, prober: object) -> doctor.DoctorReport:
    config = tmp_path / "config.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    mcp_config = tmp_path / "mcp_config.json"
    mcp_config.write_text(json.dumps({"mcpServers": {"unity": {"command": "u"},
                                                     "blender": {"command": "b"}}}),
                          encoding="utf-8")  # fmt: skip
    return asyncio.run(doctor.run_doctor(
        config_flag=config, environ={}, cwd=tmp_path, which=lambda name: name,
        probe=lambda _: "1.5.13", agy_mcp_config=mcp_config, agy_settings=tmp_path / "s.json",
        mcp=mcp, mcp_prober=prober,  # type: ignore[arg-type]
    ))  # fmt: skip


def test_doctor_starts_no_mcp_server_without_the_flag(tmp_path: Path) -> None:
    called: list[object] = []

    async def prober(servers: list[mcp_probe.McpServer], timeout_s: float) -> list[object]:
        called.append(servers)
        return []

    report = _doctor(tmp_path, mcp=False, prober=prober)
    assert called == [] and not any(":mcp:" in c.name for c in report.checks)


def test_doctor_mcp_reports_each_server_by_name(tmp_path: Path) -> None:
    async def prober(
        servers: list[mcp_probe.McpServer], timeout_s: float
    ) -> list[mcp_probe.ProbeResult]:
        assert [s.name for s in servers] == ["unity", "blender"]
        return [mcp_probe.ProbeResult("unity", "timeout", "", None),
                mcp_probe.ProbeResult("blender", "ok", "blender-mcp", None)]  # fmt: skip

    report = _doctor(tmp_path, mcp=True, prober=prober)
    checks = {c.name: c for c in report.checks if ":mcp:" in c.name}
    assert checks["provider:agy:mcp:unity"].status == "warn"
    assert "unity" in checks["provider:agy:mcp:unity"].message
    assert checks["provider:agy:mcp:blender"].status == "ok"
    assert checks["provider:agy:mcp:unity"].data == {"server": "unity", "status": "timeout"}


def test_a_server_that_exits_at_once_is_info_not_a_stall(tmp_path: Path) -> None:
    """A guard script that exits while its app is closed: agy does not wait for it."""

    async def prober(
        servers: list[mcp_probe.McpServer], timeout_s: float
    ) -> list[mcp_probe.ProbeResult]:
        return [mcp_probe.ProbeResult("unity", "exited", "1", None),
                mcp_probe.ProbeResult("blender", "ok", "", None)]  # fmt: skip

    report = _doctor(tmp_path, mcp=True, prober=prober)
    unity = next(c for c in report.checks if c.name == "provider:agy:mcp:unity")
    assert unity.status == "info" and "mcp_wait_s" not in unity.message


def test_a_server_that_closes_stdout_but_lives_on_does_not_hang_the_probe(tmp_path: Path) -> None:
    """PR #46 review: after stdout's EOF the wait for the exit code must be bounded too."""
    started = time.monotonic()  # the limit leaves a slow CI runner time to start Python
    result = _probe(_server(tmp_path, "detached"), timeout_s=20.0)
    assert time.monotonic() - started < 40  # the server sleeps 60 s: no unbounded wait
    assert result.status == "bad_output"
    assert result.pid is not None and not psutil.pid_exists(result.pid)
