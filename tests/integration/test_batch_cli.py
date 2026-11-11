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
    # --yes-cost: the estimate ($1.23) is above the default threshold (Faz 7b).
    argv = ["batch", _batch(work, tasks), "--parallel", "3", "--json", "--yes-cost"]
    code, out, _ = _run(argv, capsys)
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


# --- Faz 7b: cost estimate ---------------------------------------------------------------


def _priced(home: Path, extra: str = "") -> None:
    """One task's estimate is about $0.41 (4096 output tokens at $100/M): 1 fits under the
    default $0.50 threshold, 2 do not. Prices keep the consent (D-027)."""
    (home / "config.yaml").write_text(
        _config(4).replace(
            "        edit_format: whole\n",
            "        edit_format: whole\n        price_per_mtok: {input: 1.0, output: 100.0}\n",
        )
        + extra,
        encoding="utf-8",
    )


def _run_count() -> int:
    with closing(sqlite3.connect(paths.state_db_path())) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0])


def test_estimate_prices_every_task_and_sends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    _priced(tmp_path / "orkestra-home")
    argv = ["batch", _batch(work, [_ask("a"), _ask("b")]), "--estimate", "--json"]
    code, out, _ = _run(argv, capsys)
    assert code == 0, out
    assert fake.calls == [] and _run_count() == 0
    doc = json.loads(out)
    items = {item["task_id"]: item for item in doc["results"]}
    assert items["a"]["provider"] == "ollama" and items["a"]["model"] == "coder"
    assert items["a"]["max_output_tokens"] == 4096
    assert 0.40 < items["a"]["cost_usd"] < 0.42
    assert doc["totals"]["cost_usd"] == pytest.approx(
        items["a"]["cost_usd"] + items["b"]["cost_usd"]
    )
    assert doc["totals"]["tasks"] == 2 and doc["totals"]["unpriced"] == 0
    assert doc["confirm_above_usd"] == 0.5 and doc["needs_confirmation"] is True


def test_estimate_in_human_mode_lists_every_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    _priced(tmp_path / "orkestra-home")
    argv = ["--lang", "en", "batch", _batch(work, [_ask("a"), _ask("b")]), "--estimate"]
    code, out, _ = _run(argv, capsys)
    assert code == 0 and fake.calls == []
    assert "a" in out and "b" in out and "ollama/coder" in out and "$0.8" in out


def test_a_task_without_a_provider_shows_why_in_the_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    argv = ["batch", _batch(work, [_ask("a"), _ask("b", provider="nope")]), "--estimate",
            "--json"]  # fmt: skip
    code, out, _ = _run(argv, capsys)
    assert code == 2, out  # the exit code of the task that cannot run (unknown provider)
    items = {item["task_id"]: item for item in json.loads(out)["results"]}
    assert items["a"]["error"] is None and items["a"]["provider"] == "ollama"
    assert items["b"]["provider"] is None and "nope" in items["b"]["error"]
    assert items["b"]["exit_code"] == 2


def test_a_costly_batch_in_json_mode_needs_yes_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    _priced(tmp_path / "orkestra-home")
    file = _batch(work, [_ask("a"), _ask("b")])
    code, out, err = _run(["batch", file, "--json"], capsys)
    assert code == 2 and fake.calls == [] and _run_count() == 0
    doc = json.loads(out)  # the estimate, so the chief can show it to the user
    assert doc["needs_confirmation"] is True and len(doc["results"]) == 2
    assert "--yes-cost" in err
    code, out, _ = _run(["batch", file, "--json", "--yes-cost"], capsys)
    assert code == 0, out
    assert len(fake.calls) == 2 and json.loads(out)["totals"]["ok"] == 2


def test_a_cheap_batch_runs_without_asking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    _priced(tmp_path / "orkestra-home")
    code, out, _ = _run(["batch", _batch(work, [_ask("a")]), "--json"], capsys)
    assert code == 0, out
    assert len(fake.calls) == 1


def test_no_threshold_never_asks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    _priced(tmp_path / "orkestra-home", "estimate:\n  confirm_above_usd: null\n")
    code, out, _ = _run(["batch", _batch(work, [_ask("a"), _ask("b")]), "--json"], capsys)
    assert code == 0, out
    assert len(fake.calls) == 2


