"""The benchmark harness (Faz 13a): tasks, the hidden-test leak guard, modes, results.

Nothing here starts Claude, Orkestra or a model: a fake runner plays them.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
from collections.abc import Sequence
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from bench import run_bench as rb

TASKS = rb.load_tasks(rb.TASKS_DIR)
BIG = rb.load_tasks(rb.SUITES["big"])  # Faz 13g


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


@pytest.mark.parametrize("task", TASKS + BIG, ids=lambda t: t.id)
def test_hidden_tests_fail_on_the_project_and_pass_on_the_solution(
    task: rb.Task, tmp_path: Path
) -> None:
    start = rb.prepare_workspace(task, tmp_path / "start")
    assert not rb.evaluate(task, start, tmp_path / "eval-start").passed
    solved = rb.prepare_workspace(task, tmp_path / "solved")
    shutil.copytree(task.root / "solution", solved, dirs_exist_ok=True)
    result = rb.evaluate(task, solved, tmp_path / "eval-solved")
    assert result.passed, result.output


@pytest.mark.parametrize("task", [t for t in TASKS + BIG if t.check], ids=lambda t: t.id)
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
                             "cost_usd": 0.0421, "turns": 4, "permission_denials": 0}  # fmt: skip


def test_mode_b_gives_claude_the_skill_and_the_bench_orkestra_home(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    runner = FakeRunner(task)
    record = rb.run_once(task, "b", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    args, cwd, env = runner.calls[0]
    assert "--disable-slash-commands" not in args
    assert (cwd / ".claude" / "skills" / "orkestra" / "SKILL.md").is_file()
    assert (cwd / ".claude" / "skills" / "orkestra" / "reference.md").is_file()
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


# --- quota guards (Faz 13b, D-078) ------------------------------------------------------------

LIMIT_JSON = {"type": "result", "subtype": "success", "is_error": True, "num_turns": 1,
              "result": "Claude AI usage limit reached|1763215200", "usage": {}}  # fmt: skip


def test_a_usage_limit_stops_the_run_and_is_not_recorded(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    runner = FakeRunner(task, solve=False, claude_json=LIMIT_JSON)
    with pytest.raises(rb.UsageLimitReached):
        rb.run_once(task, "a", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")


LIMIT_TEXTS = [
    "5-hour limit reached - resets 3pm",
    "API Error: 429 rate_limit_error",
    "Overloaded (529)",
]


@pytest.mark.parametrize("stderr", LIMIT_TEXTS)
def test_a_limit_in_stderr_of_a_failed_run_is_a_limit_too(tmp_path: Path, stderr: str) -> None:
    task = _task("01-docstring-geometry")

    def runner(args: Sequence[str], cwd: Path, env: dict[str, str], timeout: float,
               input_text: str | None = None) -> rb.Completed:  # fmt: skip
        return rb.Completed(1, "", stderr)

    with pytest.raises(rb.UsageLimitReached):
        rb.run_once(task, "a", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")


def test_the_same_words_in_a_good_answer_are_not_a_limit(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    answer = {**CLAUDE_JSON, "result": "Done. I also noted that the API has a rate limit."}
    runner = FakeRunner(task, claude_json=answer)
    record = rb.run_once(task, "a", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    assert record.passed and record.error is None


class ManyTasks:
    """Plays claude/orkestra for every task: the run folder's name says which task it is."""

    def __init__(self, limit_after: int | None = None) -> None:
        self.claude_runs = 0
        self.limit_after = limit_after
        self.keys: list[str] = []

    def _task(self, cwd: Path) -> rb.Task:
        return next(t for t in TASKS + BIG if cwd.parent.name.startswith(t.id + "-"))

    def __call__(self, args: Sequence[str], cwd: Path, env: dict[str, str], timeout: float,
                 input_text: str | None = None) -> rb.Completed:  # fmt: skip
        if "--version" in args:
            return rb.Completed(0, "9.9.9 (fake)", "")
        if Path(args[0]).stem.lower().startswith("claude"):
            if self.limit_after is not None and self.claude_runs >= self.limit_after:
                return rb.Completed(1, json.dumps(LIMIT_JSON), "")
            self.claude_runs += 1
            self.keys.append(cwd.parent.name)
            shutil.copytree(self._task(cwd).root / "solution", cwd, dirs_exist_ok=True)
            return rb.Completed(0, json.dumps(CLAUDE_JSON), "")
        if "run" in args:
            self.keys.append(cwd.parent.name)
            return rb.Completed(0, json.dumps({"run_id": "r-1", "status": "ok"}), "")
        if "apply" in args:
            shutil.copytree(self._task(cwd).root / "solution", cwd, dirs_exist_ok=True)
            return rb.Completed(0, "{}", "")
        return rb.Completed(0, "{}", "")


def _main(tmp_path: Path, runner: ManyTasks, *extra: str) -> int:
    argv = ["--mode", "all", "--tasks", "01,09", "--repeat", "1", "--out", str(tmp_path / "out"),
            "--work-dir", str(tmp_path / "work"), *extra]  # fmt: skip
    return rb.main(argv, runner=runner, which=lambda name: name)


