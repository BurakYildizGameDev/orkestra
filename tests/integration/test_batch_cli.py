"""``orkestra batch`` end to end with a counting fake Ollama (Faz 7a, Mimari §12).

The fake records how many requests run at the same time, so the per-provider concurrency
limit and the ordering of edit tasks on the same files can be checked, not just assumed.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from orkestra import paths
from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.providers.base import CompletionRequest, CompletionResult, Usage
from orkestra.providers.ollama import OllamaChat
from orkestra.state import consent, db
from orkestra.tasks import runner

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
MakeRepo = Callable[..., Path]


def _config(concurrency: int) -> str:
    return f"""\
version: 1
providers:
  ollama:
    type: ollama
    base_url: http://ollama.test:11434
    concurrency: {concurrency}
    models:
      - id: coder
        tier: 1
        edit_format: whole
"""


class FakeOllama:
    """Answers every request after a short pause and counts the requests in flight."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.calls: list[str] = []  # the task prompt of every request, in order
        self.active_edits = 0
        self.peak_edits = 0
        self.answers: dict[str, str] = {}  # prompt substring -> answer

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        edit = "Output format" in req.user and '"files"' in req.user
        self.active += 1
        self.active_edits += edit
        self.peak = max(self.peak, self.active)
        self.peak_edits = max(self.peak_edits, self.active_edits)
        self.calls.append(req.user)
        try:
            await asyncio.sleep(0.02)
            text = next((a for key, a in self.answers.items() if key in req.user), "fine")
            return CompletionResult(text, Usage(10, 5, 0.0), "stop")
        finally:
            self.active -= 1
            self.active_edits -= edit


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeOllama:
    worker = FakeOllama()

    async def complete(self: OllamaChat, req: CompletionRequest) -> CompletionResult:
        return await worker.complete(req)

    monkeypatch.setattr(OllamaChat, "complete", complete)
    return worker


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, concurrency: int = 1) -> Path:
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(_config(concurrency), encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    monkeypatch.chdir(work)
    config = load_config(cwd=work, environ={}).config
    with closing(db.connect()) as conn:
        consent.grant(conn, "ollama", config.providers["ollama"], db.local_now())
    return work


def _batch(where: Path, tasks: list[dict[str, Any]], **fields: Any) -> str:
    path = where / "batch.json"
    path.write_text(json.dumps({"tasks": tasks, **fields}), encoding="utf-8")
    return str(path)


def _ask(task_id: str, **fields: Any) -> dict[str, Any]:
    return {"id": task_id, "kind": "ask", "prompt": f"question {task_id}", **fields}


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


def _results(out: str) -> dict[str, dict[str, Any]]:
    return {item["task_id"]: item for item in json.loads(out)["results"]}


# --- concurrency -----------------------------------------------------------------------


def test_twenty_tasks_never_send_more_than_the_provider_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch, concurrency=1)
    tasks = [_ask(f"t{n:02d}") for n in range(20)]
    code, out, _ = _run(["batch", _batch(work, tasks), "--parallel", "4", "--json"], capsys)
    assert code == 0, out
    doc = json.loads(out)
    assert doc["totals"]["ok"] == 20 and len(doc["results"]) == 20
    assert fake.peak == 1 and len(fake.calls) == 20  # concurrency: 1 → one request at a time
    with closing(sqlite3.connect(paths.state_db_path())) as conn:
        batch_ids = {row[0] for row in conn.execute("SELECT batch_id FROM runs")}
    assert batch_ids == {doc["batch_id"]}


def test_a_provider_with_concurrency_3_gets_three_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch, concurrency=3)
    tasks = [_ask(f"t{n}") for n in range(9)]
    code, out, _ = _run(["batch", _batch(work, tasks, parallel=5), "--json"], capsys)
    assert code == 0, out
    assert fake.peak == 3  # limited by the provider, not by --parallel 5


def test_parallel_limits_the_tasks_in_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch, concurrency=8)
    tasks = [_ask(f"t{n}") for n in range(8)]
    code, out, _ = _run(["batch", _batch(work, tasks), "--parallel", "2", "--json"], capsys)
    assert code == 0, out
    assert fake.peak == 2


