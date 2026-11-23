"""Tests for loop without progress stopping and agents_only routing (Faz 13r-b2)."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx
from conftest import git

from orkestra.config.schema import Config
from orkestra.errors import NoProviderAvailable
from orkestra.routing import router
from orkestra.routing.router import TaskNeeds
from orkestra.state import consent, db
from orkestra.tasks import delegate, runner, spec

START = datetime(2026, 11, 23, 10, 0).astimezone()


def test_task_spec_agents_only_field() -> None:
    task = spec.parse_task(
        {"id": "t1", "kind": "edit", "prompt": "do something"},
        source="test",
    )
    assert task.agents_only is False

    task_agents = spec.parse_task(
        {"id": "t2", "kind": "edit", "prompt": "do something", "agents_only": True},
        source="test",
    )
    assert task_agents.agents_only is True


def test_router_agents_only_filters_chat_workers() -> None:
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "ollama": {
                    "type": "ollama",
                    "base_url": "http://127.0.0.1:11434",
                    "models": [{"id": "llama", "tier": 1}],
                },
                "codex": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "codex",
                    "tier": 1,
                },
            },
        }
    )
    now = datetime(2026, 11, 23, 12, 0).astimezone()
    snap = router.Snapshot(
        now=now,
        providers={
            "ollama": router.ProviderState(consent="granted"),
            "codex": router.ProviderState(consent="granted", installed=True),
        },
    )

    # When agents_only is False, both are candidates
    route_normal = router.route(TaskNeeds(kind="edit", tier=1, agents_only=False), cfg, snap)
    assert len(route_normal.candidates) == 2
    assert [c.provider for c in route_normal.candidates] == ["ollama", "codex"]

    # When agents_only is True, ollama is eliminated with code="agents_only"
    route_agents = router.route(TaskNeeds(kind="edit", tier=1, agents_only=True), cfg, snap)
    assert len(route_agents.candidates) == 1
    assert route_agents.candidates[0].provider == "codex"
    elim = [e for e in route_agents.eliminated if e.provider == "ollama"]
    assert len(elim) == 1
    assert elim[0].code == "agents_only"
    assert "agents_only" in elim[0].reason


@pytest.mark.asyncio
async def test_chat_worker_progress_continues_and_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "calc.py").write_text("def a(): return 0\ndef b(): return 0\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    call_count = 0

    def chat_mock(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            content = "def a(): return 0\ndef b(): return 0\n"
        elif call_count == 2:
            content = "def a(): return 1\ndef b(): return 0\n"
        else:
            content = "def a(): return 1\ndef b(): return 1\n"
        body = json.dumps({"files": [{"path": "calc.py", "content": content}]})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": body}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10},
            },
        )

    task_data = {
        "id": "chat-prog",
        "kind": "edit",
        "prompt": "fix a and b",
        "context": {"files": ["calc.py"]},
        "provider": "chat",
        "limits": {"max_retries": 5},
        "verify": [
            {
                "type": "command",
                "run": f'"{sys.executable}" -c "import calc; assert calc.a() == 1"',
            },
            {
                "type": "command",
                "run": f'"{sys.executable}" -c "import calc; assert calc.b() == 1"',
            },
        ],
    }
    task = spec.parse_task(task_data, source="test")
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "chat": {
                    "type": "openai_compat",
                    "base_url": "https://api.test/v1",
                    "api_key_env": "TEST_KEY",
                    "models": [{"id": "model-1", "tier": 1, "edit_format": "whole"}],
                }
            },
        }
    )
    monkeypatch.setenv("TEST_KEY", "secret")

    with respx.mock(base_url="https://api.test/v1") as respx_mock:
        respx_mock.post("/chat/completions").mock(side_effect=chat_mock)
        outcome = await runner.run_task(task, cfg, cwd=repo)

    assert outcome.exit_code == 0
    assert outcome.envelope.status == "ok"
    assert outcome.envelope.attempts == 3
    assert call_count == 3


def test_router_agents_only_no_agents_available_raises_no_provider() -> None:
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "ollama": {
                    "type": "ollama",
                    "base_url": "http://127.0.0.1:11434",
                    "models": [{"id": "llama", "tier": 1}],
                },
            },
        }
    )
    now = datetime(2026, 11, 23, 12, 0).astimezone()
    snap = router.Snapshot(
        now=now,
        providers={"ollama": router.ProviderState(consent="granted")},
    )
    route = router.route(TaskNeeds(kind="edit", tier=1, agents_only=True), cfg, snap)
    assert len(route.candidates) == 0
    with pytest.raises(NoProviderAvailable):
        raise route.error()


def test_delegate_task_sets_agents_only_and_max_retries(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\nDo work.\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")

    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "codex": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "codex",
                    "tier": 1,
                },
                "ollama": {
                    "type": "ollama",
                    "base_url": "http://127.0.0.1:11434",
                    "models": [{"id": "llama", "tier": 1}],
                },
            },
        }
    )
    conn = db.connect(tmp_path / "state.db")
    consent.grant(conn, "codex", cfg.providers["codex"], START)

    # Default rounds (5) and agents_only True
    res = delegate.delegate_task(
        plan_path=plan,
        verify_commands=["echo 1"],
        config=cfg,
        dry_run=True,
        cwd=tmp_path,
        conn=conn,
    )
    assert res.task_spec is not None
    assert res.task_spec.agents_only is True
    assert res.task_spec.limits.max_retries == 5
    # The routed candidates in delegate only contain codex, ollama was eliminated
    assert [c.provider for c in res.route.candidates] == ["codex"]

    # Explicit rounds
    res_custom = delegate.delegate_task(
        plan_path=plan,
        verify_commands=["echo 1"],
        config=cfg,
        rounds=3,
        dry_run=True,
        cwd=tmp_path,
        conn=conn,
    )
    assert res_custom.task_spec is not None
    assert res_custom.task_spec.agents_only is True
    assert res_custom.task_spec.limits.max_retries == 3


def test_delegate_cli_rounds_option(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from orkestra.cli import app

    monkeypatch.setattr(consent, "state", lambda *_args: "granted")
    git(tmp_path, "init", "-q", "-b", "main")
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\nDo work.\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")

    cfg_yaml = (
        "version: 1\n"
        "providers:\n"
        "  codex:\n"
        "    type: cli_agent\n"
        f"    command: '{sys.executable}'\n"
        "    kind: codex\n"
        "    tier: 1\n"
    )
    (tmp_path / "orkestra.yaml").write_text(cfg_yaml, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        app(["delegate", str(plan), "--verify", "echo 1", "--rounds", "7", "--dry-run", "--json"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["started_runner"] is False


@pytest.mark.asyncio
async def test_agent_progress_per_round_succeeds_on_round_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "calc.py").write_text("def a(): return 0\ndef b(): return 0\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    counter_file = tmp_path / "counter.txt"
    counter_file.write_text("0", encoding="utf-8")

    # Script simulates an agent fixing one bug per round:
    # Round 1: def a(): return 0; def b(): return 0 (both fail)
    # Round 2: def a(): return 1; def b(): return 0 (a passes, b fails)
    # Round 3: def a(): return 1; def b(): return 1 (both pass)
    agent_script = tmp_path / "step_agent.py"
    agent_script.write_text(
        "from pathlib import Path\n"
        f"c_path = Path({str(counter_file)!r})\n"
        "count = int(c_path.read_text()) + 1\n"
        "c_path.write_text(str(count))\n"
        "calc = Path('calc.py')\n"
        "if count == 1:\n"
        "    calc.write_text('def a(): return 0\\ndef b(): return 0\\n')\n"
        "elif count == 2:\n"
        "    calc.write_text('def a(): return 1\\ndef b(): return 0\\n')\n"
        "else:\n"
        "    calc.write_text('def a(): return 1\\ndef b(): return 1\\n')\n"
        "print('done round', count)\n",
        encoding="utf-8",
    )

    task_data = {
        "id": "progress-task",
        "kind": "edit",
        "prompt": "fix a and b",
        "provider": "agent",
        "limits": {"max_retries": 5},
        "verify": [
            {
                "type": "command",
                "run": f'"{sys.executable}" -c "import calc; assert calc.a() == 1"',
            },
            {
                "type": "command",
                "run": f'"{sys.executable}" -c "import calc; assert calc.b() == 1"',
            },
        ],
    }
    task = spec.parse_task(task_data, source="test")
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agent": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(agent_script)],
                }
            },
        }
    )

    outcome = await runner.run_task(task, cfg, cwd=repo)
    assert outcome.exit_code == 0
    assert outcome.envelope.status == "ok"
    assert outcome.envelope.attempts == 3


@pytest.mark.asyncio
async def test_agent_no_progress_identical_failures_stops_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "calc.py").write_text("def a(): return 0\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    counter_file = tmp_path / "counter_noprog.txt"
    counter_file.write_text("0", encoding="utf-8")

    # Script makes no progress: writes same broken code each round
    agent_script = tmp_path / "stuck_agent.py"
    agent_script.write_text(
        "from pathlib import Path\n"
        f"c_path = Path({str(counter_file)!r})\n"
        "count = int(c_path.read_text()) + 1\n"
        "c_path.write_text(str(count))\n"
        "Path('calc.py').write_text('def a(): return 0\\n')\n"
        "print('stuck round', count)\n",
        encoding="utf-8",
    )

    task_data = {
        "id": "no-progress-task",
        "kind": "edit",
        "prompt": "fix a",
        "provider": "agent",
        "limits": {"max_retries": 5},  # Allows 6 answers if progress were made!
        "verify": [
            {
                "type": "command",
                "run": f'"{sys.executable}" -c "import calc; assert calc.a() == 1"',
            },
        ],
    }
    task = spec.parse_task(task_data, source="test")
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agent": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(agent_script)],
                }
            },
        }
    )

    outcome = await runner.run_task(task, cfg, cwd=repo)
    # Must fail because no progress was made after round 2
    assert outcome.exit_code != 0
    assert outcome.envelope.status in ("failed", "escalate")
    # Proves it stopped at round 2, did NOT waste rounds 3, 4, 5, 6!
    assert outcome.envelope.attempts == 2
    assert int(counter_file.read_text()) == 2


@pytest.mark.asyncio
async def test_chat_worker_no_progress_stops_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "calc.py").write_text("def a(): return 0\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    call_count = 0

    def chat_mock(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        # Chat worker returns the same broken content each round
        body = json.dumps({"files": [{"path": "calc.py", "content": "def a(): return 0\n"}]})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": body}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10},
            },
        )

    task_data = {
        "id": "chat-no-prog",
        "kind": "edit",
        "prompt": "fix a",
        "provider": "chat",
        "limits": {"max_retries": 5},
        "verify": [
            {
                "type": "command",
                "run": f'"{sys.executable}" -c "import calc; assert calc.a() == 1"',
            },
        ],
    }
    task = spec.parse_task(task_data, source="test")
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "chat": {
                    "type": "openai_compat",
                    "base_url": "https://api.test/v1",
                    "api_key_env": "TEST_KEY",
                    "models": [{"id": "model-1", "tier": 1, "edit_format": "whole"}],
                }
            },
        }
    )
    monkeypatch.setenv("TEST_KEY", "secret")

    with respx.mock(base_url="https://api.test/v1") as respx_mock:
        respx_mock.post("/chat/completions").mock(side_effect=chat_mock)
        outcome = await runner.run_task(task, cfg, cwd=repo)

    assert outcome.exit_code != 0
    assert outcome.envelope.status == "failed"
    # Proves chat worker stopped early at attempt 2
    assert outcome.envelope.attempts == 2
    assert call_count == 2


@pytest.mark.asyncio
async def test_old_tasks_max_retries_1_behavior_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "calc.py").write_text("def a(): return 0\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    counter_file = tmp_path / "counter_legacy.txt"
    counter_file.write_text("0", encoding="utf-8")

    agent_script = tmp_path / "legacy_agent.py"
    agent_script.write_text(
        "from pathlib import Path\n"
        f"c_path = Path({str(counter_file)!r})\n"
        "count = int(c_path.read_text()) + 1\n"
        "c_path.write_text(str(count))\n"
        "Path('calc.py').write_text('def a(): return 0\\n')\n"
        "print('round', count)\n",
        encoding="utf-8",
    )

    # Explicit max_retries: 1 -> 2 answers total
    task_data = {
        "id": "legacy-task",
        "kind": "edit",
        "prompt": "fix a",
        "provider": "agent",
        "limits": {"max_retries": 1},
        "verify": [
            {
                "type": "command",
                "run": f'"{sys.executable}" -c "import calc; assert calc.a() == 1"',
            },
        ],
    }
    task = spec.parse_task(task_data, source="test")
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agent": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(agent_script)],
                }
            },
        }
    )

    outcome = await runner.run_task(task, cfg, cwd=repo)
    assert outcome.exit_code != 0
    assert outcome.envelope.status in ("failed", "escalate")
    assert outcome.envelope.attempts == 2
    assert int(counter_file.read_text()) == 2
