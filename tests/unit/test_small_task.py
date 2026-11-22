"""Tests for Faz 13q-d: small_task delegation warning (Mimari §19, D-126)."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

import httpx
import pytest
import respx

from orkestra.config.schema import Config
from orkestra.envelope import ResultEnvelope, to_json
from orkestra.state import consent, db
from orkestra.tasks import batch, runner
from orkestra.tasks.context import Context, ContextFile
from orkestra.tasks.prepare import RunOptions, _is_small_task, plan_task
from orkestra.tasks.spec import TaskSpec


def _task(tmp_path: Path, files: dict[str, str]) -> TaskSpec:
    context_files: list[str] = []
    for name, content in files.items():
        file_path = tmp_path / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        context_files.append(name)
    return TaskSpec.model_validate(
        {
            "id": "small-check",
            "kind": "ask",
            "prompt": "Explain this file.",
            "context": {"files": context_files},
            "workspace": str(tmp_path),
        }
    )


def _config(min_files: int = 5, min_lines: int = 100) -> Config:
    return Config.model_validate(
        {
            "version": 1,
            "providers": {
                "dummy": {
                    "type": "ollama",
                    "base_url": "http://ollama.test:11434",
                    "models": [{"id": "m", "tier": 1}],
                }
            },
            "delegation": {"min_files": min_files, "min_lines": min_lines},
        }
    )


def test_is_small_task_detects_below_threshold() -> None:
    task = TaskSpec.model_validate({"id": "t", "kind": "ask", "prompt": "hi"})
    context = Context(files=(ContextFile(Path("a.py"), "a.py", "x\n" * 30, 60),))
    config = _config(min_files=5, min_lines=100)
    options = RunOptions()

    assert _is_small_task(task, context, options, config) is True


def test_is_small_task_above_file_threshold_not_small() -> None:
    task = TaskSpec.model_validate({"id": "t", "kind": "ask", "prompt": "hi"})
    # 6 files, 10 lines each: files >= 5, so not small
    files = tuple(ContextFile(Path(f"f{i}.py"), f"f{i}.py", "x\n" * 10, 20) for i in range(6))
    context = Context(files=files)
    config = _config(min_files=5, min_lines=100)
    options = RunOptions()

    assert _is_small_task(task, context, options, config) is False


def test_is_small_task_above_line_threshold_not_small() -> None:
    task = TaskSpec.model_validate({"id": "t", "kind": "ask", "prompt": "hi"})
    # 1 file, 150 lines: lines >= 100, so not small
    context = Context(files=(ContextFile(Path("big.py"), "big.py", "x\n" * 150, 300),))
    config = _config(min_files=5, min_lines=100)
    options = RunOptions()

    assert _is_small_task(task, context, options, config) is False


def test_is_small_task_threshold_zero_disables() -> None:
    task = TaskSpec.model_validate({"id": "t", "kind": "ask", "prompt": "hi"})
    context = Context(files=(ContextFile(Path("a.py"), "a.py", "x\n" * 10, 20),))
    options = RunOptions()

    # min_files = 0 disables
    assert _is_small_task(task, context, options, _config(min_files=0, min_lines=100)) is False
    # min_lines = 0 disables
    assert _is_small_task(task, context, options, _config(min_files=5, min_lines=0)) is False


def test_is_small_task_from_queue_suppresses_warning() -> None:
    task = TaskSpec.model_validate({"id": "t", "kind": "ask", "prompt": "hi"})
    context = Context(files=(ContextFile(Path("a.py"), "a.py", "x\n" * 10, 20),))
    config = _config(min_files=5, min_lines=100)
    options = RunOptions(from_queue=True)

    assert _is_small_task(task, context, options, config) is False


def test_is_small_task_cheap_profile_suppresses_warning() -> None:
    task = TaskSpec.model_validate({"id": "t", "kind": "ask", "prompt": "hi"})
    context = Context(files=(ContextFile(Path("a.py"), "a.py", "x\n" * 10, 20),))
    config = _config(min_files=5, min_lines=100)
    options = RunOptions(profile="cheap")

    assert _is_small_task(task, context, options, config) is False


def test_is_small_task_batch_run_suppresses_warning() -> None:
    task = TaskSpec.model_validate({"id": "t", "kind": "ask", "prompt": "hi"})
    context = Context(files=(ContextFile(Path("a.py"), "a.py", "x\n" * 10, 20),))
    config = _config(min_files=5, min_lines=100)
    options = RunOptions(in_batch_run=True)

    assert _is_small_task(task, context, options, config) is False


@pytest.mark.asyncio
async def test_plan_task_includes_small_task_warning(tmp_path: Path) -> None:
    task = _task(tmp_path, {"calc.py": "def add(a, b):\n    return a + b\n"})
    config = _config()
    options = RunOptions()

    plan = await plan_task(task, config, options, cwd=tmp_path)
    assert plan.envelope_warnings == ("small_task",)
    assert any("calc.py" in w or "1" in w for w in plan.warnings)


def test_result_envelope_serializes_warnings_when_present() -> None:
    env = ResultEnvelope(
        run_id="r",
        task_id="t",
        status="ok",
        provider="p",
        model="m",
        tier=1,
        warnings=["small_task"],
    )
    doc = json.loads(to_json(env))
    assert doc.get("warnings") == ["small_task"]

    # When None: omitted
    clean_env = ResultEnvelope(
        run_id="r",
        task_id="t",
        status="ok",
        provider="p",
        model="m",
        tier=1,
    )
    clean_doc = json.loads(to_json(clean_env))
    assert "warnings" not in clean_doc


@pytest.mark.asyncio
async def test_batch_estimate_includes_small_task_warning(tmp_path: Path) -> None:
    (tmp_path / "small.py").write_text("print('hello')\n", encoding="utf-8")
    task = TaskSpec.model_validate(
        {
            "id": "task-1",
            "kind": "ask",
            "prompt": "explain",
            "context": {"files": ["small.py"]},
        }
    )
    batch_spec = batch.from_tasks([task], "test")
    config = _config()
    options = RunOptions()
    est = await batch.estimate_batch(batch_spec, config, options, cwd=tmp_path)
    assert any("task-1" in w for w in est.warnings)


@respx.mock
@pytest.mark.asyncio
async def test_run_task_small_task_envelope_warnings(tmp_path: Path) -> None:
    respx.post("http://ollama.test:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {"content": "OK"},
                "done_reason": "stop",
                "prompt_eval_count": 5,
                "eval_count": 2,
            },
        )
    )
    task = _task(tmp_path, {"calc.py": "def add(a, b):\n    return a + b\n"})
    config = _config()
    options = RunOptions()
    with closing(db.connect()) as conn:
        consent.grant(conn, "dummy", config.providers["dummy"], db.local_now())
        outcome = await runner.run_task(task, config, options, cwd=tmp_path, conn=conn)
    assert outcome.exit_code == 0
    assert outcome.envelope.warnings == ["small_task"]
    assert any("calc.py" in w or "1" in w for w in outcome.warnings)
