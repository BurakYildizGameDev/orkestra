"""Benchmark: does handing work to cheap workers pay off? (Faz 13, YAPILIS_PLANI)

Three modes run the same tasks, each in a fresh git workspace with the task's project:

- **A - Claude only:** ``claude -p`` with no skills and no MCP servers.
- **B - Claude + Orkestra skill:** the same, with the Orkestra skill in the workspace and an
  Orkestra home of its own (the bench config, cheap local workers, cache off).
- **C - Orkestra only:** ``orkestra run --profile cheap`` with no chief; a passing run is
  applied. The lower bound without a chief.

After a run the task's **hidden tests** decide pass/fail. They (and the reference solution)
never enter a workspace, a prompt or an Orkestra task before the run ends: ``check_no_leak``
and ``check_orkestra_task`` stop the run otherwise. They are only copied into a separate
evaluation folder afterwards.

Usage::

    uv run python bench/run_bench.py --mode all --repeat 3
    uv run python bench/run_bench.py --mode c --tasks 01,09 --repeat 1
    uv run python bench/run_bench.py --dry-run          # checks every task, starts nothing

Results: ``bench/results/<date>.json`` (every run) and ``<date>.md`` (the tables). This is a
developer tool: its output is English only and it is not part of the ``orkestra`` package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from ruamel.yaml import YAML

from orkestra.errors import OrkestraError

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parent
TASKS_DIR = BENCH_DIR / "tasks"
RESULTS_DIR = BENCH_DIR / "results"
SKILL_FILE = REPO_ROOT / "skill" / "orkestra" / "SKILL.md"

MODES: dict[str, str] = {
    "a": "A - Claude only",
    "b": "B - Claude + Orkestra skill",
    "c": "C - Orkestra only (cheap)",
}
DIFFICULTIES = ("easy", "medium", "hard")
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:14b"
DEFAULT_TIMEOUT_S = 900
EVAL_TIMEOUT_S = 300
LEAK_LINE_CHARS = 30  # a hidden-test line this long quoted in a prompt is a leak
CLAUDE_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep", "Bash(python:*)", "Bash(pytest:*)",
                "Bash(git:*)")  # fmt: skip
ORKESTRA_TOOLS = ("Bash(orkestra:*)",)
SKILL_HINT = (
    "The Orkestra skill is available in this project. When a part of this task suits a cheap "
    "worker (bulky, easy to check), delegate it with orkestra as the skill describes, review "
    "the result and apply it; do the rest yourself."
)
GIT_ENV = {
    "GIT_AUTHOR_NAME": "bench", "GIT_AUTHOR_EMAIL": "bench@example.invalid",
    "GIT_COMMITTER_NAME": "bench", "GIT_COMMITTER_EMAIL": "bench@example.invalid",
}  # fmt: skip


class BenchError(OrkestraError):
    """A run could not be carried out (bad output, missing program)."""


class LeakError(BenchError):
    """A hidden test or the solution would reach the worker: the run must not start."""


class UsageLimitReached(BenchError):
    """Claude's usage limit (or an overload) stopped a run: it is not a model failure, so the
    benchmark stops and is resumed later (``--resume``)."""


# Searched in the result *text* and stderr only (never the serialized usage numbers), and
# only when the run failed, or when a short result is nothing but the limit message: a good
# answer may mention a rate limit, and "context limit reached" is a model failure.
LIMIT_PATTERN = re.compile(
    r"usage limit|(?:5-hour|weekly|daily|session) limit|limit reached.{0,40}reset"
    r"|rate[ _-]?limit[ _-]?error|too many requests|overloaded|API Error: (?:429|529)",
    re.IGNORECASE,
)
SHORT_RESULT_CHARS = 300  # a limit notice delivered as a normal result is short


# --- tasks ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    id: str
    difficulty: str
    category: str
    prompt: str
    files: tuple[str, ...]
    root: Path
    check: str | None = None
    allow_new_files: bool = False


def load_tasks(folder: Path = TASKS_DIR, only: Sequence[str] = ()) -> list[Task]:
    yaml = YAML(typ="safe")
    tasks: list[Task] = []
    for meta in sorted(folder.glob("*/task.yaml")):
        data = yaml.load(meta.read_text(encoding="utf-8"))
        task = Task(
            id=str(data["id"]), difficulty=str(data["difficulty"]),
            category=str(data["category"]), prompt=str(data["prompt"]),
            files=tuple(str(f) for f in data["files"]), root=meta.parent,
            check=data.get("check"), allow_new_files=bool(data.get("allow_new_files", False)),
        )  # fmt: skip
        if task.id != meta.parent.name:
            raise BenchError(f"{meta}: id {task.id} does not match the folder name")
        if task.difficulty not in DIFFICULTIES:
            raise BenchError(f"{meta}: unknown difficulty {task.difficulty}")
        if not only or any(task.id.startswith(prefix) for prefix in only):
            tasks.append(task)
    return tasks


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, **GIT_ENV})  # fmt: skip


def prepare_workspace(task: Task, dest: Path, extra: Mapping[str, Path] | None = None) -> Path:
    """A fresh git repository with the task's project (and ``extra`` files) committed."""
    if dest.exists():
        _rmtree(dest)
    shutil.copytree(task.root / "project", dest)
    for relative, source in (extra or {}).items():
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "config", "core.autocrlf", "false")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "start")
    return dest


