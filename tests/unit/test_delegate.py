"""Tests for ``orkestra delegate`` and delegated milestone tracking (Faz 13r-a, D-128, D-129)."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import git
from ruamel.yaml import YAML

from orkestra.chief import status
from orkestra.cli import app
from orkestra.config.schema import CliAgentProvider, Config, OllamaProvider
from orkestra.errors import UsageError
from orkestra.notify import notify
from orkestra.queue import service as queue_service
from orkestra.queue import store as queue_store
from orkestra.state import consent, db
from orkestra.tasks import delegate, spec

START = datetime(2026, 11, 23, 10, 0).astimezone()
FAKE_AGENT_SCRIPT = Path(__file__).resolve().parents[1] / "fixtures" / "fake_agent.py"


@pytest.fixture(autouse=True)
def _tmp_is_a_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An edit task needs a git repository with a commit, and the agent the user's consent
    (review fix, D-130: without them every route here came back empty)."""
    monkeypatch.setattr(consent, "state", lambda *_args: "granted")
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("repo\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    with closing(db.connect()) as connection:
        yield connection


def _agent_config(**kwargs: Any) -> Config:
    agent = CliAgentProvider.model_validate(
        {
            "type": "cli_agent",
            "command": sys.executable,
            "kind": "generic",
            "extra_args": [str(FAKE_AGENT_SCRIPT), "edit"],
            **kwargs,
        }
    )
    return Config.model_validate({"version": 1, "providers": {"agy": agent}})


def _no_agent_config() -> Config:
    ollama = OllamaProvider.model_validate(
        {
            "type": "ollama",
            "base_url": "http://localhost:11434",
            "models": [{"id": "llama3:8b", "tier": 1}],
        }
    )
    return Config.model_validate({"version": 1, "providers": {"ollama": ollama}})


# --- 13r-a1: orkestra delegate ---------------------------------------------------------


def test_delegate_task_spec_valid(tmp_path: Path, conn: sqlite3.Connection) -> None:
    plan = tmp_path / "plan-13r.md"
    plan.write_text("# Phase 13r Plan\nImplement feature X.", encoding="utf-8")
    config = _agent_config()
    launched: list[list[str]] = []

    res = delegate.delegate_task(
        plan_path=plan,
        verify_commands=["pytest -q", "ruff check ."],
        config=config,
        cwd=tmp_path,
        conn=conn,
        launcher=lambda cmd, _log, _cwd: launched.append(cmd),
        now=lambda: START,
    )

    assert res.queue_id is not None
    assert res.task_file == tmp_path / ".orkestra" / "tasks" / "plan-13r.yaml"
    assert res.task_file.is_file()
    assert res.started_runner is True
    assert len(launched) == 1
    assert launched[0][:4] == [sys.executable, "-m", "orkestra", "queue"]

    # Verify task specification content
    task = spec.load_task(res.task_file)
    assert task.id == "plan-13r"
    assert task.kind == "edit"
    assert task.tier == 3
    assert "Implement the plan exactly" in task.prompt
    assert "plan-13r.md" in task.prompt  # read-only: in the prompt, not in context (D-130)
    assert len(task.verify) == 3  # + protect_paths for the plan (D-130)
    v0 = task.verify[0]
    assert isinstance(v0, spec.CommandVerifier)
    assert v0.run == "pytest -q"
    v1 = task.verify[1]
    assert isinstance(v1, spec.CommandVerifier)
    assert v1.run == "ruff check ."
    assert task.limits.timeout_s == 3600
    assert "delegated" in task.tags

    # Verify queue item
    item = queue_store.get(conn, res.queue_id)
    assert item.status == "pending"
    assert item.profile == "balanced"
    assert delegate.is_delegated(item, conn) is True


def test_delegate_without_verify_fails_code_2(tmp_path: Path, conn: sqlite3.Connection) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("Plan content", encoding="utf-8")
    config = _agent_config()

    with pytest.raises(UsageError) as exc_info:
        delegate.delegate_task(
            plan_path=plan,
            verify_commands=[],
            config=config,
            cwd=tmp_path,
            conn=conn,
        )
    assert exc_info.value.exit_code == 2


def test_delegate_when_no_code_agent_fails_and_queue_empty(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("Plan content", encoding="utf-8")
    config = _no_agent_config()

    with pytest.raises(UsageError) as exc_info:
        delegate.delegate_task(
            plan_path=plan,
            verify_commands=["pytest -q"],
            config=config,
            cwd=tmp_path,
            conn=conn,
        )
    assert exc_info.value.exit_code == 2

    # Queue must be empty and no task file left behind
    assert queue_store.items(conn) == []
    target_file = tmp_path / ".orkestra" / "tasks" / "plan.yaml"
    assert not target_file.exists()


def test_delegate_fails_if_task_file_already_exists(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    plan = tmp_path / "duplicate.md"
    plan.write_text("Plan", encoding="utf-8")
    config = _agent_config()

    # Pre-create the task file
    task_dir = tmp_path / ".orkestra" / "tasks"
    task_dir.mkdir(parents=True)
    existing = task_dir / "duplicate.yaml"
    existing.write_text("id: duplicate\n", encoding="utf-8")

    with pytest.raises(UsageError) as exc_info:
        delegate.delegate_task(
            plan_path=plan,
            verify_commands=["pytest -q"],
            config=config,
            cwd=tmp_path,
            conn=conn,
        )
    assert exc_info.value.exit_code == 2
    assert existing.read_text(encoding="utf-8") == "id: duplicate\n"  # not overwritten


def test_delegate_spawns_detached_runner_when_queue_not_running(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    plan = tmp_path / "run-test.md"
    plan.write_text("Plan", encoding="utf-8")
    config = _agent_config()
    launched: list[tuple[list[str], Path, Path]] = []

    def fake_launcher(cmd: list[str], log_path: Path, cwd: Path) -> None:
        launched.append((cmd, log_path, cwd))

    res = delegate.delegate_task(
        plan_path=plan,
        verify_commands=["pytest -q"],
        config=config,
        cwd=tmp_path,
        conn=conn,
        launcher=fake_launcher,
        now=lambda: START,
    )
    assert res.started_runner is True
    assert len(launched) == 1
    cmd, _log_path, cwd = launched[0]
    assert cmd[-3:] == ["queue", "run", "--notify"]
    assert cwd == tmp_path


def test_delegate_does_not_spawn_runner_when_already_running(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    plan = tmp_path / "busy-test.md"
    plan.write_text("Plan", encoding="utf-8")
    config = _agent_config()
    launched: list[list[str]] = []

    # Acquire lock with an active runner
    queue_store.acquire_lock(conn, START, owner=(12345, 1.0), alive=lambda _pid, _cr: True)

    res = delegate.delegate_task(
        plan_path=plan,
        verify_commands=["pytest -q"],
        config=config,
        cwd=tmp_path,
        conn=conn,
        launcher=lambda cmd, _log, _cwd: launched.append(cmd),
        is_alive=lambda _pid, _cr: True,
        now=lambda: START,
    )
    assert res.started_runner is False
    assert len(launched) == 0  # not started because runner is already running


def test_delegate_dry_run_writes_nothing_and_does_not_queue(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    plan = tmp_path / "dry-plan.md"
    plan.write_text("Plan", encoding="utf-8")
    config = _agent_config()
    launched: list[list[str]] = []

    res = delegate.delegate_task(
        plan_path=plan,
        verify_commands=["pytest -q"],
        config=config,
        dry_run=True,
        cwd=tmp_path,
        conn=conn,
        launcher=lambda cmd, _log, _cwd: launched.append(cmd),
    )
    assert res.dry_run is True
    assert res.queue_id is None
    assert res.started_runner is False
    assert len(launched) == 0
    assert not res.task_file.exists()
    assert queue_store.items(conn) == []
    assert len(res.route.candidates) >= 1


def test_delegate_custom_options(tmp_path: Path, conn: sqlite3.Connection) -> None:
    plan = tmp_path / "custom.md"
    plan.write_text("Plan", encoding="utf-8")
    ctx_file = tmp_path / "extra.md"
    ctx_file.write_text("Extra context", encoding="utf-8")
    config = _agent_config()

    res = delegate.delegate_task(
        plan_path=plan,
        verify_commands=["pytest -q"],
        config=config,
        context_files=[ctx_file],
        to_provider="agy",
        timeout_s=7200,
        task_id="my-custom-id",
        cwd=tmp_path,
        conn=conn,
        launcher=lambda _cmd, _log, _cwd: None,
        now=lambda: START,
    )
    assert res.task_file.name == "my-custom-id.yaml"
    task = spec.load_task(res.task_file)
    assert task.id == "my-custom-id"
    assert task.provider == "agy"
    assert task.limits.timeout_s == 7200
    assert task.context.files == []  # D-130: context files of an edit task are editable
    assert "extra.md" in task.prompt


# --- 13r-a2: notifications and status --------------------------------------------------


def test_notification_sent_once_and_identifies_delegated_task(
    tmp_path: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = tmp_path / "plan-notif.md"
    plan.write_text("Plan", encoding="utf-8")
    config = _agent_config()

    # Create delegated task and add to queue
    delegate.delegate_task(
        plan_path=plan,
        verify_commands=["pytest -q"],
        config=config,
        cwd=tmp_path,
        conn=conn,
        launcher=lambda _cmd, _log, _cwd: None,
        now=lambda: START,
    )

    sent: list[tuple[str, str]] = []

    def fake_send(notify_cfg: Any, title: str, message: str, **kwargs: Any) -> list[Any]:
        sent.append((title, message))
        return []

    monkeypatch.setattr(notify, "send", fake_send)

    def execute(item: queue_store.QueueItem, remaining: float | None) -> queue_service.ItemResult:
        return queue_service.ItemResult("done", result_ref="20261123-100000-abcd", cost_usd=0.0)

    report, _deliveries = queue_service.run_with_notify(
        conn, config, notify_on=True, execute=execute, now=lambda: START
    )

    assert report.finished == 1
    # Notification sent exactly ONCE
    assert len(sent) == 1
    title, msg = sent[0]
    # Delegated task is identified in notification title or message
    found = any(kw in text.lower() for kw in ("delegat", "devredilen") for text in (title, msg))
    assert found


def test_status_delegated_section_when_delegated_tasks_exist(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    plan = tmp_path / "plan-status.md"
    plan.write_text("Plan", encoding="utf-8")
    config = _agent_config()

    res = delegate.delegate_task(
        plan_path=plan,
        verify_commands=["pytest -q"],
        config=config,
        cwd=tmp_path,
        conn=conn,
        launcher=lambda _cmd, _log, _cwd: None,
        now=lambda: START,
    )

    ctx = status.default_context(config, conn, START)
    st = status.collect(ctx)

    assert "delegated" in st.sections
    delegated_list = st.sections["delegated"]
    assert len(delegated_list) == 1
    d = delegated_list[0]
    assert d["id"] == res.queue_id
    assert d["task"] == "plan-status"
    assert d["status"] == "pending"
    assert d["worker"] is None
    assert d["failovers"] == 0
    assert d["run_id"] is None

    # Text output includes delegated section
    rendered = status.render(st)
    assert "plan-status" in rendered


def test_status_when_no_delegated_tasks_unchanged(tmp_path: Path, conn: sqlite3.Connection) -> None:
    config = _agent_config()

    ctx = status.default_context(config, conn, START)
    st = status.collect(ctx)

    # When no delegated tasks exist, section is None and not in sections dict
    assert "delegated" not in st.sections
    rendered = status.render(st)
    assert "delegated" not in rendered.lower()
    assert "devredilen" not in rendered.lower()


# --- CLI test --------------------------------------------------------------------------


def test_delegate_cli_dry_run_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    plan = tmp_path / "cli-plan.md"
    plan.write_text("Plan", encoding="utf-8")

    # Set up config with agent
    cfg_path = tmp_path / "orkestra.yaml"
    cfg = _agent_config()

    y = YAML()
    with open(cfg_path, "w", encoding="utf-8") as f:
        y.dump(cfg.model_dump(exclude_none=True), f)

    with pytest.raises(SystemExit) as exc_info:
        app(
            [
                "--config",
                str(cfg_path),
                "delegate",
                str(plan),
                "--verify",
                "pytest -q",
                "--dry-run",
                "--json",
            ]
        )

    assert exc_info.value.code in (0, None)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["queue_id"] is None
    assert "cli-plan.yaml" in data["task_file"]
    assert data["started_runner"] is False
    assert len(data["candidates"]) >= 1
