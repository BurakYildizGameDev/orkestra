"""Code agents as subprocesses (Mimari §5.3-5.5, Faz 6), driven by ``fixtures/fake_agent.py``."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import psutil
import pytest

from orkestra.config.schema import CliAgentProvider
from orkestra.errors import ProviderBadOutput, ProviderTimeout, ProviderUnavailable
from orkestra.providers import cli_agent as ca
from orkestra.providers.base import AgentRequest

FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_agent.py"


def _generic(mode: str, **fields: object) -> CliAgentProvider:
    return CliAgentProvider.model_validate(
        {"type": "cli_agent", "command": sys.executable, "kind": "generic",
         "extra_args": [str(FAKE), mode], **fields}
    )  # fmt: skip


def _request(tmp_path: Path, prompt: str = "do it", **fields: object) -> AgentRequest:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    attempt = tmp_path / "attempt"
    attempt.mkdir(exist_ok=True)
    data: dict[str, object] = {
        "prompt": prompt, "workdir": work, "model": None, "sandbox": "workspace-write",
        "timeout_s": 30, "output_file": attempt / "agent_output.md", **fields,
    }  # fmt: skip
    return AgentRequest(**data)  # type: ignore[arg-type]


def _dead(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


# --- the subprocess --------------------------------------------------------------------


def test_the_final_message_comes_back(tmp_path: Path) -> None:
    agent = ca.create_agent("fake", _generic("echo"), os.environ)
    result = asyncio.run(agent.run(_request(tmp_path)))
    assert result.final_message.strip() == "received 5 chars"
    assert result.exit_code == 0 and result.stdout_path.is_file()


def test_a_50_kb_prompt_goes_through_stdin(tmp_path: Path) -> None:
    agent = ca.create_agent("fake", _generic("echo"), os.environ)
    result = asyncio.run(agent.run(_request(tmp_path, prompt="x" * 50_000)))
    assert result.final_message.strip() == "received 50000 chars"


def test_timeout_kills_the_whole_process_tree(tmp_path: Path) -> None:
    pids_file = tmp_path / "pids.txt"
    env = {**os.environ, "FAKE_AGENT_PIDS": str(pids_file)}
    agent = ca.create_agent("fake", _generic("hang"), env)
    with pytest.raises(ProviderTimeout):
        asyncio.run(agent.run(_request(tmp_path, timeout_s=4)))
    parent, child = map(int, pids_file.read_text(encoding="utf-8").split())
    assert _dead(parent) and _dead(child)


def test_cancelling_kills_the_whole_process_tree(tmp_path: Path) -> None:
    pids_file = tmp_path / "pids.txt"
    env = {**os.environ, "FAKE_AGENT_PIDS": str(pids_file)}
    agent = ca.create_agent("fake", _generic("hang"), env)

    async def scenario() -> None:
        task = asyncio.ensure_future(agent.run(_request(tmp_path, timeout_s=120)))
        for _ in range(200):
            if pids_file.exists() and pids_file.read_text(encoding="utf-8").strip():
                break
            await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    parent, child = map(int, pids_file.read_text(encoding="utf-8").split())
    assert _dead(parent) and _dead(child)


def test_empty_output_is_bad_output(tmp_path: Path) -> None:
    agent = ca.create_agent("fake", _generic("empty"), os.environ)
    with pytest.raises(ProviderBadOutput):
        asyncio.run(agent.run(_request(tmp_path)))


def test_a_failing_agent_reports_its_stderr(tmp_path: Path) -> None:
    agent = ca.create_agent("fake", _generic("fail"), os.environ)
    with pytest.raises(ProviderBadOutput) as exc_info:
        asyncio.run(agent.run(_request(tmp_path)))
    assert "3" in exc_info.value.message and "boom" in exc_info.value.message


def test_a_missing_command_is_unavailable() -> None:
    cfg = CliAgentProvider.model_validate({"type": "cli_agent", "command": "no-such-agent-x"})
    with pytest.raises(ProviderUnavailable):
        ca.create_agent("x", cfg, os.environ)


def test_clean_env() -> None:
    env = ca.clean_env({"PATH": "/bin", "ORKESTRA_HOME": "/h", "orkestra_lang": "tr"})
    assert env["PATH"] == "/bin" and env["NO_COLOR"] == "1" and env["CI"] == "1"
    assert not any(k.upper().startswith("ORKESTRA_") for k in env)


# --- codex -----------------------------------------------------------------------------


def _codex(**fields: object) -> ca.CodexAgent:
    cfg = CliAgentProvider.model_validate({"type": "cli_agent", "command": "codex", **fields})
    return ca.CodexAgent("codex", cfg, {}, executable="/bin/codex")


def test_codex_arguments(tmp_path: Path) -> None:
    agent = _codex(model="gpt-5-codex", extra_args=["-c", "x=1"])
    req = _request(tmp_path, prompt="fix it", output_schema=tmp_path / "s.json")
    inv = agent.invocation(req)
    argv = inv.argv
    assert argv[:2] == ["/bin/codex", "exec"] and argv[-1] == "-"
    assert argv[argv.index("--cd") + 1] == str(req.workdir)
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert argv[argv.index("--output-last-message") + 1] == str(req.output_file)
    assert argv[argv.index("--model") + 1] == "gpt-5-codex"
    assert argv[argv.index("--output-schema") + 1] == str(tmp_path / "s.json")
    assert "--json" in argv and "--skip-git-repo-check" in argv and "-c" in argv
    assert "fix it" not in argv and inv.stdin == b"fix it"
    assert not any("danger" in a for a in argv)


def test_codex_final_message_and_usage(tmp_path: Path) -> None:
    agent = _codex()
    req = _request(tmp_path)
    req.output_file.write_bytes("Değiştirdim.\n".encode())
    events = [
        {"type": "thread.started", "thread_id": "t"},
        {"type": "turn.completed", "usage": {"input_tokens": 1200, "output_tokens": 300}},
    ]
    stdout = tmp_path / "attempt" / "agent.stdout"
    stdout.write_bytes("\n".join(json.dumps(e) for e in events).encode() + b"\nnot json\n")
    assert agent.final_message(req, stdout) == "Değiştirdim.\n"
    usage = agent.usage(stdout)
    assert (usage.prompt_tokens, usage.completion_tokens, usage.estimated) == (1200, 300, True)
    assert ca.CodexAgent.usage(agent, tmp_path / "missing").prompt_tokens is None


# --- agy -------------------------------------------------------------------------------


def _agy(**fields: object) -> ca.AgyAgent:
    cfg = CliAgentProvider.model_validate(
        {"type": "cli_agent", "command": "agy", "experimental": True, **fields}
    )
    return ca.AgyAgent("agy", cfg, {}, executable="/bin/agy")


def test_agy_gets_the_prompt_from_a_file_outside_the_workdir(tmp_path: Path) -> None:
    req = _request(tmp_path, prompt="a long prompt " * 1000)
    inv = _agy(model="gemini-3").invocation(req)
    prompt_file = req.output_file.parent / ca.PROMPT_FILE
    assert prompt_file.read_bytes().decode() == req.prompt
    assert not (req.workdir / ca.PROMPT_FILE).exists()
    assert all(req.prompt not in a for a in inv.argv) and inv.stdin is None
    argv = inv.argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--mode") + 1] == "accept-edits"
    assert argv[argv.index("--add-dir") + 1] == str(prompt_file.parent)
    assert "--sandbox" in argv and "--dangerously-skip-permissions" not in argv
    read_only = _agy().invocation(_request(tmp_path, sandbox="read-only")).argv
    assert read_only[read_only.index("--mode") + 1] == "plan"


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ('{"result": "done"}', "done"),
        ('{"response": {"text": "nested"}}', "nested"),
        ("plain answer\n", "plain answer"),
        ("", ""),
    ],
)
def test_agy_output(stdout: str, expected: str) -> None:
    assert ca.parse_agy_output(stdout) == expected


# --- doctor checks ---------------------------------------------------------------------


def test_agy_deny_gaps(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    assert ca.agy_deny_gaps(settings) == ["rm", "sudo"]  # no file: nothing is blocked
    settings.write_text(json.dumps({"permissions": {"deny": ["Bash(rm -rf:*)"]}}),
                        encoding="utf-8")  # fmt: skip
    assert ca.agy_deny_gaps(settings) == ["sudo"]


def test_doctor_warns_about_codex_login_and_agy_deny_list(tmp_path: Path) -> None:
    from orkestra import doctor

    codex = CliAgentProvider.model_validate({"type": "cli_agent", "command": "codex"})
    checks = doctor._check_agent(
        "codex", codex, lambda _: "/bin/codex", lambda _: "codex-cli 0.160.0",
        login=lambda _: False,
    )  # fmt: skip
    assert [c.status for c in checks] == ["info", "warn"]
    agy = CliAgentProvider.model_validate(
        {"type": "cli_agent", "command": "agy", "experimental": True}
    )
    checks = doctor._check_agent(
        "agy", agy, lambda _: "/bin/agy", lambda _: "1.5.3",
        agy_settings=tmp_path / "missing.json",
    )  # fmt: skip
    assert checks[-1].status == "warn" and "sudo" in checks[-1].message
