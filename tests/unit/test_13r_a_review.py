"""Faz 13r-a review fixes (Claude, 2026-11-23, D-130).

- The task starts on the code agents' own tier: an agent on tier 1 (the usual agy setup)
  must be found, not skipped by a hard-coded tier 3.
- The plan is something to read, not to change: for an edit task every context file is a
  "file to change", so the plan goes into the prompt and ``protect_paths``; a plan git
  ignores never reaches the worktree, so it is refused.
- Only a ``delegated`` tag marks a delegated item; any task under ``.orkestra/tasks/`` is not.
- ``status`` counts failovers from the envelope, not retries.
- Without a notification channel the user is told none will come.
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import git

from orkestra.chief import status
from orkestra.config.schema import CliAgentProvider, Config, OllamaProvider
from orkestra.errors import UsageError
from orkestra.queue import store as queue_store
from orkestra.state import consent, db
from orkestra.tasks import delegate, spec

START = datetime(2026, 11, 23, 10, 0).astimezone()
FAKE_AGENT = Path(__file__).resolve().parents[1] / "fixtures" / "fake_agent.py"


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


def _config(agent_tier: int = 1, **extra: Any) -> Config:
    agent = CliAgentProvider.model_validate(
        {
            "type": "cli_agent",
            "command": sys.executable,
            "kind": "generic",
            "tier": agent_tier,
            "extra_args": [str(FAKE_AGENT), "edit"],
        }
    )
    ollama = OllamaProvider.model_validate(
        {"type": "ollama", "models": [{"id": "small", "tier": 3}]}
    )
    return Config.model_validate(
        {"version": 1, "providers": {"agy": agent, "ollama": ollama}, **extra}
    )


def _repo(path: Path) -> Path:
    return path  # ``_tmp_is_a_repo`` made it one


def _delegate(tmp_path: Path, conn: sqlite3.Connection, **kwargs: Any) -> delegate.DelegateResult:
    plan = tmp_path / "plan.md"
    if not plan.exists():
        plan.write_text("# Plan\nDo X.\n", encoding="utf-8")
    options: dict[str, Any] = {
        "plan_path": plan,
        "verify_commands": ["python -m pytest -q"],
        "config": _config(),
        "cwd": tmp_path,
        "conn": conn,
        "launcher": lambda cmd, log, cwd: None,
        "now": lambda: START,
    }
    options.update(kwargs)
    return delegate.delegate_task(**options)


def test_an_agent_on_tier_1_is_found(tmp_path: Path, conn: sqlite3.Connection) -> None:
    res = _delegate(_repo(tmp_path), conn)
    assert res.route.candidates[0].provider == "agy"
    task = spec.load_task(res.task_file)
    assert task.tier == 1


def test_the_task_starts_on_the_agents_tier(tmp_path: Path, conn: sqlite3.Connection) -> None:
    res = _delegate(_repo(tmp_path), conn, config=_config(agent_tier=2))
    assert spec.load_task(res.task_file).tier == 2


def test_the_plan_is_read_not_changed(tmp_path: Path, conn: sqlite3.Connection) -> None:
    (tmp_path / "notes.md").write_text("background\n", encoding="utf-8")
    res = _delegate(_repo(tmp_path), conn, context_files=[Path("notes.md")])
    task = spec.load_task(res.task_file)
    assert task.context.files == []  # context files of an edit task are files to change
    assert "plan.md" in task.prompt and "notes.md" in task.prompt
    protected = [v for v in task.verify if isinstance(v, spec.ProtectPaths)]
    assert protected and set(protected[0].paths) == {"plan.md", "notes.md"}


def test_an_ignored_plan_is_refused(tmp_path: Path, conn: sqlite3.Connection) -> None:
    _repo(tmp_path)
    (tmp_path / ".gitignore").write_text("plan.md\n", encoding="utf-8")
    with pytest.raises(UsageError):
        _delegate(tmp_path, conn)
    assert queue_store.items(conn) == []


def test_a_task_file_without_the_tag_is_not_delegated(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    task_dir = tmp_path / ".orkestra" / "tasks"
    task_dir.mkdir(parents=True)
    task = task_dir / "mine.yaml"
    task.write_text("id: mine\nkind: ask\nprompt: hello\n", encoding="utf-8")
    item = queue_store.add(conn, task, now=START, profile=None, workdir=tmp_path)
    assert delegate.is_delegated(item, conn) is False


def test_status_counts_failovers_not_retries(tmp_path: Path, conn: sqlite3.Connection) -> None:
    res = _delegate(_repo(tmp_path), conn)
    assert res.queue_id is not None
    db.record_run_start(conn, run_id="r-13r", task_id="plan", kind="edit", started_at=START,
                        tags=["delegated"])  # fmt: skip
    db.record_run_end(conn, "r-13r", status="ok", provider="agy", attempts=2, duration_s=60.0)
    with db.transaction(conn):
        conn.execute(
            "UPDATE queue SET status = 'done', result_ref = 'r-13r' WHERE id = ?",
            (res.queue_id,),
        )
    found = status.collect(status.default_context(_config(), conn, START)).sections
    assert found["delegated"][0]["failovers"] == 0  # two attempts on one agent: a retry


def test_no_notification_channel_is_reported(
    tmp_path: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(delegate, "_desktop_installed", lambda: False)
    res = _delegate(_repo(tmp_path), conn)
    assert res.notify_ready is False
    res2 = _delegate(
        tmp_path, conn, task_id="second",
        config=_config(notify={"desktop": False, "ntfy_topic_env": "ORK_TOPIC"}),
    )  # fmt: skip
    assert res2.notify_ready is True


def test_a_check_may_take_as_long_as_the_run(tmp_path: Path, conn: sqlite3.Connection) -> None:
    # a phase's test suite easily takes over the 300 s a command check gets by default
    res = _delegate(tmp_path, conn, timeout_s=2400)
    commands = [v for v in spec.load_task(res.task_file).verify
                if isinstance(v, spec.CommandVerifier)]  # fmt: skip
    assert commands and all(v.timeout_s == 2400 for v in commands)
