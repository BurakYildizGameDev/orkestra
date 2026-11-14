"""The benchmark harness (Faz 13a): tasks, the hidden-test leak guard, modes, results.

Nothing here starts Claude, Orkestra or a model: a fake runner plays them.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from bench import run_bench as rb

TASKS = rb.load_tasks(rb.TASKS_DIR)


# --- the task set -----------------------------------------------------------------------------


def test_every_task_has_a_project_hidden_tests_and_a_solution() -> None:
    assert TASKS, "no benchmark tasks"
    for task in TASKS:
        assert (task.root / "project").is_dir(), task.id
        assert any((task.root / "hidden").glob("test_*.py")), task.id
        assert any((task.root / "solution").rglob("*.py")), task.id
        assert task.difficulty in ("easy", "medium", "hard")
        assert task.prompt.strip() and task.files


def test_the_full_set_has_8_easy_8_medium_4_hard() -> None:
    counts = {d: sum(1 for t in TASKS if t.difficulty == d) for d in ("easy", "medium", "hard")}
    assert counts == {"easy": 8, "medium": 8, "hard": 4}


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_hidden_tests_fail_on_the_project_and_pass_on_the_solution(
    task: rb.Task, tmp_path: Path
) -> None:
    start = rb.prepare_workspace(task, tmp_path / "start")
    assert not rb.evaluate(task, start, tmp_path / "eval-start").passed
    solved = rb.prepare_workspace(task, tmp_path / "solved")
    shutil.copytree(task.root / "solution", solved, dirs_exist_ok=True)
    result = rb.evaluate(task, solved, tmp_path / "eval-solved")
    assert result.passed, result.output


@pytest.mark.parametrize("task", [t for t in TASKS if t.check], ids=lambda t: t.id)
def test_the_visible_check_passes_on_the_project_and_the_solution(
    task: rb.Task, tmp_path: Path
) -> None:
    for name, overlay in (("start", None), ("solved", task.root / "solution")):
        workspace = rb.prepare_workspace(task, tmp_path / name)
        if overlay is not None:
            shutil.copytree(overlay, workspace, dirs_exist_ok=True)
        code, output = rb.run_check(task, workspace)
        assert code == 0, f"{task.id} {name}: {output}"


# --- the leak guard ----------------------------------------------------------------------------


def _task(task_id: str = "09-bugfix-inventory") -> rb.Task:
    return next(t for t in TASKS if t.id == task_id)


def test_a_prepared_workspace_holds_no_hidden_test_or_solution(tmp_path: Path) -> None:
    task = _task()
    workspace = rb.prepare_workspace(task, tmp_path / "ws")
    rb.check_no_leak(task, workspace, prompt=task.prompt)  # does not raise
    assert (workspace / ".git").is_dir()
    assert not any(p.name.endswith("_hidden.py") for p in workspace.rglob("*"))


def test_a_hidden_test_in_the_workspace_stops_the_run(tmp_path: Path) -> None:
    task = _task()
    workspace = rb.prepare_workspace(task, tmp_path / "ws")
    hidden = next((task.root / "hidden").glob("test_*.py"))
    shutil.copy(hidden, workspace / "renamed.py")  # same content, other name
    with pytest.raises(rb.LeakError):
        rb.check_no_leak(task, workspace, prompt=task.prompt)


def test_the_solution_in_the_workspace_stops_the_run(tmp_path: Path) -> None:
    task = _task()
    workspace = rb.prepare_workspace(task, tmp_path / "ws")
    shutil.copytree(task.root / "solution", workspace, dirs_exist_ok=True)
    with pytest.raises(rb.LeakError):
        rb.check_no_leak(task, workspace, prompt=task.prompt)


def test_a_prompt_quoting_a_hidden_test_stops_the_run(tmp_path: Path) -> None:
    task = _task()
    workspace = rb.prepare_workspace(task, tmp_path / "ws")
    hidden = next((task.root / "hidden").glob("test_*.py")).read_text(encoding="utf-8")
    line = next(line.strip() for line in hidden.splitlines() if len(line.strip()) > 30)
    with pytest.raises(rb.LeakError):
        rb.check_no_leak(task, workspace, prompt=task.prompt + "\n" + line)


def test_an_orkestra_task_never_points_at_hidden_files(tmp_path: Path) -> None:
    task = _task()
    workspace = rb.prepare_workspace(task, tmp_path / "ws")
    document = rb.orkestra_task(task)
    rb.check_orkestra_task(task, workspace, document)  # fine
    document["context"]["files"].append(str(next((task.root / "hidden").glob("test_*.py"))))
    with pytest.raises(rb.LeakError):
        rb.check_orkestra_task(task, workspace, document)
    sneaky = rb.orkestra_task(task)
    sneaky["context"]["globs"] = ["../../**/*.py"]
    with pytest.raises(rb.LeakError):
        rb.check_orkestra_task(task, workspace, sneaky)


# --- modes, with a fake runner ------------------------------------------------------------------

CLAUDE_JSON = {
    "type": "result", "subtype": "success", "is_error": False, "num_turns": 4,
    "total_cost_usd": 0.0421,
    "usage": {"input_tokens": 1200, "output_tokens": 800, "cache_read_input_tokens": 5000,
              "cache_creation_input_tokens": 300},
    "modelUsage": {"claude-sonnet-x": {"inputTokens": 1200}},
}  # fmt: skip


class FakeRunner:
    """Plays ``claude`` and ``orkestra``; ``solve`` copies the solution in as a worker would."""

    def __init__(
        self, task: rb.Task, *, solve: bool = True, claude_json: Any = CLAUDE_JSON,
        claude_exit: int = 0,
    ) -> None:  # fmt: skip
        self.task = task
        self.solve = solve
        self.claude_json = claude_json
        self.claude_exit = claude_exit
        self.calls: list[tuple[list[str], Path, dict[str, str]]] = []
        self.stdin: list[str | None] = []

    def __call__(
        self, args: Sequence[str], cwd: Path, env: dict[str, str], timeout: float,
        input_text: str | None = None,
    ) -> rb.Completed:  # fmt: skip
        self.calls.append((list(args), cwd, dict(env)))
        self.stdin.append(input_text)
        if Path(args[0]).stem.lower().startswith("claude"):
            if self.claude_exit:
                return rb.Completed(self.claude_exit, "", "timed out after 900 s")
            if self.solve:
                shutil.copytree(self.task.root / "solution", cwd, dirs_exist_ok=True)
            out = (
                self.claude_json
                if isinstance(self.claude_json, str)
                else json.dumps(self.claude_json)
            )
            return rb.Completed(0, out, "")
        if "run" in args:
            status = "ok" if self.solve else "failed"
            envelope = json.dumps({"run_id": "r-1", "status": status, "usage": {}})
            return rb.Completed(0 if self.solve else 1, envelope, "")
        if "apply" in args:
            shutil.copytree(self.task.root / "solution", cwd, dirs_exist_ok=True)
            return rb.Completed(0, json.dumps({"applied": True}), "")
        return rb.Completed(0, "{}", "")


def _settings(tmp_path: Path) -> rb.Settings:
    return rb.Settings(out_dir=tmp_path / "results", work_dir=tmp_path / "work",
                       claude="claude", orkestra=["orkestra"], ollama_model="qwen-test",
                       claude_model=None, timeout_s=60)  # fmt: skip


def test_mode_a_runs_claude_without_skills_or_mcp_and_records_tokens(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    runner = FakeRunner(task)
    record = rb.run_once(task, "a", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    args, cwd, _ = runner.calls[0]
    assert args[:2] == ["claude", "-p"] and "--output-format" in args and "json" in args
    assert "--disable-slash-commands" in args and "--strict-mcp-config" in args
    assert not (cwd / ".claude" / "skills").exists()
    assert record.passed and record.mode == "a" and record.repeat == 1
    assert record.claude == {"input_tokens": 1200, "output_tokens": 800,
                             "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 300,
                             "cost_usd": 0.0421, "turns": 4}  # fmt: skip


def test_mode_b_gives_claude_the_skill_and_the_bench_orkestra_home(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    runner = FakeRunner(task)
    record = rb.run_once(task, "b", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    args, cwd, env = runner.calls[0]
    assert "--disable-slash-commands" not in args
    assert (cwd / ".claude" / "skills" / "orkestra" / "SKILL.md").is_file()
    assert env["ORKESTRA_HOME"] == str(tmp_path / "home")
    assert record.passed


def test_mode_c_runs_orkestra_alone_and_applies_a_passing_run(tmp_path: Path) -> None:
    task = _task()
    runner = FakeRunner(task)
    record = rb.run_once(task, "c", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    run_args = runner.calls[0][0]
    assert run_args[:2] == ["orkestra", "run"] and "--profile" in run_args and "cheap" in run_args
    assert runner.calls[1][0] == ["orkestra", "apply", "r-1", "--json"]
    assert record.passed and record.claude is None


def test_a_worker_that_fails_is_recorded_as_not_passed(tmp_path: Path) -> None:
    task = _task()
    runner = FakeRunner(task, solve=False)
    record = rb.run_once(task, "c", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    assert not record.passed
    assert len(runner.calls) == 1  # nothing to apply


def test_broken_claude_output_is_an_error_not_a_crash(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    runner = FakeRunner(task, solve=False, claude_json="not json")
    record = rb.run_once(task, "a", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    assert not record.passed and record.error and "json" in record.error.lower()


# --- results ------------------------------------------------------------------------------------


def _record(mode: str, repeat: int, task_id: str, passed: bool, tokens: int = 1000) -> rb.Record:
    claude = None if mode == "c" else {"input_tokens": tokens, "output_tokens": 100,
                                       "cache_read_input_tokens": 0,
                                       "cache_creation_input_tokens": 0, "cost_usd": 0.01,
                                       "turns": 2}  # fmt: skip
    return rb.Record(task=task_id, difficulty="easy", mode=mode, repeat=repeat, passed=passed,
                     duration_s=10.0, claude=claude, workers={"cost_usd": 0.0, "runs": 1,
                     "savings_tokens": 50}, error=None)  # fmt: skip


def test_summary_reports_mean_min_max_of_passes_per_repeat() -> None:
    records = [
        _record("a", 1, "t1", True), _record("a", 1, "t2", True),
        _record("a", 2, "t1", True), _record("a", 2, "t2", False),
        _record("a", 3, "t1", False), _record("a", 3, "t2", False),
    ]  # fmt: skip
    summary = rb.summarize(records)["a"]
    assert summary["tasks"] == 2
    assert summary["passed"] == {"mean": 1.0, "min": 0, "max": 2}
    assert summary["claude_tokens_per_task"] == pytest.approx(1100)


def test_the_markdown_table_has_a_row_per_mode_and_the_token_difference() -> None:
    records = [_record("a", 1, "t1", True, tokens=2000), _record("b", 1, "t1", True, tokens=500),
               _record("c", 1, "t1", False)]  # fmt: skip
    table = rb.markdown(rb.summarize(records), records)
    assert "| A - Claude only |" in table and "| C - Orkestra only (cheap) |" in table
    assert "1/1" in table and "0/1" in table
    assert "(A - B): 1,500" in table  # Claude tokens saved per task


def test_write_results_names_the_files_by_date(tmp_path: Path) -> None:
    records = [_record("a", 1, "t1", True)]
    json_path, md_path = rb.write_results(records, tmp_path, stamp="2026-11-15-1200",
                                          meta={"ollama_model": "x"})  # fmt: skip
    assert json_path.name == "2026-11-15-1200.json" and md_path.name == "2026-11-15-1200.md"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["meta"]["ollama_model"] == "x" and len(data["records"]) == 1


def test_dry_run_checks_every_task_and_starts_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = rb.main(["--mode", "all", "--repeat", "3", "--dry-run", "--work-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert f"{len(TASKS)} tasks" in out and f"= {len(TASKS) * 9} runs" in out
    assert "nothing was started" in out


# --- code review fixes (PR #25, D-077) ----------------------------------------------------


def test_claude_gets_the_prompt_on_stdin_and_no_argument_holds_a_newline(tmp_path: Path) -> None:
    task = _task("14-bugfix-csv-line")  # its prompt has quotes, a pipe-free "" and newlines
    for mode in ("a", "b"):
        runner = FakeRunner(task)
        rb.run_once(task, mode, 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
        args = runner.calls[0][0]
        assert all("\n" not in arg and '"' not in arg for arg in args), args
        assert task.prompt.strip() not in " ".join(args)
        assert runner.stdin[0] is not None and task.prompt.strip() in runner.stdin[0]
        settings_file = Path(args[args.index("--settings") + 1])
        allowed = json.loads(settings_file.read_text(encoding="utf-8"))["permissions"]["allow"]
        assert ("Bash(orkestra:*)" in allowed) == (mode == "b")
        if mode == "b":
            assert runner.stdin[0].startswith(rb.SKILL_HINT)
        else:
            assert rb.SKILL_HINT not in runner.stdin[0]


def test_a_hanging_visible_check_is_a_failure_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rb, "EVAL_TIMEOUT_S", 1)
    task = rb.Task(id="x", difficulty="easy", category="c", prompt="p", files=("a.py",),
                   root=tmp_path, check='python -c "import time; time.sleep(30)"')  # fmt: skip
    code, output = rb.run_check(task, tmp_path)
    assert code == 124 and "timed out" in output


def test_a_claude_timeout_keeps_the_reason_and_does_not_count_as_zero_tokens(
    tmp_path: Path,
) -> None:
    task = _task("01-docstring-geometry")
    runner = FakeRunner(task, claude_exit=124)
    record = rb.run_once(task, "a", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    assert not record.passed and record.claude is None
    assert record.error is not None and "124" in record.error and "timed out" in record.error
    good = _record("a", 1, "t1", True, tokens=1000)
    summary = rb.summarize([good, record])["a"]
    assert summary["claude_tokens_per_task"] == pytest.approx(1100)  # the timeout is left out
    assert summary["runs_without_usage"] == 1


def test_a_reformatted_stack_does_not_break_the_mutation_scoring(tmp_path: Path) -> None:
    task = _task("10-write-tests-stack")
    workspace = rb.prepare_workspace(task, tmp_path / "ws")
    shutil.copytree(task.root / "solution", workspace, dirs_exist_ok=True)
    stack = workspace / "stack.py"
    text = stack.read_text(encoding="utf-8")
    text = text.replace("return self._items.pop()", "return self._items.pop()  # the top")
    text = text.replace("def push(self, item):", "def push(self, item: object) -> None:")
    stack.write_text(text, encoding="utf-8")
    result = rb.evaluate(task, workspace, tmp_path / "eval")
    assert result.passed, result.output


def test_a_stack_changed_to_fit_weak_tests_is_still_caught(tmp_path: Path) -> None:
    task = _task("10-write-tests-stack")
    workspace = rb.prepare_workspace(task, tmp_path / "ws")
    shutil.copytree(task.root / "solution", workspace, dirs_exist_ok=True)
    stack = workspace / "stack.py"  # the worker "fixes" the code instead of the tests
    stack.write_text(stack.read_text(encoding="utf-8").replace(
        "return self._items.pop()", "return self._items.pop(0)"), encoding="utf-8")  # fmt: skip
    (workspace / "tests" / "test_stack.py").write_text(
        "from stack import Stack\n\ndef test_len():\n    assert len(Stack()) == 0\n",
        encoding="utf-8",
    )
    assert not rb.evaluate(task, workspace, tmp_path / "eval").passed


def test_the_dataclass_task_does_not_ask_for_the_impossible() -> None:
    assert "hash" not in _task("07-dataclass-point").prompt.lower()


def test_a_cache_imported_by_name_also_passes(tmp_path: Path) -> None:
    task = _task("20-cache-invalidation")
    workspace = rb.prepare_workspace(task, tmp_path / "ws")
    shutil.copytree(task.root / "solution", workspace, dirs_exist_ok=True)
    (workspace / "weather" / "admin.py").write_text(
        "from weather import api\nfrom weather.service import CACHE, _key\n\n\n"
        "def update_city(city, data):\n    api.store(_key(city), data)\n"
        "    CACHE.invalidate(_key(city))\n",
        encoding="utf-8",
    )
    result = rb.evaluate(task, workspace, tmp_path / "eval")
    assert result.passed, result.output


def test_a_leak_in_mode_c_stops_the_benchmark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task()
    real = rb.orkestra_task

    def leaky(t: rb.Task) -> dict[str, Any]:
        document = real(t)
        document["context"]["globs"] = ["../**/*.py"]
        return document

    monkeypatch.setattr(rb, "orkestra_task", leaky)
    with pytest.raises(rb.LeakError):
        rb.run_once(task, "c", 1, _settings(tmp_path), runner=FakeRunner(task),
                    home=tmp_path / "home")  # fmt: skip


def test_the_bench_home_config_is_valid_yaml_even_for_odd_model_ids(tmp_path: Path) -> None:
    from orkestra.config import loader

    settings = rb.Settings(out_dir=tmp_path, work_dir=tmp_path, claude="claude",
                           orkestra=["orkestra"], ollama_model="weird: model #1",
                           claude_model=None, timeout_s=1, ollama_model_2="second")  # fmt: skip
    rb.setup_home(tmp_path / "home", settings)
    config = loader.load_config(tmp_path / "home" / "config.yaml", cwd=tmp_path, environ={}).config
    models = [(m.id, m.tier) for m in config.providers["ollama"].models]  # type: ignore[union-attr]
    assert models == [("weird: model #1", 1), ("second", 2)]
    assert config.cache.enabled is False and config.routing.adaptive is False


def test_bench_errors_come_from_the_orkestra_hierarchy() -> None:
    from orkestra.errors import OrkestraError

    assert issubclass(rb.BenchError, OrkestraError) and issubclass(rb.LeakError, rb.BenchError)
