"""Continuity when an AI runs out of quota (Faz 13f), with no network.

The scenario the user cares about: a code agent (the fake, standing in for agy or codex) does
the work until its quota runs out at task 4 of 10. Every task must still finish, the rest on
Ollama, the agent must not be started again, and everything that shows provider state must
say why it is paused and until when.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from orkestra import doctor
from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.i18n import t
from orkestra.providers.base import CompletionRequest, CompletionResult, Usage
from orkestra.providers.ollama import OllamaChat
from orkestra.state import consent, db, health

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_agent.py"
TASKS = 10
QUOTA_AT = 4
RESET = timedelta(hours=5, minutes=19)  # the reset time in the fake agent's message


def _config(fake_args: list[str]) -> dict[str, Any]:
    return {
        "version": 1,
        "notify": {"desktop": False, "ntfy_topic_env": "ORK_TEST_TOPIC"},
        "providers": {
            # Listed first on the same tier: the agent gets every task while it can.
            "agent": {"type": "cli_agent", "command": sys.executable, "kind": "generic",
                      "tier": 1, "extra_args": fake_args},
            "ollama": {"type": "ollama", "base_url": "http://ollama.test:11434",
                       "models": [{"id": "coder", "tier": 1}]},
        },
    }  # fmt: skip


class FakeOllama:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        self.calls.append(req.user)
        await asyncio.sleep(0)
        return CompletionResult("fine", Usage(10, 5, 0.0), "stop")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeOllama:
    worker = FakeOllama()

    async def complete(self: OllamaChat, req: CompletionRequest) -> CompletionResult:
        return await worker.complete(req)

    monkeypatch.setattr(OllamaChat, "complete", complete)
    return worker


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    config = _config([str(FAKE), "quota_after"])
    (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")  # JSON is YAML
    folder = tmp_path / "work"
    folder.mkdir()
    monkeypatch.chdir(folder)
    monkeypatch.setenv("FAKE_AGENT_COUNTER", str(tmp_path / "agent-runs.txt"))
    monkeypatch.setenv("FAKE_AGENT_QUOTA_AT", str(QUOTA_AT))
    monkeypatch.setenv("ORK_TEST_TOPIC", "night-topic")
    loaded = load_config(cwd=folder, environ={}).config
    with closing(db.connect()) as conn:
        for name, provider in loaded.providers.items():
            consent.grant(conn, name, provider, db.local_now())
    return folder


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


def _batch(work: Path) -> str:
    tasks = [{"id": f"t{n:02d}", "kind": "ask", "prompt": f"question {n}"}
             for n in range(1, TASKS + 1)]  # fmt: skip
    path = work / "batch.json"
    path.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
    return str(path)


def _agent_runs(tmp_path: Path) -> int:
    return int((tmp_path / "agent-runs.txt").read_text(encoding="utf-8"))


def test_the_agent_runs_out_at_task_4_and_all_ten_finish_on_ollama(
    work: Path, tmp_path: Path, fake: FakeOllama, capsys: pytest.CaptureFixture[str],
    no_real_notifications: list[tuple[str, ...]],
) -> None:  # fmt: skip
    started = time.monotonic()
    code, out, err = _run(["batch", _batch(work), "--parallel", "1", "--notify", "--json"], capsys)
    elapsed = time.monotonic() - started
    assert code == 0, out + err
    doc = json.loads(out)
    results = {item["task_id"]: item["envelope"] for item in doc["results"]}
    assert doc["totals"]["ok"] == TASKS

    # The agent did 1-3, ran out on 4 and was never started again.
    assert _agent_runs(tmp_path) == QUOTA_AT
    assert [results[f"t{n:02d}"]["provider"] for n in range(1, QUOTA_AT)] == ["agent"] * 3
    assert all(results[f"t{n:02d}"]["provider"] == "ollama" for n in range(QUOTA_AT, TASKS + 1))
    assert len(fake.calls) == TASKS - QUOTA_AT + 1

    # Task 4 moved on in the same command and says why.
    failovers = results[f"t{QUOTA_AT:02d}"]["failovers"]
    assert [(f["provider"], f["error"]) for f in failovers] == [("agent", "ProviderQuotaExhausted")]
    assert "usage limit" in failovers[0]["reason"]
    # The later tasks did not even try it: no failover, no wasted run.
    assert all(not results[f"t{n:02d}"]["failovers"] for n in range(QUOTA_AT + 1, TASKS + 1))

    # Paused until the reset time in the agent's message.
    with closing(db.connect()) as conn:
        state = health.get(conn, "agent")
    assert state.reason == "quota" and state.open_until is not None
    expected = db.local_now() + RESET
    assert abs((state.open_until - expected).total_seconds()) < elapsed + 60

    # One notification line names the paused provider, nothing of the work.
    assert len(no_real_notifications) == 1
    message = no_real_notifications[0][2]
    assert message.startswith(t("notify.counts", finished=TASKS, failed=0))
    assert "agent" in message and "question" not in message


def test_paused_for_quota_shows_everywhere_and_enable_lifts_it(
    work: Path, tmp_path: Path, fake: FakeOllama, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(["batch", _batch(work), "--parallel", "1", "--json"], capsys)
    with closing(db.connect()) as conn:
        until = health.until_text(health.get(conn, "agent").open_until, db.local_now())  # type: ignore[arg-type]

    code, out, _ = _run(["providers", "list"], capsys)
    assert t("providers.quota_paused", until=until) in out

    code, out, _ = _run(["status"], capsys)
    assert t("status.health.quota_item", name="agent", until=until) in out

    code, out, _ = _run(["providers", "list", "--json"], capsys)
    rows = {row["name"]: row for row in json.loads(out)["providers"]}
    assert rows["agent"]["health"]["reason"] == "quota"

    config = load_config(cwd=work, environ={}).config
    checks = doctor._state_checks(config.providers)
    texts = [c.message for c in checks if c.name == "provider:agent"]
    assert any(text.startswith(t("doctor.quota_paused", until=until, error="")[:20])
               for text in texts), texts  # fmt: skip

    code, out, _ = _run(["ask", "anything", "--dry-run", "--json"], capsys)
    eliminated = {e["provider"]: e["code"] for e in json.loads(out)["eliminated"]}
    assert eliminated["agent"] == "quota_paused"

    code, _, err = _run(["providers", "enable", "agent", "--yes"], capsys)
    assert code == 0, err
    with closing(db.connect()) as conn:
        assert not health.get(conn, "agent").is_open(db.local_now())
