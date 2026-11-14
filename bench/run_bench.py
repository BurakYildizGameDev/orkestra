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
from typing import Any

from ruamel.yaml import YAML

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


class BenchError(Exception):
    """A run could not be carried out (bad output, missing program)."""


class LeakError(BenchError):
    """A hidden test or the solution would reach the worker: the run must not start."""


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
    done = subprocess.run(_python(task.check), cwd=workspace, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=EVAL_TIMEOUT_S)  # fmt: skip
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


Runner = Callable[[Sequence[str], Path, dict[str, str], float], Completed]


def subprocess_runner(
    args: Sequence[str], cwd: Path, env: dict[str, str], timeout: float
) -> Completed:
    try:
        done = subprocess.run(list(args), cwd=cwd, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)  # fmt: skip
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


def claude_args(mode: str, prompt: str, settings: Settings) -> list[str]:
    args = [settings.claude, "-p", prompt, "--output-format", "json",
            "--permission-mode", "acceptEdits", "--setting-sources", "project",
            "--strict-mcp-config", "--no-session-persistence"]  # fmt: skip
    if settings.claude_model:
        args += ["--model", settings.claude_model]
    if mode == "a":
        args.append("--disable-slash-commands")
    else:
        args += ["--append-system-prompt", SKILL_HINT]
    tools = [*CLAUDE_TOOLS, *(ORKESTRA_TOOLS if mode == "b" else ())]
    return [*args, "--allowedTools", *tools]


def parse_claude(stdout: str) -> dict[str, Any]:
    try:
        data = json.loads(stdout)
    except ValueError as exc:
        raise BenchError(f"claude output is not JSON: {stdout[:200]!r}") from exc
    if isinstance(data, list):  # a stream of events: the last one is the result
        data = next(
            (d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), {}
        )
    if not isinstance(data, dict):
        raise BenchError("claude output is not a JSON object")
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
            done = runner(
                claude_args(mode, task.prompt, settings), workspace, env, settings.timeout_s
            )
            claude = parse_claude(done.stdout)
            if done.returncode != 0:
                error = f"claude exited with {done.returncode}: {done.stderr[-300:]}"
        else:
            error = _run_orkestra(task, workspace, run_dir, settings, runner, env)
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
    home.mkdir(parents=True, exist_ok=True)
    models = f"      - id: {settings.ollama_model}\n        tier: 1\n"
    if settings.ollama_model_2:
        models += f"      - id: {settings.ollama_model_2}\n        tier: 2\n"
    (home / "config.yaml").write_text(
        "version: 1\nlanguage: en\ncache:\n  enabled: false\nrouting:\n  adaptive: false\n"
        "notify:\n  desktop: false\nproviders:\n  ollama:\n    type: ollama\n    models:\n"
        + models, encoding="utf-8",
    )  # fmt: skip
    from orkestra.config import loader
    from orkestra.state import consent, db

    config = loader.load_config(home / "config.yaml", cwd=home, environ={}).config
    with closing(db.connect(home / "state.db")) as conn:
        consent.grant(conn, "ollama", config.providers["ollama"], db.local_now())


