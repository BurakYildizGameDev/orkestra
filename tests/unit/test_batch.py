"""Batch files and their plan: dependencies, cycles, edit tasks on the same files (Faz 7a)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from orkestra.errors import UsageError
from orkestra.tasks import batch


def _ask(task_id: str, **fields: Any) -> dict[str, Any]:
    return {"id": task_id, "kind": "ask", "prompt": f"question {task_id}", **fields}


def _edit(task_id: str, files: list[str], **fields: Any) -> dict[str, Any]:
    return {
        "id": task_id, "kind": "edit", "prompt": f"change {task_id}",
        "context": {"files": files}, **fields,
    }  # fmt: skip


def _write(tmp_path: Path, data: Any, name: str = "batch.yaml") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")  # JSON is valid YAML
    return path


def _details(exc: pytest.ExceptionInfo[UsageError]) -> str:
    return " ".join([exc.value.message, *exc.value.details])


# --- loading ---------------------------------------------------------------------------


def test_a_batch_file_with_parallel(tmp_path: Path) -> None:
    spec = batch.load_batch(_write(tmp_path, {"parallel": 3, "tasks": [_ask("a"), _ask("b")]}))
    assert [t.id for t in spec.tasks] == ["a", "b"] and spec.parallel == 3


def test_parallel_is_optional(tmp_path: Path) -> None:
    assert batch.load_batch(_write(tmp_path, {"tasks": [_ask("a")]})).parallel is None


@pytest.mark.parametrize(
    ("data", "needle"),
    [
        ({"tasks": []}, "tasks"),
        ({"parallel": 2}, "tasks"),
        ({"tasks": [_ask("a"), _ask("a")]}, "a"),  # duplicate id
        ({"tasks": [_ask("a", depends_on=["nope"])]}, "nope"),
        ({"tasks": [_ask("a", depends_on=["a"])]}, "a"),
        ({"tasks": [_ask("a"), {"id": "b", "kind": "ask"}]}, "prompt"),  # invalid task
        ({"tasks": [_ask("a")], "parallel": 0}, "parallel"),
        ({"tasks": [_ask("a")], "extra": 1}, "extra"),
    ],
)
def test_broken_batch_files_are_usage_errors(
    tmp_path: Path, data: dict[str, Any], needle: str
) -> None:
    with pytest.raises(UsageError) as exc:
        batch.load_batch(_write(tmp_path, data))
    assert exc.value.exit_code == 2 and needle in _details(exc)


def test_a_dependency_cycle_is_a_usage_error_naming_the_tasks(tmp_path: Path) -> None:
    data = {
        "tasks": [
            _ask("a", depends_on=["c"]),
            _ask("b", depends_on=["a"]),
            _ask("c", depends_on=["b"]),
            _ask("d"),
        ]
    }
    with pytest.raises(UsageError) as exc:
        batch.load_batch(_write(tmp_path, data))
    assert exc.value.exit_code == 2
    on_cycle = [line.split()[0] for line in exc.value.details]  # "<id> depends on <deps>"
    assert on_cycle == ["a", "b", "c"]  # "d" is not on the cycle


# --- planning --------------------------------------------------------------------------


def _plan(tmp_path: Path, tasks: list[dict[str, Any]]) -> batch.BatchPlan:
    spec = batch.load_batch(_write(tmp_path, {"tasks": tasks}))
    return batch.plan_batch(spec, cwd=tmp_path)


def test_the_order_follows_dependencies_then_the_file(tmp_path: Path) -> None:
    plan = _plan(tmp_path, [_ask("a", depends_on=["c"]), _ask("b"), _ask("c")])
    assert plan.order == ("b", "c", "a")
    assert plan.depends["a"] == frozenset({"c"})


def test_edit_tasks_on_the_same_file_are_put_in_a_row(tmp_path: Path) -> None:
    plan = _plan(
        tmp_path,
        [
            _edit("one", ["src/a.py"]),
            _edit("two", ["src/b.py", "./src/a.py"]),
            _edit("x", ["c.py"]),
        ],
    )
    assert plan.after["two"] == frozenset({"one"})
    assert plan.after.get("x", frozenset()) == frozenset()
    assert len(plan.warnings) == 1 and "one" in plan.warnings[0] and "two" in plan.warnings[0]


def test_the_row_follows_the_dependency_order_not_the_file_order(tmp_path: Path) -> None:
    # "first" depends on "second": putting them in a row by file order would be a cycle.
    plan = _plan(
        tmp_path,
        [_edit("first", ["a.py"], depends_on=["second"]), _edit("second", ["a.py"])],
    )
    assert plan.order == ("second", "first")
    assert plan.after.get("second", frozenset()) == frozenset()


def test_ask_tasks_never_wait_for_each_other(tmp_path: Path) -> None:
    plan = _plan(
        tmp_path, [_ask("a", context={"files": ["x.py"]}), _ask("b", context={"files": ["x.py"]})]
    )
    assert not any(plan.after.values()) and plan.warnings == ()


def test_files_in_different_workspaces_do_not_overlap(tmp_path: Path) -> None:
    plan = _plan(
        tmp_path,
        [_edit("a", ["x.py"], workspace="one"), _edit("b", ["x.py"], workspace="two")],
    )
    assert not any(plan.after.values())