def _saved(tmp_path: Path) -> dict[str, Any]:
    [path] = (tmp_path / "out").glob("*.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_main_stops_at_the_limit_keeps_what_was_done_and_says_how_to_resume(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _main(tmp_path, ManyTasks(limit_after=2))
    out = capsys.readouterr()
    assert code == 4
    done = [(r["task"], r["mode"]) for r in _saved(tmp_path)["records"]]
    assert done == [("01-docstring-geometry", "a"), ("01-docstring-geometry", "b"),
                    ("01-docstring-geometry", "c")]  # the limit came at 09's mode a  # fmt: skip
    assert "--resume" in out.out + out.err


def test_resume_runs_only_what_is_left_into_the_same_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _main(tmp_path, ManyTasks(limit_after=2)) == 4
    [first] = (tmp_path / "out").glob("*.json")
    runner = ManyTasks()
    code = rb.main(["--resume", str(first), "--work-dir", str(tmp_path / "work")],
                   runner=runner, which=lambda name: name)  # fmt: skip
    assert code == 0
    assert sorted(runner.keys) == ["09-bugfix-inventory-a-1", "09-bugfix-inventory-b-1",
                                   "09-bugfix-inventory-c-1"]  # fmt: skip
    data = _saved(tmp_path)  # still one file
    keys = [(r["task"], r["mode"], r["repeat"]) for r in data["records"]]
    assert len(keys) == 6 and len(set(keys)) == 6
    assert all(r["passed"] for r in data["records"])
    assert data["meta"]["repeat"] == 1 and data["meta"]["tasks"] == 2


def test_resume_can_add_repeats(tmp_path: Path) -> None:
    assert _main(tmp_path, ManyTasks()) == 0
    [first] = (tmp_path / "out").glob("*.json")
    runner = ManyTasks()
    assert rb.main(["--resume", str(first), "--repeat", "2", "--work-dir", str(tmp_path / "work")],
                   runner=runner, which=lambda name: name) == 0  # fmt: skip
    assert all(key.endswith("-2") for key in runner.keys) and len(runner.keys) == 6
    data = _saved(tmp_path)
    assert len(data["records"]) == 12 and data["meta"]["repeat"] == 2


def test_max_claude_runs_skips_further_claude_sessions_but_runs_the_rest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Faz 13d (D-110): past the limit only Claude sessions wait; mode C still runs, and the
    skipped sessions are left for ``--resume`` in the same results file."""
    runner = ManyTasks()
    code = _main(tmp_path, runner, "--max-claude-runs", "3")
    out = capsys.readouterr().out
    assert code == 0 and runner.claude_runs == 3
    modes = [(r["task"][:2], r["mode"]) for r in _saved(tmp_path)["records"]]
    assert modes == [("01", "a"), ("01", "b"), ("01", "c"), ("09", "a"), ("09", "c")]
    assert "1 Claude session" in out and "--resume" in out


def test_max_claude_runs_zero_runs_only_what_needs_no_claude_then_resume_adds_the_rest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = ManyTasks()
    assert _main(tmp_path, runner, "--max-claude-runs", "0") == 0
    assert runner.claude_runs == 0
    assert [r["mode"] for r in _saved(tmp_path)["records"]] == ["c", "c"]
    assert "4 Claude sessions" in capsys.readouterr().out
    [first] = (tmp_path / "out").glob("*.json")
    again = ManyTasks()
    assert rb.main(["--resume", str(first), "--work-dir", str(tmp_path / "work")],
                   runner=again, which=lambda name: name) == 0  # fmt: skip
    assert again.claude_runs == 4
    assert sorted(r["mode"] for r in _saved(tmp_path)["records"]) == ["a", "a", "b", "b", "c", "c"]


def test_resume_refuses_another_task_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _main(tmp_path, ManyTasks()) == 0
    [first] = (tmp_path / "out").glob("*.json")
    code = rb.main(["--resume", str(first), "--tasks", "01", "--work-dir", str(tmp_path / "work")],
                   runner=ManyTasks(), which=lambda name: name)  # fmt: skip
    assert code == 2 and "--tasks" in capsys.readouterr().err


# --- code review fixes (PR #26, D-079) ----------------------------------------------------


@pytest.mark.parametrize(
    ("stdout", "stderr"),
    [
        (json.dumps({**CLAUDE_JSON, "is_error": True, "subtype": "error_max_turns",
                     "usage": {"output_tokens": 529, "cache_creation_input_tokens": 429}}), ""),
        (json.dumps({**CLAUDE_JSON, "is_error": True, "result": "The context limit reached."}), ""),
        ("", "Error: tool failed after 429 ms"),
    ],
)  # fmt: skip
def test_numbers_and_other_limits_in_a_failure_are_not_a_usage_limit(
    tmp_path: Path, stdout: str, stderr: str
) -> None:
    task = _task("01-docstring-geometry")

    def runner(args: Sequence[str], cwd: Path, env: dict[str, str], timeout: float,
               input_text: str | None = None) -> rb.Completed:  # fmt: skip
        return rb.Completed(1, stdout, stderr)

    record = rb.run_once(task, "a", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    assert not record.passed and record.error  # a recorded failure, not a stop


def test_a_limit_in_the_event_list_form_is_seen(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    events = [{"type": "system"}, LIMIT_JSON]
    with pytest.raises(rb.UsageLimitReached):
        rb.run_once(task, "a", 1, _settings(tmp_path),
                    runner=FakeRunner(task, solve=False, claude_json=json.dumps(events)),
                    home=tmp_path / "home")  # fmt: skip


def test_a_limit_message_as_a_normal_result_is_still_a_limit(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    quiet = {**LIMIT_JSON, "is_error": False}  # exit 0, is_error false, the text says it
    with pytest.raises(rb.UsageLimitReached):
        rb.run_once(task, "a", 1, _settings(tmp_path),
                    runner=FakeRunner(task, solve=False, claude_json=quiet),
                    home=tmp_path / "home")  # fmt: skip


def test_results_are_written_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rb.write_results([_record("a", 1, "t1", True)], tmp_path, stamp="s", meta={})
    before = (tmp_path / "s.json").read_text(encoding="utf-8")

    def broken_dumps(*args: object, **kwargs: object) -> str:
        raise KeyboardInterrupt  # Ctrl+C while writing

    monkeypatch.setattr(rb.json, "dumps", broken_dumps)
    with pytest.raises(KeyboardInterrupt):
        rb.write_results([_record("a", 1, "t1", True), _record("a", 1, "t2", False)], tmp_path,
                         stamp="s", meta={})  # fmt: skip
    assert (tmp_path / "s.json").read_text(encoding="utf-8") == before


@pytest.mark.parametrize("content", [None, "not json", json.dumps({"meta": {}, "records": []})])
def test_a_file_that_cannot_be_resumed_is_a_clear_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str | None
) -> None:
    path = tmp_path / "old.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    code = rb.main(["--resume", str(path), "--work-dir", str(tmp_path / "work")],
                   runner=ManyTasks(), which=lambda name: name)  # fmt: skip
    assert code == 2 and "resume" in capsys.readouterr().err.lower()


def test_version_of_a_failing_or_hanging_program_is_unknown() -> None:
    def hanging(args: Sequence[str], cwd: Path, env: dict[str, str], timeout: float,
                input_text: str | None = None) -> rb.Completed:  # fmt: skip
        return rb.Completed(124, "", "timed out after 60 s")

    assert rb._version(["claude", "--version"], hanging) == "unknown"


def test_resume_refuses_another_model_or_timeout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _main(tmp_path, ManyTasks()) == 0
    [first] = (tmp_path / "out").glob("*.json")
    for extra in (["--claude-model", "opus"], ["--ollama-model", "other"], ["--timeout", "5"]):
        code = rb.main(["--resume", str(first), "--work-dir", str(tmp_path / "work"), *extra],
                       runner=ManyTasks(), which=lambda name: name)  # fmt: skip
        assert code == 2, extra
        assert extra[0] in capsys.readouterr().err


def test_resume_notes_a_new_claude_version_per_window(tmp_path: Path) -> None:
    assert _main(tmp_path, ManyTasks(limit_after=2)) == 4
    [first] = (tmp_path / "out").glob("*.json")

    class Updated(ManyTasks):
        def __call__(self, args: Sequence[str], *rest: Any, **kw: Any) -> rb.Completed:
            if "--version" in args:
                return rb.Completed(0, "10.0.0 (fake)", "")
            return super().__call__(args, *rest, **kw)

    assert rb.main(["--resume", str(first), "--work-dir", str(tmp_path / "work")],
                   runner=Updated(), which=lambda name: name) == 0  # fmt: skip
    windows = _saved(tmp_path)["meta"]["windows"]
    assert [w["claude"] for w in windows] == ["9.9.9 (fake)", "10.0.0 (fake)"]


def test_a_trailing_comma_in_tasks_matches_the_resumed_set(tmp_path: Path) -> None:
    assert _main(tmp_path, ManyTasks(limit_after=2)) == 4
    [first] = (tmp_path / "out").glob("*.json")
    argv = ["--resume", str(first), "--tasks", "01,09,", "--work-dir", str(tmp_path / "work")]
    assert rb.main(argv, runner=ManyTasks(), which=lambda n: n) == 0


def test_an_unfinished_repeat_is_not_scored_as_low() -> None:
    records = [_record("a", 1, "t1", True), _record("a", 1, "t2", True),
               _record("a", 2, "t1", True)]  # repeat 2 stopped halfway  # fmt: skip
    summary = rb.summarize(records)["a"]
    assert summary["passed"] == {"mean": 2.0, "min": 2, "max": 2}
    assert summary["complete_repeats"] == 1 and summary["partial_runs"] == 1
    assert "partial" in rb.markdown(rb.summarize(records), records).lower()


def test_the_report_header_is_readable(tmp_path: Path) -> None:
    meta = {"task_ids": ["01-a", "02-b"], "claude_model": None, "ollama_model_2": None,
            "windows": [{"date": "d", "claude": "1", "orkestra": "2", "runs": 3}]}  # fmt: skip
    _, md = rb.write_results([_record("a", 1, "t1", True)], tmp_path, stamp="s", meta=meta)
    header = md.read_text(encoding="utf-8").split("|", 1)[0]
    assert "None" not in header and "['01-a'" not in header
    assert "claude_model: default" in header and "tasks: 01-a, 02-b" in header


# --- Faz 13c: what the first real run showed (D-080) ---------------------------------------


def test_denied_tools_are_counted_and_the_raw_output_is_kept(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    denied = {**CLAUDE_JSON, "permission_denials": [{"tool_name": "Bash"}, {"tool_name": "Bash"}]}
    runner = FakeRunner(task, claude_json=denied)
    record = rb.run_once(task, "a", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    assert record.claude is not None and record.claude["permission_denials"] == 2
    raw = tmp_path / "work" / "01-docstring-geometry-a-1" / "claude-output.json"
    assert (
        json.loads(raw.read_text(encoding="utf-8"))["permission_denials"][0]["tool_name"] == "Bash"
    )


def test_the_markdown_reports_denied_tools() -> None:
    record = _record("a", 1, "t1", True)
    assert record.claude is not None
    record.claude["permission_denials"] = 3
    summary = rb.summarize([record])
    assert summary["a"]["permission_denials"] == 3
    assert "denied" in rb.markdown(summary, [record]).lower()


def test_the_evaluation_has_no_asyncio_warning(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    solved = rb.prepare_workspace(task, tmp_path / "ws")
    shutil.copytree(task.root / "solution", solved, dirs_exist_ok=True)
    result = rb.evaluate(task, solved, tmp_path / "eval")
    assert result.passed and "PytestDeprecationWarning" not in result.output


def test_records_never_hold_personal_paths(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    home = str(Path.home())

    def runner(args: Sequence[str], cwd: Path, env: dict[str, str], timeout: float,
               input_text: str | None = None) -> rb.Completed:  # fmt: skip
        return rb.Completed(1, "", f"Traceback: {home}{os.sep}x.py and {cwd}{os.sep}y.py")

    record = rb.run_once(task, "a", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    text = json.dumps(dataclasses.asdict(record))
    assert home not in text and home.replace("\\", "\\\\") not in text
    assert str(tmp_path) not in text and str(tmp_path).replace("\\", "\\\\") not in text
    assert "~" in (record.error or "") or "<work>" in (record.error or "")


# --- code review fixes (PR #27, D-081) ----------------------------------------------------

FAKE_HOME = Path("C:/Users/Someone") if os.name == "nt" else Path("/home/someone")


def _scrubber() -> rb.Scrubber:
    return rb.Scrubber([(FAKE_HOME, "~")])


def test_a_cut_never_leaves_part_of_a_personal_path() -> None:
    text = "start " + str(FAKE_HOME / "proj" / "x.py") + " end"
    for cut in range(1, len(text)):
        tail = rb.clean_tail(text, cut, _scrubber())
        assert "omeone" not in tail and "Someone" not in tail, (cut, tail)


def test_quoted_lowercase_and_posix_forms_are_scrubbed() -> None:
    raw = str(FAKE_HOME / "x")
    forms = [raw, raw.replace("\\", "\\\\"), raw.lower(), raw.upper(), FAKE_HOME.as_posix() + "/x"]
    for form in forms:
        assert "omeone" not in _scrubber()(f"error: {form!s} and {form!r}").lower(), form


def test_a_sibling_folder_is_not_mangled() -> None:
    sibling = str(FAKE_HOME) + "2" + os.sep + "x"
    assert _scrubber()(sibling) == sibling


def test_a_relative_work_dir_never_replaces_ordinary_text(tmp_path: Path) -> None:
    scrubber = rb.Scrubber.for_run(Path("."))
    assert scrubber("5 passed in 0.03s") == "5 passed in 0.03s"


def test_written_results_are_scrubbed_even_for_resumed_records(tmp_path: Path) -> None:
    home = str(Path.home())
    record = _record("a", 1, "t1", False)
    record.output_tail = f"Traceback: {home}{os.sep}x.py"
    record.error = f"failed in {home!r}"
    json_path, md_path = rb.write_results([record], tmp_path, stamp="s", meta={"m": home})
    for path in (json_path, md_path):
        text = path.read_text(encoding="utf-8")
        assert home not in text and home.replace("\\", "\\\\") not in text


def test_denials_that_were_never_measured_are_unknown_not_zero() -> None:
    old = _record("a", 1, "t1", True)  # a record from before permission_denials existed
    assert old.claude is not None and "permission_denials" not in old.claude
    assert rb.summarize([old])["a"]["permission_denials"] is None


def test_a_retried_run_does_not_keep_an_old_stderr_file(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    stale = tmp_path / "work" / "01-docstring-geometry-a-1" / "claude-stderr.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("usage limit reached", encoding="utf-8")
    rb.run_once(task, "a", 1, _settings(tmp_path), runner=FakeRunner(task), home=tmp_path / "home")
    assert not stale.exists()


def test_async_hidden_tests_still_run(tmp_path: Path) -> None:
    root = tmp_path / "task"
    (root / "project").mkdir(parents=True)
    (root / "project" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "hidden").mkdir()
    (root / "hidden" / "test_async_hidden.py").write_text(
        "import pytest\nimport mod\n\n\n@pytest.mark.asyncio\nasync def test_it():\n"
        "    assert mod.VALUE == 1\n", encoding="utf-8")  # fmt: skip
    task = rb.Task(id="async", difficulty="easy", category="c", prompt="p", files=("mod.py",),
                   root=root)  # fmt: skip
    workspace = rb.prepare_workspace(task, tmp_path / "ws")
    result = rb.evaluate(task, workspace, tmp_path / "eval")
    assert result.passed, result.output
    assert "PytestDeprecationWarning" not in result.output


# --- Faz 13d: mode D, delegation asked for (D-082) ------------------------------------------


def test_mode_d_asks_claude_to_delegate_with_the_skill_and_permission(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    runner = FakeRunner(task)
    record = rb.run_once(task, "d", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    args, cwd, env = runner.calls[0]
    assert "--disable-slash-commands" not in args
    assert (cwd / ".claude" / "skills" / "orkestra" / "SKILL.md").is_file()
    assert runner.stdin[0] is not None and runner.stdin[0].startswith(rb.DELEGATE_HINT)
    allowed = json.loads(Path(args[args.index("--settings") + 1]).read_text(encoding="utf-8"))
    assert "Bash(orkestra:*)" in allowed["permissions"]["allow"]
    assert env["ORKESTRA_HOME"] == str(tmp_path / "home")
    assert record.passed and record.mode == "d"


def test_all_is_still_the_three_planned_modes_and_d_is_chosen_on_its_own(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert rb.main(["--dry-run", "--tasks", "01", "--work-dir", str(tmp_path)]) == 0
    assert "x 3 modes" in capsys.readouterr().out
    runner = ManyTasks()
    argv = ["--mode", "d", "--tasks", "01", "--repeat", "1", "--out", str(tmp_path / "out"),
            "--work-dir", str(tmp_path / "work")]  # fmt: skip
    assert rb.main(argv, runner=runner, which=lambda name: name) == 0
    assert runner.claude_runs == 1
    assert [r["mode"] for r in _saved(tmp_path)["records"]] == ["d"]


def test_the_report_compares_d_with_a_too() -> None:
    records = [_record("a", 1, "t1", True, tokens=2000), _record("d", 1, "t1", True, tokens=800)]
    table = rb.markdown(rb.summarize(records), records)
    assert "D - Claude + Orkestra, delegation asked" in table
    assert "(A - D): 1,200" in table


def test_powershell_and_read_only_commands_are_allowed_like_their_bash_forms(
    tmp_path: Path,
) -> None:
    for mode in ("a", "b", "d"):
        allowed = json.loads(rb.claude_settings(mode, tmp_path / f"{mode}.json")
                             .read_text(encoding="utf-8"))["permissions"]["allow"]  # fmt: skip
        expected = [
            "PowerShell(python:*)",
            "PowerShell(git:*)",
            "PowerShell(Get-Content:*)",
            "PowerShell(Get-ChildItem:*)",
            "Bash(cd:*)",
            "Bash(ls:*)",
            "Bash(cat:*)",
        ]
        for tool in expected:
            assert tool in allowed, (mode, tool)
        assert ("PowerShell(orkestra:*)" in allowed) == (mode in ("b", "d"))


# --- code review fixes (PR #28, D-083) ----------------------------------------------------


def test_a_mode_list_runs_a_and_d_together_and_reports_the_difference(tmp_path: Path) -> None:
    argv = ["--mode", "a,d", "--tasks", "01", "--repeat", "1", "--out", str(tmp_path / "out"),
            "--work-dir", str(tmp_path / "work")]  # fmt: skip
    assert rb.main(argv, runner=ManyTasks(), which=lambda name: name) == 0
    data = _saved(tmp_path)
    assert [r["mode"] for r in data["records"]] == ["a", "d"]
    [md] = (tmp_path / "out").glob("*.md")
    assert "(A - D)" in md.read_text(encoding="utf-8")


def test_an_unknown_mode_in_a_list_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert rb.main(["--mode", "a,x", "--dry-run", "--work-dir", str(tmp_path)]) == 2
    assert "x" in capsys.readouterr().err


def test_powershell_aliases_are_allowed_and_nothing_that_writes_files(tmp_path: Path) -> None:
    required = {f"Bash({c}:*)" for c in ("python", "pytest", "git", "cd", "ls", "cat", "pwd")}
    required |= {f"PowerShell({c}:*)" for c in (
        "python", "pytest", "git", "cd", "ls", "dir", "cat", "type", "pwd", "Get-Content",
        "Get-ChildItem", "Select-String", "Set-Location", "Get-Location")}  # fmt: skip
    for mode in ("a", "b", "d"):
        allowed = set(json.loads(rb.claude_settings(mode, tmp_path / f"{mode}.json")
                                 .read_text(encoding="utf-8"))["permissions"]["allow"])  # fmt: skip
        assert required <= allowed, (mode, sorted(required - allowed))
        assert not {"Bash(echo:*)", "PowerShell(echo:*)", "PowerShell(Write-Output:*)"} & allowed


def test_the_results_say_which_tool_list_was_used(tmp_path: Path) -> None:
    assert _main(tmp_path, ManyTasks()) == 0
    meta = _saved(tmp_path)["meta"]
    assert meta["claude_tools"] == list(rb.CLAUDE_TOOLS)
    assert meta["orkestra_tools"] == list(rb.ORKESTRA_TOOLS)


def test_a_missing_claude_names_every_mode_that_needs_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--mode", "d", "--tasks", "01", "--repeat", "1", "--work-dir", str(tmp_path)]
    assert rb.main(argv, runner=ManyTasks(), which=lambda name: None) == 2
    assert "a, b, d" in capsys.readouterr().err


def test_help_says_b_and_d_can_use_the_second_model() -> None:
    assert "B and D" in rb._parser().format_help().replace("\n", " ").replace("  ", " ")


def test_every_mode_is_described_in_one_place() -> None:
    for key, mode in rb.MODES.items():
        assert mode.label.startswith(key.upper() + " - ")
        # A hint about Orkestra needs the skill (Claude) or the chief guide (an agent chief).
        assert (mode.hint is not None) <= (mode.skill or mode.agent is not None)
        assert not (mode.skill and not mode.chief)
        assert not (mode.agent and mode.chief)  # an agent chief is no Claude session
    assert rb.PLANNED_MODES == ("a", "b", "c") and rb.CHIEF_MODES == ("a", "b", "d", "f", "g")
    assert rb.AGENT_MODES == ("e",)


# --- mode E: agy is the chief (Faz 13n) -------------------------------------------------------

AGY_JSON = {"conversation_id": "c-1", "status": "SUCCESS", "response": "done",
            "duration_seconds": 31.0, "num_turns": 3,
            "usage": {"input_tokens": 15591, "output_tokens": 864, "thinking_tokens": 770,
                      "cache_read_tokens": 17232, "total_tokens": 16455}}  # fmt: skip


class AgyRunner(FakeRunner):
    """Plays ``agy`` as well: it reads the prompt file it is pointed at, then "solves"."""

    def __init__(self, task: rb.Task, *, agy_out: str | None = None, agy_exit: int = 0,
                 agy_err: str = "", solve: bool = True) -> None:  # fmt: skip
        super().__init__(task, solve=solve)
        self.agy_out = json.dumps(AGY_JSON) if agy_out is None else agy_out
        self.agy_exit, self.agy_err = agy_exit, agy_err
        self.prompts: list[str] = []

    def __call__(
        self, args: Sequence[str], cwd: Path, env: dict[str, str], timeout: float,
        input_text: str | None = None,
    ) -> rb.Completed:  # fmt: skip
        if Path(args[0]).stem.lower() != "agy":
            return super().__call__(args, cwd, env, timeout, input_text)
        self.calls.append((list(args), cwd, dict(env)))
        pointer = args[-1]
        prompt_file = Path(pointer.split("Read the file ", 1)[1].split(" and follow", 1)[0])
        self.prompts.append(prompt_file.read_text(encoding="utf-8"))
        if self.solve and not self.agy_exit:
            shutil.copytree(self.task.root / "solution", cwd, dirs_exist_ok=True)
        return rb.Completed(self.agy_exit, self.agy_out, self.agy_err)


def test_mode_e_runs_agy_as_chief_with_the_guide_and_records_its_tokens(tmp_path: Path) -> None:
    from orkestra.handoff import brief

    task = _task("14-bugfix-csv-line")
    runner = AgyRunner(task)
    record = rb.run_once(task, "e", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    args, cwd, env = runner.calls[0]
    assert Path(args[0]).stem == "agy" and "--print" in args
    assert "--sandbox" not in args  # print mode with a sandbox refuses shell commands (D-048)
    assert "--output-format" in args and "json" in args
    assert all("\n" not in arg and '"' not in arg for arg in args), args
    assert task.prompt.strip() not in " ".join(args)
    prompt = runner.prompts[0]
    assert prompt.startswith(rb.AGENT_HINT)
    assert all(line in prompt for line in brief.guide_lines())
    assert task.prompt.strip() in prompt
    assert not (cwd / ".claude").exists()
    assert env["ORKESTRA_HOME"] == str(tmp_path / "home") and env["ORKESTRA_CHIEF"] == "agy"
    assert record.passed and record.claude is None
    assert record.agent == {
        "name": "agy", "input_tokens": 15591, "output_tokens": 864, "thinking_tokens": 770,
        "cache_read_tokens": 17232, "turns": 3,
    }  # fmt: skip


def test_mode_e_is_never_part_of_all() -> None:
    assert "e" not in rb.parse_modes("all")
    assert rb.parse_modes("e") == ["e"]
    assert "e" not in rb.CHIEF_MODES  # it is no Claude session (--max-claude-runs)


def test_an_agy_quota_message_stops_the_benchmark(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    runner = AgyRunner(task, agy_out="", agy_exit=1,
                       agy_err="RESOURCE_EXHAUSTED: You have exhausted your capacity on this "
                               "model. Your quota will reset after 5h19m.")  # fmt: skip
    with pytest.raises(rb.UsageLimitReached):
        rb.run_once(task, "e", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")


def test_a_failed_agy_run_keeps_the_reason_and_no_token_count(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    runner = AgyRunner(task, agy_out="not json", agy_exit=2, agy_err="crashed", solve=False)
    record = rb.run_once(task, "e", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    assert not record.passed and record.agent is None
    assert record.error is not None and "agy exited with 2" in record.error


def _agent_record(repeat: int, task_id: str, passed: bool) -> rb.Record:
    record = _record("e", repeat, task_id, passed)
    return dataclasses.replace(record, claude=None, agent={
        "name": "agy", "input_tokens": 1000, "output_tokens": 200, "thinking_tokens": 50,
        "cache_read_tokens": 3000, "turns": 2})  # fmt: skip


def test_the_summary_and_table_show_the_agent_chiefs_tokens() -> None:
    records = [_agent_record(1, "t1", True), _agent_record(1, "t2", False),
               _record("a", 1, "t1", True), _record("a", 1, "t2", True)]  # fmt: skip
    summary = rb.summarize(records)
    assert summary["e"]["agent_tokens_per_task"] == pytest.approx(1250)
    assert summary["e"]["claude_tokens_per_task"] is None
    assert summary["a"]["agent_tokens_per_task"] is None
    table = rb.markdown(summary, records)
    assert "| E - agy chief + Orkestra |" in table
    assert "agy (chief) tokens per task (E): 1,250" in table


def test_old_results_without_the_agent_field_still_load() -> None:
    data = dataclasses.asdict(_record("a", 1, "t1", True))
    del data["agent"]
    assert rb.Record(**data).agent is None


# --- code review of PR #38 (D-103) -------------------------------------------------------------


def test_no_hidden_test_is_left_behind_for_a_later_chief(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    settings = _settings(tmp_path)
    rb.run_once(task, "a", 1, settings, runner=FakeRunner(task), home=tmp_path / "home")
    left = [p for p in settings.work_dir.rglob("*") if "_hidden_tests" in p.parts]
    assert left == []


def test_an_agent_that_touched_the_hidden_tests_stops_the_benchmark(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")

    class Peeking(AgyRunner):
        def __call__(self, args: Sequence[str], cwd: Path, env: dict[str, str], timeout: float,
                     input_text: str | None = None) -> rb.Completed:  # fmt: skip
            done = super().__call__(args, cwd, env, timeout, input_text)
            if Path(args[0]).stem.lower() == "agy":
                log = Path(args[args.index("--log-file") + 1])
                log.write_text("read ../../x-a-1/eval/_hidden_tests/test_x.py", encoding="utf-8")
            return done

    with pytest.raises(rb.LeakError):
        rb.run_once(task, "e", 1, _settings(tmp_path), runner=Peeking(task),
                    home=tmp_path / "home")  # fmt: skip


@pytest.mark.parametrize("stderr", ["HTTP 429 Too Many Requests", "rate limit exceeded, retry"])
def test_a_soft_rate_limit_of_agy_is_a_failed_run_not_a_stop(tmp_path: Path, stderr: str) -> None:
    task = _task("01-docstring-geometry")
    runner = AgyRunner(task, agy_out="", agy_exit=1, agy_err=stderr, solve=False)
    record = rb.run_once(task, "e", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    assert not record.passed and record.error is not None


def test_a_quota_message_with_exit_0_and_no_json_still_stops(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    runner = AgyRunner(task, agy_out="", agy_exit=0,
                       agy_err="RESOURCE_EXHAUSTED: quota will reset after 5h19m.")  # fmt: skip
    with pytest.raises(rb.UsageLimitReached):
        rb.run_once(task, "e", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")


def test_a_banner_line_before_agys_json_is_not_a_lost_result(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    runner = AgyRunner(task, agy_out="A new version is available.\n" + json.dumps(AGY_JSON))
    record = rb.run_once(task, "e", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    assert record.error is None and record.agent is not None
    assert record.agent["input_tokens"] == 15591


def test_exit_0_without_a_result_is_an_error_with_a_reason(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    runner = AgyRunner(task, agy_out="", agy_exit=0, solve=False)
    record = rb.run_once(task, "e", 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    assert record.error is not None and "no status" in record.error


def test_agy_times_out_by_itself_before_it_is_killed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    args = rb.agent_args(settings, tmp_path / "p.md", tmp_path / "a.log")
    own = int(args[args.index("--print-timeout") + 1].rstrip("s"))
    assert 0 < own < settings.timeout_s


def test_without_any_agent_usage_the_tokens_are_unknown_not_zero() -> None:
    records = [dataclasses.replace(_agent_record(1, "t1", True), agent=None)]
    summary = rb.summarize(records)["e"]
    assert summary["agent_tokens_per_task"] is None
    assert summary["agent_runs_without_usage"] == 1
    assert "tokens per task (E)" not in rb.markdown(rb.summarize(records), records)
    mixed = [_agent_record(1, "t1", True), records[0]]
    table = rb.markdown(rb.summarize(mixed), mixed)
    assert "1 run(s) without usage" in table


def test_the_agent_prompt_uses_the_hint_of_its_mode() -> None:
    mode = rb.MODES["e"]
    assert rb.agent_prompt("do it", mode.hint or "").startswith(mode.hint or "")
    assert rb.agent_prompt("do it", "OTHER HINT").startswith("OTHER HINT")


def test_the_window_records_the_agent_version(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")

    class Versions(AgyRunner):
        def __call__(self, args: Sequence[str], cwd: Path, env: dict[str, str], timeout: float,
                     input_text: str | None = None) -> rb.Completed:  # fmt: skip
            if list(args[1:]) == ["--version"]:
                return rb.Completed(0, "1.5.12\n", "")
            return super().__call__(args, cwd, env, timeout, input_text)

    out = tmp_path / "results"
    code = rb.main(["--mode", "e", "--tasks", "01", "--repeat", "1", "--out", str(out),
                    "--work-dir", str(tmp_path / "work")],
                   runner=Versions(task), which=lambda name: name)  # fmt: skip
    assert code == 0
    data = json.loads(next(out.glob("*.json")).read_text(encoding="utf-8"))
    assert data["meta"]["windows"][0]["agy"] == "1.5.12"


# --- Faz 13d: agy as the worker (D-111) -------------------------------------------------------


def test_worker_agy_makes_agy_the_only_tier_1_worker(tmp_path: Path) -> None:
    from contextlib import closing

    from orkestra.config import loader
    from orkestra.state import consent, db

    settings = rb.Settings(out_dir=tmp_path, work_dir=tmp_path, claude="claude",
                           orkestra=["orkestra"], ollama_model="qwen-test",
                           claude_model=None, timeout_s=1, agy="agy-bin",
                           worker="agy")  # fmt: skip
    rb.setup_home(tmp_path / "home", settings)
    config = loader.load_config(tmp_path / "home" / "config.yaml", cwd=tmp_path, environ={}).config
    assert list(config.providers) == ["agy"]
    agy = config.providers["agy"]
    assert agy.type == "cli_agent" and agy.command == "agy-bin"  # type: ignore[union-attr]
    assert agy.kind == "agy" and agy.tier == 1  # type: ignore[union-attr]
    # experimental: the router skips it unless enabled is written out (router.py)
    assert "enabled" in agy.model_fields_set and agy.enabled
    with closing(db.connect(tmp_path / "home" / "state.db")) as conn:
        assert consent.state(conn, "agy", agy) == "granted"


def test_worker_defaults_to_ollama(tmp_path: Path) -> None:
    assert _settings(tmp_path).worker == "ollama"
    assert _main(tmp_path, ManyTasks()) == 0
    assert _saved(tmp_path)["meta"]["worker"] == "ollama"


def test_worker_agy_needs_agy_on_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["--mode", "d", "--tasks", "01", "--repeat", "1", "--worker", "agy",
            "--out", str(tmp_path / "out"), "--work-dir", str(tmp_path / "work")]  # fmt: skip
    code = rb.main(argv, runner=ManyTasks(), which=lambda name: None if name == "agy" else name)
    assert code == 2 and "agy" in capsys.readouterr().err


def test_resume_refuses_another_worker(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _main(tmp_path, ManyTasks()) == 0
    [first] = (tmp_path / "out").glob("*.json")
    code = rb.main(["--resume", str(first), "--work-dir", str(tmp_path / "work"),
                    "--worker", "agy"], runner=ManyTasks(), which=lambda name: name)  # fmt: skip
    assert code == 2 and "--worker" in capsys.readouterr().err


# --- PR #42 review (D-112) --------------------------------------------------------------------


def _agy_settings(tmp_path: Path, timeout_s: float = 900) -> rb.Settings:
    return rb.Settings(out_dir=tmp_path / "results", work_dir=tmp_path / "work", claude="claude",
                       orkestra=["orkestra"], ollama_model="qwen-test", claude_model=None,
                       timeout_s=timeout_s, agy="agy", worker="agy")  # fmt: skip


def _agy_config(tmp_path: Path, timeout_s: float) -> Any:
    from orkestra.config import loader

    rb.setup_home(tmp_path / "home", _agy_settings(tmp_path, timeout_s))
    path = tmp_path / "home" / "config.yaml"
    return loader.load_config(path, cwd=tmp_path, environ={}).config.providers["agy"]


def test_the_agy_worker_times_out_well_before_the_run(tmp_path: Path) -> None:
    assert _agy_config(tmp_path, 900).timeout_s == 600
    assert _agy_config(tmp_path / "tiny", 0.5).timeout_s == 1  # no crash below 1 s


def _quota_event(home: Path, provider: str) -> None:
    from orkestra.state import db, forecast

    with closing(db.connect(home / "state.db")) as conn, conn:
        forecast.record_event(conn, provider, db.local_now(), None)


def test_a_worker_quota_after_the_start_is_found(tmp_path: Path) -> None:
    home = tmp_path / "home"
    rb.setup_home(home, _agy_settings(tmp_path))
    started = datetime.now().astimezone()
    assert rb.worker_quota_hit(home, started) is None
    _quota_event(home, "agy")
    assert rb.worker_quota_hit(home, started) == "agy"
    assert rb.worker_quota_hit(tmp_path / "nowhere", started) is None


def test_a_worker_quota_stops_the_bench_labelled_with_the_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(rb, "worker_quota_hit", lambda home, since: "agy")
    argv = ["--mode", "c", "--tasks", "01", "--repeat", "1", "--worker", "agy",
            "--out", str(tmp_path / "out"), "--work-dir", str(tmp_path / "work")]  # fmt: skip
    assert rb.main(argv, runner=ManyTasks(), which=lambda name: name) == 4
    err = capsys.readouterr().err
    assert "usage limit (agy)" in err and "Claude" not in err


def test_a_worker_agy_run_writes_no_ollama_model_and_refuses_ollama_flags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = ["--mode", "c", "--tasks", "01", "--repeat", "1", "--worker", "agy",
            "--out", str(tmp_path / "out"), "--work-dir", str(tmp_path / "work")]  # fmt: skip
    for extra in (["--ollama-model", "x"], ["--ollama-model-2", "y"]):
        assert rb.main([*base, *extra], runner=ManyTasks(), which=lambda n: n) == 2, extra
        assert extra[0] in capsys.readouterr().err
    assert rb.main(base, runner=ManyTasks(), which=lambda n: n) == 0
    meta = _saved(tmp_path)["meta"]
    assert meta["worker"] == "agy" and meta["ollama_model"] is None
    md = next((tmp_path / "out").glob("*.md")).read_text(encoding="utf-8")
    assert "ollama_model: -" in md and ", agy 9.9.9 (fake), skill " in md  # agy's version


def test_a_delegating_run_without_any_worker_run_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class NoWorker(ManyTasks):
        def __call__(self, args: Sequence[str], cwd: Path, env: dict[str, str], timeout: float,
                     input_text: str | None = None) -> rb.Completed:  # fmt: skip
            if "run" in args:  # the worker never ran: nothing applied
                return rb.Completed(1, "", "no provider")
            return super().__call__(args, cwd, env, timeout, input_text)

    _main(tmp_path, NoWorker())
    assert "no worker run" in capsys.readouterr().out


def test_each_window_records_the_skill_and_a_change_is_noted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PR #43 review (D-114): a resumed run must show when the skill changed between windows."""
    assert _main(tmp_path, ManyTasks(limit_after=2)) == 4
    [first] = (tmp_path / "out").glob("*.json")
    capsys.readouterr()
    other = tmp_path / "SKILL.md"
    other.write_text("another skill", encoding="utf-8")
    monkeypatch.setattr(rb, "SKILL_FILES", (other,))
    assert rb.main(["--resume", str(first), "--work-dir", str(tmp_path / "work")],
                   runner=ManyTasks(), which=lambda name: name) == 0  # fmt: skip
    windows = _saved(tmp_path)["meta"]["windows"]
    assert len({w["skill"] for w in windows}) == 2 and all(len(w["skill"]) == 12 for w in windows)
    assert "skill" in capsys.readouterr().err
    md = next((tmp_path / "out").glob("*.md")).read_text(encoding="utf-8")
    assert f"skill {windows[-1]['skill']}" in md


# --- Faz 13g: the big suite, arms F and G, a cross reviewer ----------------------------------


def test_the_big_suite_has_big_tasks_with_a_project_hidden_tests_and_a_solution() -> None:
    assert BIG, "no big benchmark task"
    for task in BIG:
        assert task.difficulty == "big" and task.check, task.id
        assert (task.root / "project").is_dir() and any((task.root / "hidden").glob("test_*.py"))
        lines = sum(len(f.read_text(encoding="utf-8").splitlines())
                    for f in (task.root / "project").rglob("*")
                    if f.is_file() and "__pycache__" not in f.parts)  # fmt: skip
        assert lines >= 1500, f"{task.id}: a big task starts from a big project ({lines} lines)"


def test_the_small_suite_is_the_default_and_big_is_chosen_with_suite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert rb.SUITES["small"] == rb.TASKS_DIR
    argv = ["--suite", "big", "--mode", "a", "--repeat", "2", "--dry-run",
            "--work-dir", str(tmp_path)]  # fmt: skip
    assert rb.main(argv) == 0
    assert f"{len(BIG)} tasks x 1 modes x 2 repeats" in capsys.readouterr().out


def test_the_suite_is_recorded_and_a_resume_stays_in_it(tmp_path: Path) -> None:
    argv = ["--suite", "big", "--mode", "a", "--repeat", "1", "--out", str(tmp_path / "out"),
            "--work-dir", str(tmp_path / "work")]  # fmt: skip
    assert rb.main(argv, runner=ManyTasks(), which=lambda name: name) == 0
    [first] = (tmp_path / "out").glob("*.json")
    data = _saved(tmp_path)
    assert data["meta"]["suite"] == "big" and data["meta"]["task_ids"] == [t.id for t in BIG]
    runner = ManyTasks()
    resume = ["--resume", str(first), "--repeat", "2", "--work-dir", str(tmp_path / "work")]
    assert rb.main(resume, runner=runner, which=lambda name: name) == 0
    assert runner.claude_runs == len(BIG)  # the big task again, never the small set
    bad = ["--resume", str(first), "--suite", "small", "--work-dir", str(tmp_path / "work")]
    assert rb.main(bad, runner=ManyTasks(), which=lambda name: name) == 2


@pytest.mark.parametrize(("mode", "hint"), [("f", "FILTER_HINT"), ("g", "FULL_HINT")])
def test_arms_f_and_g_get_the_skill_and_their_own_hint(
    mode: str, hint: str, tmp_path: Path
) -> None:
    task = _task("01-docstring-geometry")
    runner = FakeRunner(task)
    record = rb.run_once(task, mode, 1, _settings(tmp_path), runner=runner, home=tmp_path / "home")
    args, cwd, _ = runner.calls[0]
    assert (cwd / ".claude" / "skills" / "orkestra" / "SKILL.md").is_file()
    assert runner.stdin[0] is not None and runner.stdin[0].startswith(getattr(rb, hint))
    allowed = json.loads(Path(args[args.index("--settings") + 1]).read_text(encoding="utf-8"))
    assert "Bash(orkestra:*)" in allowed["permissions"]["allow"]
    assert record.passed and mode not in rb.PLANNED_MODES


def test_arm_f_only_filters_context_and_arm_g_also_delegates() -> None:
    assert "orkestra exec" in rb.FILTER_HINT and "orkestra read" in rb.FILTER_HINT
    assert "do not hand" in rb.FILTER_HINT.lower()
    assert "orkestra exec" in rb.FULL_HINT and "batch" in rb.FULL_HINT
    assert "review" in rb.FULL_HINT and "--report" in rb.FULL_HINT
    assert "g" in rb.DELEGATING_MODES and "f" not in rb.DELEGATING_MODES


def test_a_cross_reviewer_is_another_provider_that_never_writes_first(tmp_path: Path) -> None:
    from orkestra.config import loader

    settings = dataclasses.replace(_settings(tmp_path), worker="agy", reviewer="ollama")
    rb.setup_home(tmp_path / "home", settings)
    config = loader.load_config(tmp_path / "home" / "config.yaml", cwd=tmp_path, environ={}).config
    assert set(config.providers) == {"agy", "ollama"}
    assert config.providers["agy"].tier == 1  # type: ignore[union-attr]
    assert [m.tier for m in config.providers["ollama"].models] == [2]  # type: ignore[union-attr]
    assert config.review.by == {"agy": ["ollama"]} and config.review.independent is True


def test_a_reviewer_is_recorded_and_must_match_on_resume(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--mode", "a", "--tasks", "01", "--repeat", "1", "--worker", "agy",
            "--reviewer", "ollama", "--out", str(tmp_path / "out"),
            "--work-dir", str(tmp_path / "work")]  # fmt: skip
    assert rb.main(argv, runner=ManyTasks(), which=lambda name: name) == 0
    [first] = (tmp_path / "out").glob("*.json")
    assert _saved(tmp_path)["meta"]["reviewer"] == "ollama"
    bad = ["--resume", str(first), "--reviewer", "none", "--work-dir", str(tmp_path / "work")]
    assert rb.main(bad, runner=ManyTasks(), which=lambda name: name) == 2
    assert "--reviewer" in capsys.readouterr().err


def test_the_reviewer_must_differ_from_the_worker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--mode", "a", "--tasks", "01", "--reviewer", "ollama", "--dry-run",
            "--work-dir", str(tmp_path)]  # fmt: skip
    assert rb.main(argv) == 2  # the worker is ollama: it cannot review itself
    assert "reviewer" in capsys.readouterr().err