@pytest.mark.parametrize(("agreed", "code", "calls"), [(False, 2, 0), (True, 0, 2)])
def test_interactive_mode_asks_before_a_costly_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str], agreed: bool, code: int, calls: int,
) -> None:  # fmt: skip
    from orkestra import cli

    asked: list[str] = []

    def confirm(text: str, default: bool = False) -> bool:
        asked.append(text)
        return agreed

    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli.typer, "confirm", confirm)
    work = _setup(tmp_path, monkeypatch)
    _priced(tmp_path / "orkestra-home")
    result, out, _ = _run(["--lang", "en", "batch", _batch(work, [_ask("a"), _ask("b")])], capsys)
    assert result == code and len(fake.calls) == calls and len(asked) == 1
    assert "$0.8" in out  # the estimate was shown before the question


def test_a_remote_model_without_a_price_needs_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    # No price for a paid model (price list not fetched, none in the config): its cost is
    # unknown, so it cannot slip under the threshold as $0.
    work = _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("CLOUD_TEST_KEY", "sk-or-v1-FAKEKEYFORESTIMATETESTS00000000")
    home = tmp_path / "orkestra-home"
    (home / "config.yaml").write_text(
        "version: 1\nproviders:\n  cloud:\n    type: openai_compat\n"
        "    base_url: https://cloud.test/v1\n    api_key_env: CLOUD_TEST_KEY\n"
        "    models:\n      - id: paid\n        tier: 1\n",
        encoding="utf-8",
    )
    config = load_config(cwd=work, environ={"CLOUD_TEST_KEY": "x"}).config
    with closing(db.connect()) as conn:
        consent.grant(conn, "cloud", config.providers["cloud"], db.local_now())
    code, out, _ = _run(["batch", _batch(work, [_ask("a")]), "--estimate", "--json"], capsys)
    assert code == 0, out
    doc = json.loads(out)
    assert doc["results"][0]["provider"] == "cloud" and doc["results"][0]["cost_usd"] is None
    assert doc["totals"]["unpriced_remote"] == 1 and doc["needs_confirmation"] is True
    # A real run stops too, and says why: the price, not the total, is the problem.
    from orkestra.providers import pricing

    async def no_fetch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return pricing.load_cache()  # the price list is not reachable

    monkeypatch.setattr(pricing, "refresh", no_fetch)
    code, out, err = _run(["--lang", "en", "batch", _batch(work, [_ask("a")]), "--json"], capsys)
    assert code == 2 and json.loads(out)["needs_confirmation"] is True
    assert "price is not known" in err


def test_a_local_only_setup_skips_the_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    from orkestra.tasks import batch

    called: list[int] = []

    async def estimate(*args: Any, **kwargs: Any) -> Any:
        called.append(1)
        raise AssertionError("a local model without a price costs nothing")

    monkeypatch.setattr(batch, "estimate_batch", estimate)
    work = _setup(tmp_path, monkeypatch)  # ollama, no price
    code, out, _ = _run(["batch", _batch(work, [_ask("a"), _ask("b")]), "--json"], capsys)
    assert code == 0, out
    assert called == [] and len(fake.calls) == 2


def test_a_costly_batch_without_a_terminal_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    from orkestra import cli

    monkeypatch.setattr(cli, "_interactive", lambda: False)
    work = _setup(tmp_path, monkeypatch)
    _priced(tmp_path / "orkestra-home")
    code, _, err = _run(["--lang", "en", "batch", _batch(work, [_ask("a"), _ask("b")])], capsys)
    assert code == 2 and fake.calls == []
    assert "--yes-cost" in err


# --- Faz 7b: apply --batch ---------------------------------------------------------------