# --- dependencies and failures ---------------------------------------------------------


def test_a_failed_task_skips_its_dependents_and_the_rest_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    fake.answers["question bad"] = "no match here"
    tasks = [
        _ask("bad", verify=[{"type": "regex", "must_match": ["^OK$"]}],
             limits={"max_retries": 0}),
        _ask("child", depends_on=["bad"]),
        _ask("grandchild", depends_on=["child"]),
        _ask("free"),
    ]  # fmt: skip
    code, out, _ = _run(["batch", _batch(work, tasks), "--json"], capsys)
    assert code == 1
    results = _results(out)
    assert results["bad"]["status"] in {"failed", "escalate"}
    assert results["child"]["status"] == "skipped" and "bad" in results["child"]["error"]
    assert results["grandchild"]["status"] == "skipped"
    assert results["free"]["status"] == "ok"
    totals = json.loads(out)["totals"]
    assert totals["skipped"] == 2 and totals["ok"] == 1
    assert not any("question child" in c for c in fake.calls)


def test_fail_fast_starts_nothing_after_the_first_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    fake.answers["question bad"] = "no match here"
    tasks = [
        _ask("bad", verify=[{"type": "regex", "must_match": ["^OK$"]}],
             limits={"max_retries": 0}),
        *[_ask(f"later{n}", depends_on=["bad"] if n == 0 else []) for n in range(3)],
    ]  # fmt: skip
    code, out, _ = _run(
        ["batch", _batch(work, tasks), "--parallel", "1", "--fail-fast", "--json"], capsys
    )
    assert code == 1
    results = _results(out)
    assert {results[f"later{n}"]["status"] for n in range(3)} == {"skipped"}
    assert len(fake.calls) == 1


def test_a_crashing_task_does_not_bring_the_batch_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    real = runner.run_task

    async def flaky(task: Any, *args: Any, **kwargs: Any) -> runner.TaskOutcome:
        if task.id == "boom":
            raise RuntimeError("unexpected bug")
        return await real(task, *args, **kwargs)

    monkeypatch.setattr(runner, "run_task", flaky)
    tasks = [_ask("boom"), _ask("fine1"), _ask("fine2", depends_on=["boom"])]
    code, out, _ = _run(["batch", _batch(work, tasks), "--json"], capsys)
    assert code == 1
    results = _results(out)
    assert results["boom"]["status"] == "error" and "RuntimeError" in results["boom"]["error"]
    assert results["fine1"]["status"] == "ok"
    assert results["fine2"]["status"] == "skipped"


def test_a_task_without_a_provider_is_an_error_item_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    tasks = [_ask("nowhere", provider="missing"), _ask("fine")]
    code, out, _ = _run(["batch", _batch(work, tasks), "--json"], capsys)
    assert code == 1
    results = _results(out)
    assert results["nowhere"]["status"] == "error" and results["nowhere"]["exit_code"] == 2
    assert results["fine"]["status"] == "ok"


def test_a_cycle_is_exit_code_2_and_nothing_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    tasks = [_ask("a", depends_on=["b"]), _ask("b", depends_on=["a"])]
    code, out, _ = _run(["batch", _batch(work, tasks), "--json"], capsys)
    assert code == 2
    assert "error" in json.loads(out) and fake.calls == []


# --- edit tasks on the same files ------------------------------------------------------


def test_edit_tasks_on_the_same_file_run_one_after_the_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    make_repo: MakeRepo, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch, concurrency=4)
    repo = make_repo({"a.py": "x = 1\n", "b.py": "y = 1\n"})
    monkeypatch.chdir(repo)
    for name in ("a1", "a2"):
        fake.answers[f"change {name}"] = json.dumps(
            {"files": [{"path": "a.py", "content": f"x = '{name}'\n"}], "note": name}
        )
    fake.answers["change other"] = json.dumps(
        {"files": [{"path": "b.py", "content": "y = 2\n"}], "note": "b"}
    )
    tasks = [
        {"id": n, "kind": "edit", "prompt": f"change {n}", "context": {"files": [f]}}
        for n, f in (("a1", "a.py"), ("a2", "a.py"), ("other", "b.py"))
    ]
    code, out, err = _run(
        ["--lang", "en", "batch", _batch(tmp_path, tasks), "--parallel", "3", "--json"], capsys
    )
    assert code == 0, out
    assert fake.peak_edits == 2  # a1 and other together; a2 waited for a1
    assert "a1" in err and "a2" in err and "same files" in err
    doc = json.loads(out)
    assert any("same files" in w for w in doc["warnings"])
    assert all(r["envelope"]["changes"]["files"] == 1 for r in doc["results"])