def test_the_difficulty_table_shows_only_the_difficulties_that_ran() -> None:
    records = [dataclasses.replace(_record("a", 1, "g1", True), difficulty="big")]
    table = rb.markdown(rb.summarize(records), records)
    assert "| Mode | big |\n|---|---|\n| A - Claude only | 1/1 |" in table


def test_claude_tokens_come_from_the_whole_session_not_the_last_loop() -> None:
    """13g: a session that waited for a background job ended in several loops; ``usage`` held
    only the last one, ``modelUsage`` (and the cost) the whole session."""
    data = {**CLAUDE_JSON, "usage": {"input_tokens": 20, "output_tokens": 5042,
                                     "cache_read_input_tokens": 659908,
                                     "cache_creation_input_tokens": 13462},
            "modelUsage": {
                "claude-opus-x": {"inputTokens": 80, "outputTokens": 20000,
                                  "cacheReadInputTokens": 2200000,
                                  "cacheCreationInputTokens": 60000},
                "claude-haiku-x": {"inputTokens": 4, "outputTokens": 2059,
                                   "cacheReadInputTokens": 56909,
                                   "cacheCreationInputTokens": 7413},
            }}  # fmt: skip
    parsed = rb.parse_claude(json.dumps(data))
    assert (parsed["input_tokens"], parsed["output_tokens"]) == (84, 22059)
    assert parsed["cache_read_input_tokens"] == 2256909
    assert parsed["cache_creation_input_tokens"] == 67413


