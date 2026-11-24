"""Tests for continuation on failover and doctor notification warning (Faz 13r-b3)."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx
from conftest import git
from pydantic import ValidationError

from orkestra import doctor
from orkestra.config.schema import Config
from orkestra.state import consent, db
from orkestra.tasks import delegate, runner, spec

START = datetime(2026, 11, 23, 10, 0).astimezone()


def test_on_failover_schema_validation() -> None:
    task_default = spec.parse_task(
        {"id": "t1", "kind": "edit", "prompt": "do something"},
        source="test",
    )
    assert task_default.on_failover == "restart"

    task_continue = spec.parse_task(
        {"id": "t2", "kind": "edit", "prompt": "do something", "on_failover": "continue"},
        source="test",
    )
    assert task_continue.on_failover == "continue"

    with pytest.raises(ValidationError):
        spec.TaskSpec.model_validate(
            {"id": "t3", "kind": "edit", "prompt": "do something", "on_failover": "invalid_mode"}
        )

    from orkestra.errors import UsageError

    with pytest.raises(UsageError):
        spec.parse_task(
            {"id": "t3", "kind": "edit", "prompt": "do something", "on_failover": "invalid_mode"},
            source="test",
        )


def test_delegate_task_writes_on_failover_continue(tmp_path: Path) -> None:
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
            },
        }
    )
    conn = db.connect(tmp_path / "state.db")
    consent.grant(conn, "codex", cfg.providers["codex"], START)

    res = delegate.delegate_task(
        plan_path=plan,
        verify_commands=["echo 1"],
        config=cfg,
        dry_run=True,
        cwd=tmp_path,
        conn=conn,
    )
    assert res.task_spec is not None
    assert res.task_spec.on_failover == "continue"


@pytest.mark.asyncio
async def test_agent_to_agent_failover_continue_preserves_worktree_and_adds_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "base.txt").write_text("initial\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    prompt_log1 = tmp_path / "prompt1.txt"
    prompt_log2 = tmp_path / "prompt2.txt"

    # Agent 1 writes file1.txt, logs prompt, and fails with quota exhausted
    agent1_script = tmp_path / "agent1.py"
    agent1_script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        f"Path({str(prompt_log1)!r}).write_text(sys.stdin.read(), encoding='utf-8')\n"
        "Path('file1.txt').write_text('content1\\n', encoding='utf-8')\n"
        "sys.stderr.write('quota exhausted\\n')\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )

    # Agent 2 checks file1.txt exists, logs prompt, writes file2.txt, exits 0
    agent2_script = tmp_path / "agent2.py"
    agent2_script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        f"Path({str(prompt_log2)!r}).write_text(sys.stdin.read(), encoding='utf-8')\n"
        "f1 = Path('file1.txt')\n"
        "assert f1.exists(), 'file1.txt must exist from previous agent!'\n"
        "Path('file2.txt').write_text('content2\\n', encoding='utf-8')\n"
        "print('agent 2 done')\n",
        encoding="utf-8",
    )

    task_data = {
        "id": "continue-task",
        "kind": "edit",
        "prompt": "write files 1 and 2",
        "on_failover": "continue",
        "verify": [
            {
                "type": "command",
                "run": (
                    f'"{sys.executable}" -c "from pathlib import Path; '
                    "assert Path('file1.txt').exists() and Path('file2.txt').exists()\""
                ),
            }
        ],
    }
    task = spec.parse_task(task_data, source="test")
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agent1": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(agent1_script)],
                    "tier": 1,
                },
                "agent2": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(agent2_script)],
                    "tier": 2,
                },
            },
        }
    )

    outcome = await runner.run_task(task, cfg, cwd=repo)
    assert outcome.exit_code == 0
    assert outcome.envelope.status == "ok"
    assert outcome.envelope.changes is not None
    # Both file1.txt and file2.txt must be in the final changes
    assert outcome.envelope.changes.files == 2

    # Agent 2 received the continuation note
    agent2_prompt = prompt_log2.read_text(encoding="utf-8")
    assert "file1.txt" in agent2_prompt
    assert "quota exhausted" in agent2_prompt
    assert "Continue from the current state, do not rewrite what is done." in agent2_prompt


@pytest.mark.asyncio
async def test_agent_to_agent_failover_restart_mode_resets_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "base.txt").write_text("initial\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    prompt_log2 = tmp_path / "prompt2.txt"

    # Agent 1 writes file1.txt and fails with quota exhausted
    agent1_script = tmp_path / "agent1.py"
    agent1_script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "Path('file1.txt').write_text('content1\\n', encoding='utf-8')\n"
        "sys.stderr.write('quota exhausted\\n')\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )

    # Agent 2 checks file1.txt does NOT exist under restart mode, then writes file2.txt
    agent2_script = tmp_path / "agent2.py"
    agent2_script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        f"Path({str(prompt_log2)!r}).write_text(sys.stdin.read(), encoding='utf-8')\n"
        "f1 = Path('file1.txt')\n"
        "assert not f1.exists(), 'file1.txt must NOT exist in restart mode!'\n"
        "Path('file2.txt').write_text('content2\\n', encoding='utf-8')\n"
        "print('agent 2 done')\n",
        encoding="utf-8",
    )

    task_data = {
        "id": "restart-task",
        "kind": "edit",
        "prompt": "write file 2",
        "on_failover": "restart",
        "verify": [
            {
                "type": "command",
                "run": (
                    f'"{sys.executable}" -c "from pathlib import Path; '
                    "assert Path('file2.txt').exists()\""
                ),
            }
        ],
    }
    task = spec.parse_task(task_data, source="test")
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agent1": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(agent1_script)],
                    "tier": 1,
                },
                "agent2": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(agent2_script)],
                    "tier": 2,
                },
            },
        }
    )

    outcome = await runner.run_task(task, cfg, cwd=repo)
    assert outcome.exit_code == 0
    assert outcome.envelope.status == "ok"
    assert outcome.envelope.changes is not None
    # Only file2.txt is present
    assert outcome.envelope.changes.files == 1

    agent2_prompt = prompt_log2.read_text(encoding="utf-8")
    assert "Continue from the current state" not in agent2_prompt


@pytest.mark.asyncio
async def test_continue_agent_to_chat_worker_drops_partial_work_and_sets_envelope_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "calc.py").write_text("def a(): return 0\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    # Agent 1 writes partial file file_partial.txt, then fails with quota exhausted
    agent1_script = tmp_path / "agent1.py"
    agent1_script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "Path('file_partial.txt').write_text('partial\\n', encoding='utf-8')\n"
        "sys.stderr.write('quota exhausted\\n')\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )

    task_data = {
        "id": "agent-to-chat-task",
        "kind": "edit",
        "prompt": "fix calc.py",
        "on_failover": "continue",
        "agents_only": False,
        "context": {"files": ["calc.py"]},
        "verify": [
            {
                "type": "command",
                "run": f'"{sys.executable}" -c "import calc; assert calc.a() == 42"',
            }
        ],
    }
    task = spec.parse_task(task_data, source="test")
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agent1": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(agent1_script)],
                    "tier": 1,
                },
                "chat": {
                    "type": "openai_compat",
                    "base_url": "https://api.test/v1",
                    "api_key_env": "TEST_KEY",
                    "models": [{"id": "model-1", "tier": 2, "edit_format": "whole"}],
                },
            },
        }
    )
    monkeypatch.setenv("TEST_KEY", "secret-test-key")

    chat_content = json.dumps({"files": [{"path": "calc.py", "content": "def a(): return 42\n"}]})
    chat_body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": chat_content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 20},
    }

    with respx.mock(base_url="https://api.test/v1") as respx_mock:
        respx_mock.post("/chat/completions").mock(return_value=httpx.Response(200, json=chat_body))
        outcome = await runner.run_task(task, cfg, cwd=repo)

    assert outcome.exit_code == 0
    assert outcome.envelope.status == "ok"
    # partial_dropped must be True in the envelope
    assert outcome.envelope.partial_dropped is True
    # In serialized json, partial_dropped is true
    raw_env = json.loads(outcome.envelope.model_dump_json())
    assert raw_env.get("partial_dropped") is True


@pytest.mark.asyncio
async def test_doctor_warns_when_no_notification_channel(tmp_path: Path) -> None:
    # Desktop unavailable (has_desktop=lambda: False), and no ntfy configured
    report = await doctor.run_doctor(
        which=lambda tool: "/usr/bin/git" if tool == "git" else None,
        probe=lambda path: "git version 2.50.0",
        platform="linux",
        has_desktop=lambda: False,
    )
    notify_checks = [c for c in report.checks if c.name == "notify"]
    assert len(notify_checks) == 1
    check = notify_checks[0]
    assert check.status == "warn"
    assert "orkestra-cli[notify]" in check.data.get("hint", "")


@pytest.mark.asyncio
async def test_doctor_suggests_configuration_when_desktop_notifications_are_disabled(
    tmp_path: Path,
) -> None:
    from orkestra.i18n import t

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "version: 1\nnotify:\n  desktop: false\nproviders: {}\n",
        encoding="utf-8",
    )
    report = await doctor.run_doctor(
        config_flag=config_path,
        which=lambda tool: "/usr/bin/git" if tool == "git" else None,
        probe=lambda path: "git version 2.50.0",
        platform="linux",
        has_desktop=lambda: False,
    )

    check = next(c for c in report.checks if c.name == "notify")
    assert check.data["hint"] == t("doctor.hint.configure_notify")


@pytest.mark.asyncio
async def test_doctor_suppresses_warning_when_channel_available(tmp_path: Path) -> None:
    # 1. Desktop available
    report_desktop = await doctor.run_doctor(
        which=lambda tool: "/usr/bin/git" if tool == "git" else None,
        probe=lambda path: "git version 2.50.0",
        platform="linux",
        has_desktop=lambda: True,
    )
    assert not any(c.name == "notify" for c in report_desktop.checks)

    # 2. Ntfy configured
    cfg_file = tmp_path / "orkestra.yaml"
    cfg_file.write_text(
        "version: 1\nnotify:\n  ntfy_topic_env: MY_NTFY_TOPIC\n",
        encoding="utf-8",
    )
    report_ntfy = await doctor.run_doctor(
        config_flag=cfg_file,
        which=lambda tool: "/usr/bin/git" if tool == "git" else None,
        probe=lambda path: "git version 2.50.0",
        environ={"MY_NTFY_TOPIC": "secret-topic"},
        platform="linux",
        has_desktop=lambda: False,
    )
    assert not any(c.name == "notify" for c in report_ntfy.checks)


@pytest.mark.asyncio
async def test_continuation_note_includes_verifier_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "base.txt").write_text("initial\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    prompt_log2 = tmp_path / "prompt2.txt"

    # Agent 1 writes buggy file, exits 0, but fails check, and max_retries: 1 so it fails over
    agent1_script = tmp_path / "agent1.py"
    agent1_script.write_text(
        "from pathlib import Path\n"
        "Path('file1.txt').write_text('bad content\\n', encoding='utf-8')\n"
        "print('agent 1 done')\n",
        encoding="utf-8",
    )

    # Agent 2 fixes file1.txt, exits 0
    agent2_script = tmp_path / "agent2.py"
    agent2_script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        f"Path({str(prompt_log2)!r}).write_text(sys.stdin.read(), encoding='utf-8')\n"
        "Path('file1.txt').write_text('good content\\n', encoding='utf-8')\n"
        "print('agent 2 done')\n",
        encoding="utf-8",
    )

    task_data = {
        "id": "verify-failover-task",
        "kind": "edit",
        "prompt": "write good content to file1.txt",
        "on_failover": "continue",
        "limits": {"max_retries": 1},
        "verify": [
            {
                "type": "command",
                "run": (
                    f'"{sys.executable}" -c "from pathlib import Path; '
                    "assert 'good content' in Path('file1.txt').read_text()\""
                ),
            }
        ],
    }
    task = spec.parse_task(task_data, source="test")
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agent1": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(agent1_script)],
                    "tier": 1,
                },
                "agent2": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(agent2_script)],
                    "tier": 2,
                },
            },
        }
    )

    outcome = await runner.run_task(task, cfg, cwd=repo)
    assert outcome.exit_code == 0
    assert outcome.envelope.status == "ok"

    agent2_prompt = prompt_log2.read_text(encoding="utf-8")
    assert "AssertionError" in agent2_prompt or "assert 'good content'" in agent2_prompt
    assert "file1.txt" in agent2_prompt
    assert "Continue from the current state, do not rewrite what is done." in agent2_prompt