def test_human_output_lists_every_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    code, out, _ = _run(["--lang", "en", "batch", _batch(work, [_ask("a"), _ask("b")])], capsys)
    assert code == 0
    assert "a" in out and "b" in out and "2 ok" in out


# --- code review fixes (PR #13) ----------------------------------------------------------


def _budget_config(home: Path) -> None:
    # One estimate ($0.41 for 4096 output tokens) fits into $0.50, two do not.
    (home / "config.yaml").write_text(
        _config(1)
        .replace(
            "        edit_format: whole\n",
            "        edit_format: whole\n        price_per_mtok: {input: 1.0, output: 100.0}\n",
        )
        .replace("    concurrency: 1\n", "    concurrency: 1\n    budget: {daily_usd: 0.5}\n"),
        encoding="utf-8",
    )


def test_waiting_tasks_hold_no_budget_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    _budget_config(tmp_path / "orkestra-home")  # budgets and prices keep the consent (D-027)
    tasks = [_ask(f"t{n}") for n in range(3)]
    code, out, _ = _run(["batch", _batch(work, tasks), "--parallel", "3", "--json"], capsys)
    assert code == 0, out  # one at a time, each settles at its real cost (0) first
    assert json.loads(out)["totals"]["ok"] == 3


def test_queued_requests_do_not_go_to_a_provider_that_was_just_paused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    from orkestra.errors import ProviderAuthError

    calls: list[str] = []

    async def refuse(self: OllamaChat, req: CompletionRequest) -> CompletionResult:
        calls.append(req.user)
        await asyncio.sleep(0.01)
        raise ProviderAuthError("bad key")  # opens the circuit at once

    monkeypatch.setattr(OllamaChat, "complete", refuse)
    work = _setup(tmp_path, monkeypatch)
    tasks = [_ask(f"t{n}") for n in range(4)]
    code, out, _ = _run(["batch", _batch(work, tasks), "--parallel", "4", "--json"], capsys)
    assert code == 1
    assert len(calls) == 1  # the others saw the paused provider after their wait
    reasons = [f["error"] for r in _results(out).values() if r["envelope"]
               for f in r["envelope"]["failovers"]]  # fmt: skip
    assert reasons.count("CircuitOpen") == 3


def test_price_lists_are_fetched_by_one_task_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    from orkestra.providers import pricing

    active, peak = 0, 0
    real = pricing.refresh

    async def counting(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01)
            return await real(*args, **kwargs)
        finally:
            active -= 1

    monkeypatch.setattr(pricing, "refresh", counting)
    work = _setup(tmp_path, monkeypatch, concurrency=4)
    code, out, _ = _run(
        ["batch", _batch(work, [_ask(f"t{n}") for n in range(4)]), "--json"], capsys
    )
    assert code == 0, out
    assert peak == 1


def test_task_warnings_are_shown_in_human_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    tasks = [_ask("a", prompt="Explain this line: password = hunter2secret")]
    code, _, err = _run(["--lang", "en", "batch", _batch(work, tasks)], capsys)
    assert code == 0
    assert "a:" in err and "secret" in err.lower()


def test_a_run_that_crashes_after_it_started_keeps_its_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    async def crash(self: Any, candidate: Any) -> Any:
        raise RuntimeError("bug inside the run")

    monkeypatch.setattr(runner._TaskRun, "_try", crash)
    work = _setup(tmp_path, monkeypatch)
    code, out, _ = _run(["batch", _batch(work, [_ask("a")]), "--json"], capsys)
    assert code == 1
    item = _results(out)["a"]
    assert item["status"] == "error" and item["run_id"]
    assert paths.run_dir(item["run_id"]).is_dir()