def test_rescore_reads_the_saved_claude_output_again(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A results file measured with the old parser is fixed from the run folders (13g)."""
    assert _main(tmp_path, ManyTasks()) == 0
    [first] = (tmp_path / "out").glob("*.json")
    saved = tmp_path / "work" / "09-bugfix-inventory-a-1" / "claude-output.json"
    whole = {**CLAUDE_JSON, "modelUsage": {"m": {"inputTokens": 1200, "outputTokens": 9000,
                                                 "cacheReadInputTokens": 70000,
                                                 "cacheCreationInputTokens": 3000}}}  # fmt: skip
    saved.write_text(json.dumps(whole), encoding="utf-8")
    capsys.readouterr()
    assert rb.main(["--rescore", str(first), "--work-dir", str(tmp_path / "work")]) == 0
    assert "1 record(s) changed" in capsys.readouterr().out
    records = {(r["task"], r["mode"]): r for r in _saved(tmp_path)["records"]}
    assert records[("09-bugfix-inventory", "a")]["claude"]["output_tokens"] == 9000
    assert records[("01-docstring-geometry", "a")]["claude"]["output_tokens"] == 800
    assert records[("09-bugfix-inventory", "c")]["claude"] is None  # no Claude in mode C


# --- PR #44 review (D-117) ------------------------------------------------------------------


def test_rescore_leaves_a_record_whose_saved_output_is_another_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The folder name is reused by every call in the work dir: the cost must match."""
    assert _main(tmp_path, ManyTasks()) == 0
    [first] = (tmp_path / "out").glob("*.json")
    later = {**CLAUDE_JSON, "total_cost_usd": 0.9,
             "modelUsage": {"m": {"outputTokens": 99999}}}  # fmt: skip
    saved = tmp_path / "work" / "09-bugfix-inventory-a-1" / "claude-output.json"
    saved.write_text(json.dumps(later), encoding="utf-8")
    capsys.readouterr()
    assert rb.main(["--rescore", str(first), "--work-dir", str(tmp_path / "work")]) == 0
    out = capsys.readouterr().out
    assert "0 record(s) changed" in out and "1 left as they were" in out
    records = {(r["task"], r["mode"]): r for r in _saved(tmp_path)["records"]}
    assert records[("09-bugfix-inventory", "a")]["claude"]["output_tokens"] == 800


def test_rescore_counts_only_token_changes(tmp_path: Path) -> None:
    assert _main(tmp_path, ManyTasks()) == 0
    [first] = (tmp_path / "out").glob("*.json")
    data = json.loads(first.read_text(encoding="utf-8"))
    for record in data["records"]:  # a file from before permission_denials was recorded
        if record["claude"]:
            del record["claude"]["permission_denials"]
    first.write_text(json.dumps(data), encoding="utf-8")
    assert rb.rescore(first, tmp_path / "work") == 0


def test_the_providers_of_worker_runs_are_recorded(tmp_path: Path) -> None:
    from orkestra.state import db

    since = datetime.now().astimezone()
    with closing(db.connect(tmp_path / "state.db")) as conn:
        for run_id, provider in (("r1", "agy"), ("r2", "ollama"), ("r3", "agy")):
            conn.execute(
                "INSERT INTO runs (run_id, task_id, kind, status, provider, model, tier, "
                "attempts, started_at) VALUES (?, 't', 'edit', 'ok', ?, 'm', 1, 1, ?)",
                (run_id, provider, db.local_now().isoformat()),
            )
        conn.commit()
    assert rb.worker_stats(tmp_path, since)["by_provider"] == {"agy": 2, "ollama": 1}


def test_a_run_the_reviewer_wrote_is_marked_and_reported() -> None:
    workers = {"runs": 3, "by_provider": {"agy": 2, "ollama": 1}}
    record = dataclasses.replace(_record("g", 1, "t1", True), workers=workers)
    assert "reviewer ollama wrote 1 run" in rb.run_mark(record, "ollama")
    table = rb.markdown(rb.summarize([record]), [record], reviewer="ollama")
    assert "Worker runs written by the reviewer (ollama): G 1" in table


def test_a_g_run_without_delegation_is_a_choice_not_a_broken_worker() -> None:
    idle = dataclasses.replace(_record("g", 1, "t1", True), workers={"runs": 0})
    assert rb.run_mark(idle, None) == "PASS - did not delegate"
    broken = dataclasses.replace(_record("d", 1, "t1", False), mode="d", workers={"runs": 0})
    assert rb.run_mark(broken, None) == "fail - no worker run"


def test_ollama_model_2_is_refused_when_only_the_reviewer_is_ollama(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--mode", "a", "--tasks", "01", "--worker", "agy", "--reviewer", "ollama",
            "--ollama-model-2", "big", "--work-dir", str(tmp_path)]  # fmt: skip
    assert rb.main(argv, runner=ManyTasks(), which=lambda name: name) == 2
    assert "--ollama-model-2" in capsys.readouterr().err


def test_a_missing_agy_names_the_reviewer_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--mode", "a", "--tasks", "01", "--reviewer", "agy", "--work-dir", str(tmp_path)]
    which = lambda name: None if name == "agy" else name  # noqa: E731
    assert rb.main(argv, runner=ManyTasks(), which=which) == 2
    assert "--reviewer agy" in capsys.readouterr().err