# --- results ----------------------------------------------------------------------------------


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
        repeats = sorted({r.repeat for r in mine})
        per_repeat = [sum(r.passed for r in mine if r.repeat == n) for n in repeats]
        tasks = sorted({r.task for r in mine})
        summary[mode] = {
            "label": MODES[mode], "tasks": len(tasks), "repeats": len(repeats),
            "passed": {"mean": _mean(per_repeat), "min": min(per_repeat), "max": max(per_repeat)},
            "by_difficulty": {
                d: {"tasks": len({r.task for r in mine if r.difficulty == d}),
                    "passed_mean": _mean(sum(r.passed for r in mine
                                             if r.difficulty == d and r.repeat == n)
                                         for n in repeats)}
                for d in DIFFICULTIES if any(r.difficulty == d for r in mine)
            },
            "claude_tokens_per_task": (_mean(_claude_tokens(r) for r in mine)
                                       if mode != "c" else None),
            "claude_cache_read_per_task": _mean((r.claude or {}).get("cache_read_input_tokens", 0)
                                                for r in mine) if mode != "c" else None,
            "claude_cost_per_task": _mean((r.claude or {}).get("cost_usd", 0.0) for r in mine)
                                    if mode != "c" else None,
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
        lines.append(
            f"| {s['label']} | {passed['mean']:g}/{s['tasks']} ({passed['min']}-{passed['max']}) "
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
    json_path = out_dir / f"{stamp}.json"
    json_path.write_text(json.dumps({"meta": dict(meta), "summary": summary,
                                     "records": [asdict(r) for r in records]}, indent=2),
                         encoding="utf-8")  # fmt: skip
    md_path = out_dir / f"{stamp}.md"
    header = f"# Benchmark {stamp}\n\n" + "".join(f"- {k}: {v}\n" for k, v in meta.items()) + "\n"
    md_path.write_text(header + markdown(summary, records), encoding="utf-8")
    return json_path, md_path


# --- command line -----------------------------------------------------------------------------


def _version(args: Sequence[str]) -> str:
    try:
        done = subprocess.run(list(args), capture_output=True, text=True, timeout=60,
                              encoding="utf-8", errors="replace")  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return (
        (done.stdout or done.stderr).strip().splitlines()[0]
        if (done.stdout or done.stderr)
        else "unknown"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Orkestra benchmark (Faz 13).")
    parser.add_argument("--mode", choices=[*MODES, "all"], default="all")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--tasks", default="", help="comma-separated id prefixes (default: all)")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    parser.add_argument(
        "--work-dir", type=Path, default=Path(tempfile.gettempdir()) / "orkestra-bench"
    )
    parser.add_argument("--ollama-model", default=DEFAULT_OLLAMA_MODEL)
    parser.add_argument("--ollama-model-2", default=None, help="an optional tier-2 Ollama model")
    parser.add_argument("--claude-model", default=None)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--dry-run", action="store_true",
                        help="check every task and the leak guard; start nothing")  # fmt: skip
    return parser


def main(argv: Sequence[str] | None = None, *, runner: Runner = subprocess_runner) -> int:
    opts = _parser().parse_args(argv)
    modes = list(MODES) if opts.mode == "all" else [opts.mode]
    tasks = load_tasks(TASKS_DIR, [p for p in opts.tasks.split(",") if p])
    total = len(tasks) * len(modes) * opts.repeat
    print(f"{len(tasks)} tasks x {len(modes)} modes x {opts.repeat} repeats = {total} runs")
    if opts.dry_run:
        for task in tasks:
            workspace = prepare_workspace(task, opts.work_dir / "dry-run" / task.id)
            check_no_leak(task, workspace, prompt=task.prompt)
            check_orkestra_task(task, workspace, orkestra_task(task))
        print("dry run: every task is ready, nothing leaks; nothing was started")
        return 0
    claude = shutil.which("claude") or "claude"
    if any(m in ("a", "b") for m in modes) and shutil.which("claude") is None:
        print("claude is not on PATH (needed for modes a and b)", file=sys.stderr)
        return 2
    settings = Settings(out_dir=opts.out, work_dir=opts.work_dir, claude=claude,
                        orkestra=[sys.executable, "-m", "orkestra"],
                        ollama_model=opts.ollama_model, ollama_model_2=opts.ollama_model_2,
                        claude_model=opts.claude_model, timeout_s=opts.timeout)  # fmt: skip
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    home = opts.work_dir / f"home-{stamp}"
    setup_home(home, settings)
    meta = {
        "date": datetime.now().astimezone().isoformat(timespec="minutes"),
        "machine": f"{platform.system()} {platform.release()}, "
                   f"{platform.processor() or platform.machine()}",
        "python": platform.python_version(), "modes": "".join(modes), "repeat": opts.repeat,
        "tasks": len(tasks), "ollama_model": opts.ollama_model,
        "ollama_model_2": opts.ollama_model_2 or "-",
        "claude": _version([claude, "--version"]) if "a" in modes or "b" in modes else "-",
        "claude_model": opts.claude_model or "default",
        "orkestra": _version([*settings.orkestra, "--version"]),
    }  # fmt: skip
    records: list[Record] = []
    for repeat in range(1, opts.repeat + 1):
        for task in tasks:
            for mode in modes:
                record = run_once(task, mode, repeat, settings, runner=runner, home=home)
                records.append(record)
                mark = "PASS" if record.passed else "fail"
                print(f"[{len(records)}/{total}] {task.id} {mode} #{repeat}: {mark} "
                      f"({record.duration_s:.0f} s){' - ' + record.error if record.error else ''}",
                      flush=True)  # fmt: skip
                write_results(records, opts.out, stamp=stamp, meta=meta)  # survives a crash
    json_path, md_path = write_results(records, opts.out, stamp=stamp, meta=meta)
    print(f"results: {json_path}\n         {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