def _force_remove(func: Callable[..., Any], path: str, _exc: Any) -> None:
    os.chmod(path, 0o700)  # git objects are read-only on Windows
    func(path)


def _rmtree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_force_remove)
    else:
        shutil.rmtree(path, onerror=_force_remove)


def _python(command: str) -> list[str]:
    parts = shlex.split(command)
    return [sys.executable, *parts[1:]] if parts and parts[0] == "python" else parts


def run_check(task: Task, workspace: Path) -> tuple[int, str]:
    """The task's visible check (``check:``), as the worker would run it."""
    if not task.check:
        return 0, ""
    try:
        done = subprocess.run(
            _python(task.check), cwd=workspace, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=EVAL_TIMEOUT_S,
        )  # fmt: skip
    except subprocess.TimeoutExpired:  # a hanging worker result must not stop the benchmark
        return 124, f"visible check timed out after {EVAL_TIMEOUT_S} s"
    return done.returncode, done.stdout + done.stderr


@dataclass(frozen=True)
class Evaluation:
    passed: bool
    output: str


def evaluate(task: Task, workspace: Path, eval_dir: Path) -> Evaluation:
    """Copy the result, add the hidden tests next to it, run them. The workspace itself is
    never touched, so nothing hidden is ever inside it."""
    if eval_dir.exists():
        _rmtree(eval_dir)
    shutil.copytree(workspace, eval_dir, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    hidden = eval_dir / "_hidden_tests"
    shutil.copytree(task.root / "hidden", hidden)
    (eval_dir / "_bench_pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "-c", "_bench_pytest.ini", "--rootdir", ".", "_hidden_tests"]  # fmt: skip
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        done = subprocess.run(
            args, cwd=eval_dir, capture_output=True, text=True, env=env,
            encoding="utf-8", errors="replace", timeout=EVAL_TIMEOUT_S,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return Evaluation(False, "hidden tests timed out")
    return Evaluation(done.returncode == 0, (done.stdout + done.stderr)[-4000:])


# --- the leak guard -----------------------------------------------------------------------------


def _digest(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _secrets(task: Task) -> tuple[set[str], set[str], list[str]]:
    """Names of hidden tests, digests of hidden tests and solution files (the ones that differ
    from the project), and the long lines of the hidden tests."""
    names: set[str] = set()
    digests: set[str] = set()
    lines: list[str] = []
    for path in (task.root / "hidden").rglob("*"):
        if path.is_file():
            names.add(path.name)
            digests.add(_digest(path.read_bytes()))
            text = path.read_text(encoding="utf-8", errors="replace")
            lines += [ln.strip() for ln in text.splitlines() if len(ln.strip()) > LEAK_LINE_CHARS]
    for path in (task.root / "solution").rglob("*"):
        if not path.is_file():
            continue
        original = task.root / "project" / path.relative_to(task.root / "solution")
        if not original.is_file() or _digest(original.read_bytes()) != _digest(path.read_bytes()):
            digests.add(_digest(path.read_bytes()))
    return names, digests, lines


def check_no_leak(task: Task, workspace: Path, *, prompt: str) -> None:
    names, digests, lines = _secrets(task)
    for path in workspace.rglob("*"):
        if ".git" in path.relative_to(workspace).parts or not path.is_file():
            continue
        if path.name in names or _digest(path.read_bytes()) in digests:
            raise LeakError(
                f"{task.id}: {path.relative_to(workspace)} is a hidden test or the solution"
            )
    for line in lines:
        if line in prompt:
            raise LeakError(f"{task.id}: the prompt quotes a hidden test")


def orkestra_task(task: Task) -> dict[str, Any]:
    """Mode C's Orkestra task: the same prompt and files; the visible check as the verifier."""
    document: dict[str, Any] = {
        "id": task.id.replace("_", "-"), "kind": "edit", "tier": 1, "prompt": task.prompt,
        "context": {"files": list(task.files), "globs": []},
        "allow_new_files": task.allow_new_files, "tags": ["bench", task.category],
    }  # fmt: skip
    if task.check:
        document["verify"] = [{"type": "command", "run": task.check}]
    return document


def check_orkestra_task(task: Task, workspace: Path, document: Mapping[str, Any]) -> None:
    """Every context path stays inside the workspace (where nothing hidden is)."""
    check_no_leak(task, workspace, prompt=str(document.get("prompt", "")))
    context = document.get("context", {})
    root = workspace.resolve()
    for name in context.get("files", []):
        target = (workspace / name).resolve()
        if not target.is_relative_to(root):
            raise LeakError(f"{task.id}: context file {name} is outside the workspace")
    for pattern in context.get("globs", []):
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise LeakError(f"{task.id}: context glob {pattern} may leave the workspace")


# --- running ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Completed:
    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    def __call__(
        self, args: Sequence[str], cwd: Path, env: dict[str, str], timeout: float,
        input_text: str | None = None,
    ) -> Completed: ...  # fmt: skip


def subprocess_runner(
    args: Sequence[str], cwd: Path, env: dict[str, str], timeout: float,
    input_text: str | None = None,
) -> Completed:  # fmt: skip
    try:
        done = subprocess.run(list(args), cwd=cwd, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              input=input_text)  # fmt: skip
    except subprocess.TimeoutExpired:
        return Completed(124, "", f"timed out after {timeout:.0f} s")
    return Completed(done.returncode, done.stdout, done.stderr)


@dataclass(frozen=True)
class Settings:
    out_dir: Path
    work_dir: Path
    claude: str
    orkestra: list[str]
    ollama_model: str
    claude_model: str | None
    timeout_s: float
    ollama_model_2: str | None = None


@dataclass
class Record:
    task: str
    difficulty: str
    mode: str
    repeat: int
    passed: bool
    duration_s: float
    claude: dict[str, Any] | None
    workers: dict[str, Any]
    error: str | None = None
    check_passed: bool | None = None
    output_tail: str = field(default="", repr=False)


def claude_args(mode: str, settings: Settings, settings_file: Path) -> list[str]:
    """No argument holds the prompt, a newline or a quote: on Windows ``claude`` is an npm
    ``claude.CMD`` and cmd.exe would cut or mangle them. The prompt goes in on stdin, the tool
    permissions in a settings file."""
    args = [settings.claude, "-p", "--output-format", "json",
            "--permission-mode", "acceptEdits", "--setting-sources", "project",
            "--strict-mcp-config", "--no-session-persistence",
            "--settings", str(settings_file)]  # fmt: skip
    if settings.claude_model:
        args += ["--model", settings.claude_model]
    if mode == "a":
        args.append("--disable-slash-commands")
    return args


def claude_prompt(mode: str, prompt: str) -> str:
    return f"{SKILL_HINT}\n\n{prompt}" if mode == "b" else prompt


def claude_settings(mode: str, path: Path) -> Path:
    tools = [*CLAUDE_TOOLS, *(ORKESTRA_TOOLS if mode == "b" else ())]
    path.write_text(json.dumps({"permissions": {"allow": tools}}, indent=2), encoding="utf-8")
    return path


def result_event(stdout: str) -> dict[str, Any] | None:
    """The result object of ``claude -p --output-format json`` (also from a list of events);
    None when the output is not JSON."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return None
    if isinstance(data, list):  # a stream of events: the last one is the result
        data = next(
            (d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), {}
        )
    return data if isinstance(data, dict) else {}


def parse_claude(stdout: str) -> dict[str, Any]:
    data = result_event(stdout)
    if data is None:
        raise BenchError(f"claude output is not JSON: {stdout[:200]!r}")
    usage = data.get("usage") or {}
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
        "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
        "cost_usd": float(data.get("total_cost_usd") or 0.0),
        "turns": int(data.get("num_turns") or 0),
    }


def worker_stats(home: Path, since: datetime) -> dict[str, Any]:
    """What the workers did in ``home`` since ``since`` (Orkestra's own records)."""
    empty = {"runs": 0, "ok": 0, "cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0,
             "savings_tokens": 0}  # fmt: skip
    path = home / "state.db"
    if not path.is_file():
        return empty
    from orkestra.state import db, stats

    with closing(db.connect(path)) as conn:
        report = stats.collect(conn, since=since, now=db.local_now())
    totals, saved = report.totals, report.savings
    return {
        "runs": totals.runs, "ok": totals.ok, "cost_usd": round(totals.cost_usd, 6),
        "prompt_tokens": totals.prompt_tokens, "completion_tokens": totals.completion_tokens,
        "savings_tokens": max(saved.worker_output_tokens - saved.envelope_tokens, 0),
    }  # fmt: skip


def _env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("ORKESTRA_CONFIG", "ORKESTRA_CHIEF")}
    return {**env, "ORKESTRA_HOME": str(home), "ORKESTRA_LANG": "en", "PYTHONUTF8": "1"}


def run_once(
    task: Task, mode: str, repeat: int, settings: Settings, *, runner: Runner, home: Path
) -> Record:
    run_dir = settings.work_dir / f"{task.id}-{mode}-{repeat}"
    extra = {".claude/skills/orkestra/SKILL.md": SKILL_FILE} if mode == "b" else None
    workspace = prepare_workspace(task, run_dir / "ws", extra)
    check_no_leak(task, workspace, prompt=task.prompt)
    env = _env(home)
    started_at = datetime.now().astimezone()
    started = time.monotonic()
    claude: dict[str, Any] | None = None
    error: str | None = None
    try:
        if mode in ("a", "b"):
            claude, error = _run_claude(task, mode, workspace, run_dir, settings, runner, env)
        else:
            error = _run_orkestra(task, workspace, run_dir, settings, runner, env)
    except (LeakError, UsageLimitReached):
        raise  # never a model failure: the whole benchmark stops
    except BenchError as exc:
        error = str(exc)
    duration = round(time.monotonic() - started, 2)
    result = evaluate(task, workspace, run_dir / "eval")
    check_code, _ = run_check(task, workspace) if task.check else (0, "")
    return Record(
        task=task.id, difficulty=task.difficulty, mode=mode, repeat=repeat,
        passed=result.passed, duration_s=duration, claude=claude,
        workers=worker_stats(home, started_at), error=error,
        check_passed=(check_code == 0) if task.check else None, output_tail=result.output[-1500:],
    )  # fmt: skip


def _run_claude(
    task: Task, mode: str, workspace: Path, run_dir: Path, settings: Settings, runner: Runner,
    env: dict[str, str],
) -> tuple[dict[str, Any] | None, str | None]:  # fmt: skip
    """Claude's usage and an error; a failed run keeps its exit code and stderr, and its
    usage only when Claude still printed it (a timeout has none: it is not counted as 0)."""
    settings_file = claude_settings(mode, run_dir / "claude-settings.json")
    done = runner(claude_args(mode, settings, settings_file), workspace, env,
                  settings.timeout_s, input_text=claude_prompt(mode, task.prompt))  # fmt: skip
    if _limit_reached(done):
        raise UsageLimitReached(f"{task.id} {mode}: {_limit_text(done)[:200]}")
    if done.returncode != 0:
        error = f"claude exited with {done.returncode}: {done.stderr[-300:]}"
        try:
            return parse_claude(done.stdout), error
        except BenchError:
            return None, error
    return parse_claude(done.stdout), None


def _limit_text(done: Completed) -> str:
    event = result_event(done.stdout)
    result = str(event.get("result") or "") if event else done.stdout
    return f"{result}\n{done.stderr}".strip()


def _limit_reached(done: Completed) -> bool:
    event = result_event(done.stdout) or {}
    failed = done.returncode != 0 or bool(event.get("is_error"))
    text = _limit_text(done)
    if not LIMIT_PATTERN.search(text):
        return False
    return failed or len(str(event.get("result") or "")) <= SHORT_RESULT_CHARS


def _run_orkestra(
    task: Task, workspace: Path, run_dir: Path, settings: Settings, runner: Runner,
    env: dict[str, str],
) -> str | None:  # fmt: skip
    document = orkestra_task(task)
    check_orkestra_task(task, workspace, document)
    task_file = run_dir / "orkestra-task.json"  # outside the workspace: not part of the change
    task_file.write_text(json.dumps(document, indent=2), encoding="utf-8")
    run = [*settings.orkestra, "run", str(task_file), "--profile", "cheap", "--json"]
    done = runner(run, workspace, env, settings.timeout_s)
    try:
        envelope = json.loads(done.stdout)
    except ValueError as exc:
        raise BenchError(f"orkestra output is not JSON (exit {done.returncode}): "
                         f"{done.stderr[-300:]}") from exc  # fmt: skip
    if envelope.get("status") != "ok":
        return f"orkestra run ended {envelope.get('status')} (exit {done.returncode})"
    applied = runner([*settings.orkestra, "apply", str(envelope["run_id"]), "--json"],
                     workspace, env, settings.timeout_s)  # fmt: skip
    if applied.returncode != 0:
        return f"orkestra apply failed (exit {applied.returncode}): {applied.stderr[-300:]}"
    return None


# --- the bench Orkestra home --------------------------------------------------------------------


def setup_home(home: Path, settings: Settings) -> None:
    """Orkestra's config and consent for the bench: local Ollama only, the cache off (the same
    task runs several times), adaptive routing off (every repeat routes the same way)."""
    from orkestra.config import loader
    from orkestra.state import consent, db

    home.mkdir(parents=True, exist_ok=True)
    models = [{"id": settings.ollama_model, "tier": 1}]
    if settings.ollama_model_2:
        models.append({"id": settings.ollama_model_2, "tier": 2})
    document = {
        "version": 1, "language": "en", "cache": {"enabled": False},
        "routing": {"adaptive": False}, "notify": {"desktop": False},
        "providers": {"ollama": {"type": "ollama", "models": models}},
    }  # fmt: skip
    (home / "config.yaml").write_text(loader.dump_yaml(document), encoding="utf-8")

    config = loader.load_config(home / "config.yaml", cwd=home, environ={}).config
    with closing(db.connect(home / "state.db")) as conn:
        consent.grant(conn, "ollama", config.providers["ollama"], db.local_now())


# --- results ----------------------------------------------------------------------------------


def _with_usage(records: Iterable[Record]) -> list[Record]:
    """Runs that reported Claude usage; a timeout or crash has none and is not a zero."""
    return [r for r in records if r.claude is not None]


def _claude_tokens(record: Record) -> int:
    c = record.claude or {}
    return int(c.get("input_tokens", 0) + c.get("output_tokens", 0)
               + c.get("cache_creation_input_tokens", 0))  # fmt: skip


def _mean(values: Iterable[float]) -> float:
    found = list(values)
    return round(statistics.fmean(found), 3) if found else 0.0


def summarize(records: Sequence[Record]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for mode in MODES:
        mine = [r for r in records if r.mode == mode]
        if not mine:
            continue
        tasks = sorted({r.task for r in mine})
        every = sorted({r.repeat for r in mine})
        # A repeat a stop cut short would look like a low score: only complete ones count.
        complete = [n for n in every if len({r.task for r in mine if r.repeat == n}) == len(tasks)]
        repeats = complete or every
        per_repeat = [sum(r.passed for r in mine if r.repeat == n) for n in repeats]
        summary[mode] = {
            "label": MODES[mode], "tasks": len(tasks), "repeats": len(repeats),
            "complete_repeats": len(complete),
            "partial_runs": sum(1 for r in mine if r.repeat not in complete),
            "passed": {"mean": _mean(per_repeat), "min": min(per_repeat), "max": max(per_repeat)},
            "by_difficulty": {
                d: {"tasks": len({r.task for r in mine if r.difficulty == d}),
                    "passed_mean": _mean(sum(r.passed for r in mine
                                             if r.difficulty == d and r.repeat == n)
                                         for n in repeats)}
                for d in DIFFICULTIES if any(r.difficulty == d for r in mine)
            },
            "claude_tokens_per_task": (_mean(_claude_tokens(r) for r in _with_usage(mine))
                                       if mode != "c" else None),
            "claude_cache_read_per_task": (
                _mean((r.claude or {}).get("cache_read_input_tokens", 0) for r in _with_usage(mine))
                if mode != "c" else None),
            "claude_cost_per_task": _mean((r.claude or {}).get("cost_usd", 0.0)
                                          for r in _with_usage(mine)) if mode != "c" else None,
            "runs_without_usage": (sum(1 for r in mine if r.claude is None)
                                   if mode != "c" else None),
            "worker_cost_per_task": _mean(r.workers.get("cost_usd", 0.0) for r in mine),
            "worker_runs_per_task": _mean(r.workers.get("runs", 0) for r in mine),
            "savings_estimate_per_task": _mean(r.workers.get("savings_tokens", 0) for r in mine),
            "duration_per_task_s": _mean(r.duration_s for r in mine),
            "errors": sum(1 for r in mine if r.error),
        }  # fmt: skip
    return summary


def _num(value: float | None, pattern: str = "{:,.0f}") -> str:
    return "-" if value is None else pattern.format(value)


def markdown(summary: Mapping[str, Mapping[str, Any]], records: Sequence[Record]) -> str:
    lines = [
        "| Mode | Passed (mean, min-max) | Claude tokens / task | Claude cost / task "
        "| Worker cost / task | Worker runs / task | Time / task |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in summary.values():
        passed = s["passed"]
        partial = f", partial: {s['partial_runs']} runs not scored" if s["partial_runs"] else ""
        lines.append(
            f"| {s['label']} | {passed['mean']:g}/{s['tasks']} ({passed['min']}-{passed['max']}"
            f"{partial}) "
            f"| {_num(s['claude_tokens_per_task'])} | {_num(s['claude_cost_per_task'], '${:.4f}')} "
            f"| {_num(s['worker_cost_per_task'], '${:.4f}')} "
            f"| {_num(s['worker_runs_per_task'], '{:.1f}')} "
            f"| {_num(s['duration_per_task_s'], '{:.0f} s')} |"
        )  # fmt: skip
    lines += ["", "| Mode | " + " | ".join(DIFFICULTIES) + " |", "|---|---|---|---|"]
    for s in summary.values():
        cells = [f"{s['by_difficulty'][d]['passed_mean']:g}/{s['by_difficulty'][d]['tasks']}"
                 if d in s["by_difficulty"] else "-" for d in DIFFICULTIES]  # fmt: skip
        lines.append(f"| {s['label']} | " + " | ".join(cells) + " |")
    if "a" in summary and "b" in summary:
        saved = summary["a"]["claude_tokens_per_task"] - summary["b"]["claude_tokens_per_task"]
        lines += ["", f"Claude tokens saved per task (A - B): {saved:,.0f}",
                  f"Orkestra's own estimate in B (`stats` savings) per task: "
                  f"{summary['b']['savings_estimate_per_task']:,.0f}"]  # fmt: skip
    errors = [r for r in records if r.error]
    if errors:
        lines += ["", f"Runs with an error: {len(errors)} (see the JSON file)."]
    return "\n".join(lines) + "\n"


def write_results(
    records: Sequence[Record], out_dir: Path, *, stamp: str, meta: Mapping[str, Any]
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(records)
    document = json.dumps({"meta": dict(meta), "summary": summary,
                           "records": [asdict(r) for r in records]}, indent=2)  # fmt: skip
    json_path = _write_atomic(out_dir / f"{stamp}.json", document)
    header = f"# Benchmark {stamp}\n\n" + "".join(_meta_lines(meta)) + "\n"
    md_path = _write_atomic(out_dir / f"{stamp}.md", header + markdown(summary, records))
    return json_path, md_path


def _write_atomic(path: Path, text: str) -> Path:
    """Every window's results live in one file: a cut write must not lose them."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return path


def _meta_lines(meta: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, value in meta.items():
        if key == "task_ids":
            lines.append(f"- tasks: {', '.join(value)}\n")
        elif key == "windows":
            lines += [f"- window {w.get('date', '-')}: claude {w.get('claude', '-')}, "
                      f"orkestra {w.get('orkestra', '-')}, {w.get('runs', 0)} runs\n"
                      for w in value]  # fmt: skip
        elif key == "tasks":
            continue  # the ids above say it
        elif value is None:
            lines.append(f"- {key}: {'default' if key == 'claude_model' else '-'}\n")
        else:
            lines.append(f"- {key}: {value}\n")
    return lines


# --- command line -----------------------------------------------------------------------------


def _version(args: Sequence[str], runner: Runner) -> str:
    try:
        done = runner(list(args), Path.cwd(), dict(os.environ), 60)
    except OSError:
        return "unknown"
    text = done.stdout.strip()
    return text.splitlines()[0] if done.returncode == 0 and text else "unknown"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Orkestra benchmark (Faz 13).")
    parser.add_argument("--mode", choices=[*MODES, "all"], default=None, help="default all")
    parser.add_argument("--repeat", type=int, default=None, help="default 3")
    parser.add_argument("--tasks", default="", help="comma-separated id prefixes (default: all)")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    parser.add_argument(
        "--work-dir", type=Path, default=Path(tempfile.gettempdir()) / "orkestra-bench"
    )
    parser.add_argument("--ollama-model", default=None, help=f"default {DEFAULT_OLLAMA_MODEL}")
    parser.add_argument("--ollama-model-2", default=None,
                        help="an optional tier-2 Ollama model; only mode B can use it "
                             "(when Claude asks for tier 2): mode C runs the cheap "
                             "profile, tier 1")  # fmt: skip
    parser.add_argument("--claude-model", default=None)
    parser.add_argument("--timeout", type=float, default=None,
                        help=f"per run, default {DEFAULT_TIMEOUT_S} s")  # fmt: skip
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="a results JSON file: skip its finished runs, append to it",
    )
    parser.add_argument("--max-claude-runs", type=int, default=None,
                        help="start at most this many Claude sessions in this call")  # fmt: skip
    parser.add_argument("--dry-run", action="store_true",
                        help="check every task and the leak guard; start nothing")  # fmt: skip
    return parser


@dataclass
class Plan:
    """What to run: from the command line, or from the results file being resumed."""

    modes: list[str]
    tasks: list[Task]
    repeat: int
    out: Path
    stamp: str
    meta: dict[str, Any]
    records: list[Record]


def _plan(opts: argparse.Namespace) -> Plan:
    if opts.resume is None:
        modes = list(MODES) if opts.mode in (None, "all") else [opts.mode]
        tasks = load_tasks(TASKS_DIR, [p for p in opts.tasks.split(",") if p])
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        return Plan(modes, tasks, opts.repeat or 3, opts.out, stamp, {}, [])
    try:
        data = json.loads(opts.resume.read_text(encoding="utf-8"))
        meta = dict(data["meta"])
        ids = list(meta["task_ids"])
        stored_records = list(data["records"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BenchError(f"cannot resume from {opts.resume}: not a results file of this "
                         f"version ({type(exc).__name__}: {exc})") from exc  # fmt: skip
    prefixes = [p for p in opts.tasks.split(",") if p]
    if prefixes and [t.id for t in load_tasks(TASKS_DIR, prefixes)] != ids:
        raise BenchError(f"--tasks differs from the resumed run ({', '.join(ids)})")
    for flag, key, value in (("--ollama-model", "ollama_model", opts.ollama_model),
                             ("--ollama-model-2", "ollama_model_2", opts.ollama_model_2),
                             ("--claude-model", "claude_model", opts.claude_model),
                             ("--timeout", "timeout_s", opts.timeout)):  # fmt: skip
        if value is not None and value != meta.get(key):
            raise BenchError(f"{flag} differs from the resumed run ({meta.get(key)})")
    if opts.mode not in (None, "all" if meta["modes"] == "".join(MODES) else meta["modes"]):
        raise BenchError(f"--mode differs from the resumed run ({meta['modes']})")
    tasks = [t for t in load_tasks(TASKS_DIR) if t.id in ids]
    records = [Record(**r) for r in stored_records]
    repeat = max(opts.repeat or 0, int(meta["repeat"]))
    return Plan(list(meta["modes"]), tasks, repeat, opts.resume.parent, opts.resume.stem, meta,
                records)  # fmt: skip


def _stop(records: Sequence[Record], plan: Plan, reason: str) -> Path:
    json_path, _ = write_results(records, plan.out, stamp=plan.stamp, meta=plan.meta)
    print(f"{reason}\nresume with: uv run python bench/run_bench.py --resume {json_path}")
    return json_path


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = subprocess_runner,
    which: Callable[[str], str | None] = shutil.which,
) -> int:
    opts = _parser().parse_args(argv)
    try:
        plan = _plan(opts)
    except BenchError as exc:
        print(exc, file=sys.stderr)
        return 2
    done = {(r.task, r.mode, r.repeat) for r in plan.records}
    total = len(plan.tasks) * len(plan.modes) * plan.repeat
    print(f"{len(plan.tasks)} tasks x {len(plan.modes)} modes x {plan.repeat} repeats = "
          f"{total} runs ({total - len(done)} to go)")  # fmt: skip
    if opts.dry_run:
        for task in plan.tasks:
            workspace = prepare_workspace(task, opts.work_dir / "dry-run" / task.id)
            check_no_leak(task, workspace, prompt=task.prompt)
            check_orkestra_task(task, workspace, orkestra_task(task))
        print("dry run: every task is ready, nothing leaks; nothing was started")
        return 0
    uses_claude = any(m in ("a", "b") for m in plan.modes)
    claude = which("claude")
    if uses_claude and claude is None:
        print("claude is not on PATH (needed for modes a and b)", file=sys.stderr)
        return 2
    meta = plan.meta
    settings = Settings(
        out_dir=plan.out, work_dir=opts.work_dir, claude=claude or "claude",
        orkestra=[sys.executable, "-m", "orkestra"],
        ollama_model=meta.get("ollama_model", opts.ollama_model or DEFAULT_OLLAMA_MODEL),
        ollama_model_2=meta.get("ollama_model_2", opts.ollama_model_2),
        claude_model=meta.get("claude_model", opts.claude_model),
        timeout_s=meta.get("timeout_s", opts.timeout or DEFAULT_TIMEOUT_S),
    )  # fmt: skip
    home = opts.work_dir / f"home-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}"
    setup_home(home, settings)
    window = {
        "date": datetime.now().astimezone().isoformat(timespec="minutes"),
        "claude": _version([settings.claude, "--version"], runner) if uses_claude else "-",
        "orkestra": _version([*settings.orkestra, "--version"], runner), "runs": 0,
    }  # fmt: skip
    if not meta:
        meta.update({
            "date": window["date"],
            "machine": f"{platform.system()} {platform.release()}, "
                       f"{platform.processor() or platform.machine()}",
            "python": platform.python_version(),
            "modes": "".join(plan.modes), "task_ids": [t.id for t in plan.tasks],
            "tasks": len(plan.tasks), "ollama_model": settings.ollama_model,
            "ollama_model_2": settings.ollama_model_2, "claude_model": settings.claude_model,
            "timeout_s": settings.timeout_s, "windows": [],
        })  # fmt: skip
    windows = meta.setdefault("windows", [])
    versions = (window["claude"], window["orkestra"])
    if windows and (windows[-1]["claude"], windows[-1]["orkestra"]) != versions:
        print(f"note: versions changed since the last window: claude {window['claude']}, "
              f"orkestra {window['orkestra']} (recorded per window)", file=sys.stderr)  # fmt: skip
    windows.append(window)
    meta["repeat"] = plan.repeat
    records = list(plan.records)
    claude_runs = 0
    for repeat in range(1, plan.repeat + 1):
        for task in plan.tasks:
            for mode in plan.modes:
                if (task.id, mode, repeat) in done:
                    continue
                is_claude = mode in ("a", "b")
                if (
                    is_claude
                    and opts.max_claude_runs is not None
                    and claude_runs >= opts.max_claude_runs
                ):
                    _stop(
                        records,
                        plan,
                        f"stopped after {claude_runs} Claude sessions (--max-claude-runs)",
                    )
                    return 0
                try:
                    record = run_once(task, mode, repeat, settings, runner=runner, home=home)
                except LeakError as exc:
                    print(f"STOPPED, the leak guard tripped: {exc}", file=sys.stderr)
                    return 3
                except UsageLimitReached as exc:
                    print(f"STOPPED, Claude's usage limit: {exc}", file=sys.stderr)
                    _stop(records, plan, "this run is not recorded; wait for the limit to reset")
                    return 4
                claude_runs += is_claude
                window["runs"] += 1
                records.append(record)
                mark = "PASS" if record.passed else "fail"
                print(f"[{len(records)}/{total}] {task.id} {mode} #{repeat}: {mark} "
                      f"({record.duration_s:.0f} s){' - ' + record.error if record.error else ''}",
                      flush=True)  # fmt: skip
                write_results(records, plan.out, stamp=plan.stamp, meta=meta)  # survives a crash
    json_path, md_path = write_results(records, plan.out, stamp=plan.stamp, meta=meta)
    print(f"results: {json_path}\n         {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
