"""``orkestra queue``, ``notify test`` and ``batch --notify`` end to end (Faz 12a, §21).

A fake Ollama answers; ``no_real_notifications`` (conftest) records what ntfy would get.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import psutil
import pytest

from orkestra import paths
from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.i18n import t
from orkestra.providers.base import CompletionRequest, CompletionResult, Usage
from orkestra.providers.ollama import OllamaChat
from orkestra.queue import store
from orkestra.state import consent, db

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
SECRET = "sk-or-v1-0123456789abcdef0123456789abcdef"
CONFIG = """\
version: 1
notify:
  desktop: {desktop}
  ntfy_topic_env: {topic_env}
providers:
  ollama:
    type: ollama
    base_url: http://ollama.test:11434
    models:
      - id: coder
        tier: 1
"""


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


def _setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    desktop: bool = False,
    topic_env: str = "null",
) -> Path:
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(
        CONFIG.format(desktop=str(desktop).lower(), topic_env=topic_env), encoding="utf-8"
    )
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    monkeypatch.chdir(work)
    config = load_config(cwd=work, environ={}).config
    with closing(db.connect()) as conn:
        consent.grant(conn, "ollama", config.providers["ollama"], db.local_now())
    return work


def _task(where: Path, name: str, prompt: str, **fields: Any) -> Path:
    path = where / name
    path.write_text(
        json.dumps({"id": path.stem, "kind": "ask", "prompt": prompt, **fields}), encoding="utf-8"
    )
    return path


def _batch(where: Path, name: str = "night.json") -> Path:
    path = where / name
    tasks = [
        {"id": "a", "kind": "ask", "prompt": "batch one"},
        {"id": "b", "kind": "ask", "prompt": "batch two"},
    ]
    path.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
    return path


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


def test_queue_add_list_run_and_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work = _setup(tmp_path, monkeypatch)
    code, out, _ = _run(["queue", "add", str(_task(work, "hi.json", "say hi")), "--json"], capsys)
    assert code == 0, out
    first = json.loads(out)
    assert first["kind"] == "task" and first["status"] == "pending" and first["profile"] is None
    _batch(work)
    code, out, _ = _run(["queue", "add", "night.json"], capsys)  # relative to this folder
    assert code == 0 and "#2" in out and "batch" in out
    code, out, _ = _run(["status"], capsys)
    assert t("status.queue.line", pending=2, running=0, failed=0) in out
    code, out, _ = _run(["queue", "list"], capsys)
    assert "hi.json" in out and "night.json" in out and "pending" in out

    code, out, err = _run(["queue", "run", "--json"], capsys)
    assert code == 0, err
    report = json.loads(out)
    assert report["done"] == [first["id"], first["id"] + 1] and report["failed"] == []
    assert report["stopped"] is None and report["notifications"] == []
    refs = {item["kind"]: item["result_ref"] for item in report["items"]}
    with closing(sqlite3.connect(paths.state_db_path())) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE run_id = ?",
                            (refs["task"],)).fetchone()[0] == 1  # fmt: skip
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE batch_id = ?",
                            (refs["batch"],)).fetchone()[0] == 2  # fmt: skip
    assert len(fake.calls) == 3
    code, out, _ = _run(["status"], capsys)
    assert "queue:" not in out  # nothing waiting or failed: no line
    code, out, _ = _run(["queue", "list"], capsys)
    assert out.count("done") == 2


def test_queue_run_text_output_and_remove(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work = _setup(tmp_path, monkeypatch)
    _run(["queue", "add", str(_task(work, "one.json", "first"))], capsys)
    _run(["queue", "add", str(_task(work, "two.json", "second"))], capsys)
    code, out, _ = _run(["queue", "remove", "1"], capsys)
    assert code == 0 and t("queue.removed", id=1) in out
    code, out, err = _run(["queue", "run"], capsys)
    assert code == 0, err
    assert t("queue.summary", done=1, failed=0, skipped=0) in out
    assert "#2" in err and "two.json" in err
    assert len(fake.calls) == 1 and "second" in fake.calls[0]
    code, _, err = _run(["queue", "remove", "1"], capsys)
    assert code == 2 and "#1" in err


def test_queue_remove_finished_and_its_usage_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work = _setup(tmp_path, monkeypatch)
    _run(["queue", "add", str(_task(work, "one.json", "first"))], capsys)
    code, _, err = _run(["queue", "run"], capsys)
    assert code == 0, err
    _run(["queue", "add", str(_task(work, "two.json", "second"))], capsys)
    code, out, _ = _run(["queue", "remove", "--finished", "--json"], capsys)
    assert code == 0
    assert [item["id"] for item in json.loads(out)["removed"]] == [1]
    code, out, _ = _run(["queue", "list", "--json"], capsys)
    assert [item["id"] for item in json.loads(out)["items"]] == [2]
    code, out, _ = _run(["queue", "remove", "--finished"], capsys)
    assert code == 0 and t("queue.removed_finished", count=0) in out
    code, _, err = _run(["queue", "remove"], capsys)
    assert code == 2 and t("queue.error.remove_target") in err
    code, _, err = _run(["queue", "remove", "2", "--finished"], capsys)
    assert code == 2 and t("queue.error.remove_target") in err


def test_a_second_queue_run_exits_with_code_5(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work = _setup(tmp_path, monkeypatch)
    _run(["queue", "add", str(_task(work, "one.json", "first"))], capsys)
    parent = psutil.Process(os.getppid())  # alive for the whole test, and not us
    with closing(db.connect()) as conn:
        store.acquire_lock(conn, db.local_now(), owner=(parent.pid, parent.create_time()))
    code, _, err = _run(["queue", "run"], capsys)
    assert code == 5
    assert "queue run" in err and str(parent.pid) in err
    assert fake.calls == []


def test_a_changed_file_is_announced_and_the_current_one_runs_from_its_own_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work = _setup(tmp_path, monkeypatch)
    (work / "notes.txt").write_text("the notes say 42", encoding="utf-8")
    task = _task(work, "read.json", "old prompt", context={"files": ["notes.txt"]})
    _run(["queue", "add", "read.json"], capsys)
    _task(work, "read.json", "new prompt", context={"files": ["notes.txt"]})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # cron starts in the home folder
    code, _, err = _run(["queue", "run"], capsys)
    assert code == 0, err
    assert t("queue.warning.changed", id=1, path=task) in err
    assert "new prompt" in fake.calls[0] and "the notes say 42" in fake.calls[0]
    assert Path.cwd() == elsewhere


def test_queue_run_notify_sends_only_the_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
    no_real_notifications: list[tuple[str, ...]],
) -> None:
    monkeypatch.setenv("ORK_TEST_TOPIC", "night-shift")
    work = _setup(tmp_path, monkeypatch, topic_env="ORK_TEST_TOPIC")
    prompt = f"def secret_function(): return '{SECRET}'"
    _run(["queue", "add", str(_task(work, "code.json", prompt)), "--json"], capsys)
    _run(["queue", "add", str(_batch(work))], capsys)
    code, out, err = _run(["queue", "run", "--notify"], capsys)
    assert code == 0, err
    assert no_real_notifications == [
        (
            "https://ntfy.sh/night-shift",
            t("notify.title.queue"),
            t("notify.counts", finished=2, failed=0),
        )
    ]
    sent = " ".join(" ".join(item) for item in no_real_notifications)
    assert SECRET not in sent and "secret_function" not in sent and "code.json" not in sent
    assert "night-shift" not in out + err  # the topic is never printed
    assert t("notify.state.sent") in err


def test_batch_notify_sends_the_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
    no_real_notifications: list[tuple[str, ...]],
) -> None:
    monkeypatch.setenv("ORK_TEST_TOPIC", "topic1")
    work = _setup(tmp_path, monkeypatch, topic_env="ORK_TEST_TOPIC")
    code, out, err = _run(["batch", str(_batch(work)), "--notify", "--json"], capsys)
    assert code == 0, err
    json.loads(out)  # stdout is still one JSON document
    assert no_real_notifications == [
        (
            "https://ntfy.sh/topic1",
            t("notify.title.batch"),
            t("notify.counts", finished=2, failed=0),
        )
    ]


def test_notify_test_reports_every_channel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_real_notifications: list[tuple[str, ...]],
) -> None:
    _setup(tmp_path, monkeypatch, desktop=True, topic_env="ORK_TEST_TOPIC")
    code, out, _ = _run(["notify", "test"], capsys)
    assert code == 1  # desktop not installed, topic variable unset: nothing was delivered
    assert "orkestra-cli[notify]" in out and "ORK_TEST_TOPIC" in out
    monkeypatch.setenv("ORK_TEST_TOPIC", "my_topic")
    code, out, _ = _run(["notify", "test", "--json"], capsys)
    assert code == 0
    states = {d["channel"]: d["state"] for d in json.loads(out)["deliveries"]}
    assert states == {"desktop": "skipped", "ntfy": "sent"}
    assert no_real_notifications[-1][2] == t("notify.test.message")


def test_notify_test_without_any_channel_says_how_to_set_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup(tmp_path, monkeypatch, desktop=False)
    code, out, _ = _run(["notify", "test"], capsys)
    assert code == 1 and t("notify.test.none") in out


def test_queue_run_with_a_wrong_until_is_a_usage_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup(tmp_path, monkeypatch)
    code, _, err = _run(["queue", "run", "--until", "25:99"], capsys)
    assert code == 2 and "HH:MM" in err


def test_queue_add_refuses_an_unknown_profile_and_a_broken_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work = _setup(tmp_path, monkeypatch)
    task = _task(work, "hi.json", "hi")
    code, _, err = _run(["queue", "add", str(task), "--profile", "nope"], capsys)
    assert code == 2 and "nope" in err
    code, _, _ = _run(["queue", "add", str(work / "missing.json")], capsys)
    assert code == 2
    code, out, _ = _run(["queue", "list"], capsys)
    assert t("queue.empty") in out


def test_a_relative_config_path_still_works_for_items_added_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    night = (tmp_path / "orkestra-home" / "config.yaml").read_text(encoding="utf-8")
    (work / "night.yaml").write_text(night, encoding="utf-8")
    (tmp_path / "orkestra-home" / "config.yaml").unlink()  # only ./night.yaml has providers
    project = work / "proj"
    project.mkdir()
    _task(project, "hi.json", "say hi")
    monkeypatch.chdir(project)
    code, _, err = _run(["--config", "../night.yaml", "queue", "add", "hi.json"], capsys)
    assert code == 0, err
    monkeypatch.chdir(work)
    code, out, err = _run(["--config", "night.yaml", "queue", "run", "--json"], capsys)
    assert code == 0, err + out
    assert json.loads(out)["done"] == [1]


def test_status_leaves_out_an_old_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    from datetime import timedelta

    work = _setup(tmp_path, monkeypatch)
    _task(work, "hi.json", "hi")
    with closing(db.connect()) as conn:
        item = store.add(conn, Path("hi.json"), now=db.local_now())
        store.mark_running(conn, item.id, db.local_now())
        store.mark_finished(conn, item.id, "failed", db.local_now() - timedelta(days=3))
    code, out, _ = _run(["status"], capsys)
    assert code == 0 and "queue:" not in out