def _edit_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeOllama,
    make_repo: MakeRepo,
    capsys: pytest.CaptureFixture[str],
    answers: dict[str, tuple[str, str] | str],
    extra: dict[str, dict[str, Any]] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Run a batch of edit tasks; ``answers``: task id -> (file, new content) or raw answer;
    ``extra``: more fields per task (``verify``, ``depends_on``)."""
    _setup(tmp_path, monkeypatch, concurrency=4)
    repo = make_repo({"a.py": "x = 1\n", "b.py": "y = 1\n", "c.py": "z = 1\n"})
    monkeypatch.chdir(repo)
    tasks = []
    for task_id, answer in answers.items():
        if isinstance(answer, tuple):
            name, content = answer
            fake.answers[f"change {task_id}"] = json.dumps(
                {"files": [{"path": name, "content": content}], "note": task_id}
            )
        else:
            name = "c.py"
            fake.answers[f"change {task_id}"] = answer
        tasks.append({"id": task_id, "kind": "edit", "prompt": f"change {task_id}",
                      "context": {"files": [name]}, **(extra or {}).get(task_id, {})})  # fmt: skip
    _, out, _ = _run(["batch", _batch(tmp_path, tasks), "--json"], capsys)
    return repo, json.loads(out)


# A change that never passes its checks: the run fails and keeps its worktree.
_FAILING_CHECK = {"verify": [{"type": "max_changed_files", "value": 0}]}


def test_apply_batch_only_ok_applies_the_passing_runs_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    make_repo: MakeRepo, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    repo, doc = _edit_batch(tmp_path, monkeypatch, fake, make_repo, capsys, {
        "one": ("a.py", "x = 2\n"), "two": ("b.py", "y = 2\n"), "bad": "CANNOT_DO: unclear",
    })  # fmt: skip
    statuses = {r["task_id"]: r["status"] for r in doc["results"]}
    assert statuses == {"one": "ok", "two": "ok", "bad": "escalate"}
    code, out, _ = _run(["apply", "--batch", doc["batch_id"], "--only-ok", "--json"], capsys)
    assert code == 0, out
    report = json.loads(out)
    assert sorted(a["task_id"] for a in report["applied"]) == ["one", "two"]
    assert [s["task_id"] for s in report["skipped"]] == ["bad"]
    assert report["conflict"] is None and report["not_tried"] == []
    assert (repo / "a.py").read_text(encoding="utf-8") == "x = 2\n"
    assert (repo / "b.py").read_text(encoding="utf-8") == "y = 2\n"
    assert (repo / "c.py").read_text(encoding="utf-8") == "z = 1\n"
    code, out, _ = _run(["apply", "--batch", doc["batch_id"], "--only-ok", "--json"], capsys)
    assert code == 0 and json.loads(out)["applied"] == []  # all applied already: skipped


def test_apply_batch_without_only_ok_refuses_a_batch_with_failed_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    make_repo: MakeRepo, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    repo, doc = _edit_batch(tmp_path, monkeypatch, fake, make_repo, capsys, {
        "one": ("a.py", "x = 2\n"), "broken": ("c.py", "z = 2\n"),
    }, extra={"broken": _FAILING_CHECK})  # fmt: skip
    results = {r["task_id"]: r for r in doc["results"]}
    assert results["broken"]["status"] != "ok"
    code, _, err = _run(["--lang", "en", "apply", "--batch", doc["batch_id"]], capsys)
    assert code == 2 and "--only-ok" in err
    assert (repo / "a.py").read_text(encoding="utf-8") == "x = 1\n"  # nothing was applied
    # Discarding the failed run leaves nothing failed to apply: the batch goes through.
    assert _run(["discard", results["broken"]["run_id"]], capsys)[0] == 0
    code, out, _ = _run(["apply", "--batch", doc["batch_id"], "--json"], capsys)
    assert code == 0, out
    assert [a["task_id"] for a in json.loads(out)["applied"]] == ["one"]
    assert (repo / "a.py").read_text(encoding="utf-8") == "x = 2\n"


def test_a_failed_run_without_a_change_does_not_block_the_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    make_repo: MakeRepo, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    repo, doc = _edit_batch(tmp_path, monkeypatch, fake, make_repo, capsys, {
        "one": ("a.py", "x = 2\n"), "bad": "CANNOT_DO: unclear",
    })  # fmt: skip
    code, out, _ = _run(["apply", "--batch", doc["batch_id"], "--json"], capsys)
    assert code == 0, out
    assert (repo / "a.py").read_text(encoding="utf-8") == "x = 2\n"


def test_an_error_while_applying_keeps_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    make_repo: MakeRepo, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    from orkestra.errors import InternalError
    from orkestra.workspace import service

    repo, doc = _edit_batch(tmp_path, monkeypatch, fake, make_repo, capsys, {
        "one": ("a.py", "x = 2\n"), "two": ("b.py", "y = 2\n"),
        "three": ("c.py", "z = 2\n"),
    }, extra={"two": {"depends_on": ["one"]}, "three": {"depends_on": ["two"]}})  # fmt: skip
    real = service.apply_run

    def apply_run(conn: Any, run_id: str, **kwargs: Any) -> Any:
        if run_id == _results(json.dumps(doc))["two"]["run_id"]:
            raise InternalError("git worktree remove failed")
        return real(conn, run_id, **kwargs)

    monkeypatch.setattr(service, "apply_run", apply_run)
    code, out, _ = _run(["apply", "--batch", doc["batch_id"], "--json"], capsys)
    assert code == 10, out
    report = json.loads(out)
    assert [a["task_id"] for a in report["applied"]] == ["one"]  # still reported
    assert report["error"]["task_id"] == "two" and "remove failed" in report["error"]["message"]
    assert report["conflict"] is None
    assert [r["task_id"] for r in report["not_tried"]] == ["three"]
    assert (repo / "a.py").read_text(encoding="utf-8") == "x = 2\n"


def test_apply_batch_stops_at_a_conflict_and_reports_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    make_repo: MakeRepo, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    repo, doc = _edit_batch(tmp_path, monkeypatch, fake, make_repo, capsys, {
        "first": ("a.py", "x = 'first'\n"), "second": ("a.py", "x = 'second'\n"),
        "third": ("a.py", "x = 'third'\n"),
    })  # fmt: skip
    assert all(r["status"] == "ok" for r in doc["results"])
    code, out, _ = _run(["apply", "--batch", doc["batch_id"], "--only-ok", "--json"], capsys)
    assert code == 5, out
    report = json.loads(out)
    assert [a["task_id"] for a in report["applied"]] == ["first"]  # same files: in a row
    assert report["conflict"]["task_id"] == "second" and report["conflict"]["details"]
    assert [r["task_id"] for r in report["not_tried"]] == ["third"]
    assert (repo / "a.py").read_text(encoding="utf-8") == "x = 'first'\n"


def test_not_tried_leaves_out_runs_only_ok_would_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    make_repo: MakeRepo, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _, doc = _edit_batch(tmp_path, monkeypatch, fake, make_repo, capsys, {
        "first": ("a.py", "x = 'first'\n"), "second": ("a.py", "x = 'second'\n"),
        "broken": ("c.py", "z = 2\n"),
    }, extra={"broken": {**_FAILING_CHECK, "depends_on": ["second"]}})  # fmt: skip
    code, out, _ = _run(["apply", "--batch", doc["batch_id"], "--only-ok", "--json"], capsys)
    assert code == 5, out
    assert json.loads(out)["not_tried"] == []  # "broken" did not pass: it would be skipped


@pytest.mark.parametrize(
    "argv",
    [
        ["apply"],  # neither a run nor a batch
        ["apply", "r-1", "--batch", "b-1"],  # both
        ["apply", "r-1", "--only-ok"],  # --only-ok belongs to --batch
        ["apply", "--batch", "b-unknown"],
    ],
)
def test_apply_batch_usage_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    code, _, _ = _run(argv, capsys)
    assert code == 2


# --- Faz 7b: stats -----------------------------------------------------------------------


def test_stats_after_a_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    tasks = [_ask("a", tags=["docs"]), _ask("b", tags=["docs", "tests"])]
    assert _run(["batch", _batch(work, tasks), "--json"], capsys)[0] == 0
    code, out, _ = _run(["stats", "--since", "1d", "--json"], capsys)
    assert code == 0, out
    doc = json.loads(out)
    ollama = {p["provider"]: p for p in doc["providers"]}["ollama"]
    assert ollama["runs"] == 2 and ollama["ok"] == 2 and ollama["success_rate"] == 1.0
    assert ollama["prompt_tokens"] == 20 and ollama["completion_tokens"] == 10
    tags = {row["tag"]: row for row in doc["tags"]}
    assert tags["docs"]["runs"] == 2 and tags["tests"]["runs"] == 1
    code, out, _ = _run(["--lang", "en", "stats"], capsys)
    assert code == 0 and "ollama" in out


def test_stats_with_a_bad_since_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    assert _run(["stats", "--since", "soon"], capsys)[0] == 2
    assert _run(["stats", "--since", "99999999d"], capsys)[0] == 2  # no overflow traceback
