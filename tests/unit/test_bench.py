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
                             "cost_usd": 0.0421, "turns": 4, "permission_denials": 0}  # fmt: skip


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
        return next(t for t in TASKS if cwd.parent.name.startswith(t.id + "-"))

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


def test_max_claude_runs_stops_before_the_next_claude_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = ManyTasks()
    code = _main(tmp_path, runner, "--max-claude-runs", "3")
    out = capsys.readouterr().out
    assert code == 0 and runner.claude_runs == 3
    modes = [(r["task"][:2], r["mode"]) for r in _saved(tmp_path)["records"]]
    assert modes == [("01", "a"), ("01", "b"), ("01", "c"), ("09", "a")]
    assert "--resume" in out


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


def test_the_evaluation_turns_the_asyncio_plugin_off(tmp_path: Path) -> None:
    task = _task("01-docstring-geometry")
    solved = rb.prepare_workspace(task, tmp_path / "ws")
    shutil.copytree(task.root / "solution", solved, dirs_exist_ok=True)
    result = rb.evaluate(task, solved, tmp_path / "eval")
    assert result.passed and "PytestDeprecationWarning" not in result.output
