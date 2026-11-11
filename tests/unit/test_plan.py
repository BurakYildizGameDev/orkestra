"""Unit tests for chief plan expand (YAML parsing, validation, verifier warnings)."""

from __future__ import annotations

import pytest

from orkestra.chief import plan


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
