"""Unit tests for chief plan expand (YAML parsing, validation, verifier warnings)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from orkestra.chief import plan
from orkestra.config.schema import Config
from orkestra.errors import BudgetExhausted, NoProviderAvailable


def test_parse_expanded_plan_valid() -> None:
    raw = """\
```yaml
tasks:
  - id: task-1
    kind: ask
    prompt: Answer something
```
"""
    spec = plan.parse_and_validate_batch(raw)
    assert len(spec.tasks) == 1
    assert spec.tasks[0].id == "task-1"
    assert spec.tasks[0].kind == "ask"


def test_parse_expanded_plan_invalid_raises_plan_error() -> None:
    raw = "not: [unclosed"
    with pytest.raises(plan.PlanFormatError):
        plan.parse_and_validate_batch(raw)

    raw_invalid_task = """\
tasks:
  - id: "invalid id with spaces"
    kind: edit
    prompt: do it
"""
    with pytest.raises(plan.PlanFormatError):
        plan.parse_and_validate_batch(raw_invalid_task)


def test_check_edit_verifiers_warns_when_missing() -> None:
    raw = """\
tasks:
  - id: edit-task
    kind: edit
    prompt: Fix code
    context:
      files: [src/calc.py]
    verify: []
"""
    spec = plan.parse_and_validate_batch(raw)
    warnings = plan.check_verifier_warnings(spec)
    assert len(warnings) == 1
    assert "edit-task" in warnings[0]


@pytest.mark.parametrize(
    "error",
    [NoProviderAvailable("no tier-2 model"), BudgetExhausted("budget is spent")],
)
def test_expand_plan_does_not_retry_routing_or_budget_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: NoProviderAvailable
) -> None:
    """Only a bad answer is worth another attempt; a routing or budget error is raised as is."""
    calls: list[str] = []

    async def fake_query(config: Config, **kwargs: Any) -> tuple[str, str]:
        calls.append(kwargs["user"])
        raise error

    monkeypatch.setattr(plan, "query_chief_model", fake_query)
    draft = tmp_path / "draft.md"
    draft.write_text("# Plan\n", encoding="utf-8")
    out = tmp_path / "batch.yaml"

    with pytest.raises(type(error)) as caught:
        asyncio.run(plan.expand_plan(draft, out, Config.model_validate({"version": 1})))
    assert caught.value is error
    assert len(calls) == 1
    assert not out.exists()


def test_expand_plan_retries_only_bad_answers_and_feeds_the_error_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = ["tasks: [unclosed", "tasks:\n  - id: ok\n    kind: ask\n    prompt: hi\n"]
    calls: list[str] = []

    async def fake_query(config: Config, **kwargs: Any) -> tuple[str, str]:
        calls.append(kwargs["user"])
        return answers.pop(0), "fake/model"

    monkeypatch.setattr(plan, "query_chief_model", fake_query)
    draft = tmp_path / "draft.md"
    draft.write_text("# Plan\n", encoding="utf-8")
    out = tmp_path / "batch.yaml"

    spec, _warnings = asyncio.run(
        plan.expand_plan(draft, out, Config.model_validate({"version": 1}))
    )
    assert [task.id for task in spec.tasks] == ["ok"]
    assert len(calls) == 2
    assert "YAML" in calls[1]
