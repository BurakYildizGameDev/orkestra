from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from orkestra import i18n
from orkestra.errors import UsageError
from orkestra.tasks.spec import (
    CommandVerifier,
    ForbidPaths,
    MaxDiffLines,
    TaskSpec,
    effective_verifiers,
    load_task,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _details(tmp_path: Path, text: str, name: str = "task.yaml") -> tuple[str, ...]:
    with pytest.raises(UsageError) as exc_info:
        load_task(_write(tmp_path / name, text))
    assert exc_info.value.exit_code == 2
    return exc_info.value.details


def test_minimal_ask_task_defaults(tmp_path: Path) -> None:
    task = load_task(_write(tmp_path / "t.yaml", "id: hello\nkind: ask\nprompt: Say hi\n"))
    assert (task.id, task.kind, task.tier, task.privacy) == ("hello", "ask", 1, "normal")
    assert task.verify == [] and task.verify_defaults is True
    assert task.output.format == "text" and task.output.schema_path is None
    assert task.limits.max_retries is None and task.limits.timeout_s is None


def test_json_task_file(tmp_path: Path) -> None:
    data = {"id": "j", "kind": "ask", "prompt": "p", "tier": 2, "tags": ["docs"]}
    task = load_task(_write(tmp_path / "t.json", json.dumps(data)))
    assert (task.tier, task.tags) == (2, ["docs"])


def test_full_example_parses(tmp_path: Path) -> None:
    text = """\
id: docstring-ekle
kind: ask
tier: 1
prompt: |
  Write docstrings.
context:
  files: [src/util.py]
  globs: ["src/**/*.py"]
output:
  format: json
  schema: schema.json
verify:
  - type: command
    run: "python -m pytest -q"
    timeout_s: 300
  - type: json_schema
  - type: regex
    must_match: ["^\\\\{"]
    must_not_match: ["TODO"]
  - type: max_changed_files
    value: 1
  - type: max_diff_lines
    value: 50
  - type: protect_paths
    paths: ["tests/**"]
  - type: forbid_paths
    paths: [".env"]
  - type: files_exist
    paths: ["README.md"]
limits:
  timeout_s: 600
  max_retries: 1
privacy: local_only
depends_on: [other]
"""
    task = load_task(_write(tmp_path / "t.yaml", text))
    assert [v.type for v in task.verify] == [
        "command", "json_schema", "regex", "max_changed_files", "max_diff_lines",
        "protect_paths", "forbid_paths", "files_exist",
    ]  # fmt: skip
    assert isinstance(task.verify[0], CommandVerifier)
    assert task.verify[0].shell is False
    assert task.output.schema_path == "schema.json"
    assert task.limits.max_retries == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("kind: ask\nprompt: p\n", "id: required field is missing"),
        ("id: 'a b'\nkind: ask\nprompt: p\n", "id: "),
        ("id: a\nkind: chat\nprompt: p\n", "kind: must be 'ask' or 'edit'"),
        ("id: a\nkind: ask\nprompt: ''\n", "prompt: must not be empty"),
        ("id: a\nkind: ask\nprompt: p\ntier: 4\n", "tier: must be 1, 2 or 3"),
        (
            "id: a\nkind: ask\nprompt: p\nverify:\n  - type: magic\n",
            "verify[0]: unknown type 'magic'; expected one of: command, json_schema",
        ),
        ("id: a\nkind: ask\nprompt: p\nverify:\n  - type: command\n", "verify[0].run: "),
        ("id: a\nkind: ask\nprompt: p\nverify:\n  - run: x\n", "verify[0]: 'type' is required"),
        ("id: a\nkind: ask\nprompt: p\nverify:\n  - type: regex\n", "verify[0]: "),
        ("id: a\nkind: ask\nprompt: p\nbogus: 1\n", "bogus: unknown field"),
        (
            "id: a\nkind: ask\nprompt: p\noutput:\n  schema: s.json\n",
            "output: output.schema needs format: json",
        ),
    ],
)
def test_invalid_task_messages(tmp_path: Path, text: str, expected: str) -> None:
    details = _details(tmp_path, text)
    assert any(d.startswith(expected) for d in details), details


def test_invalid_regex_is_reported(tmp_path: Path) -> None:
    details = _details(
        tmp_path, "id: a\nkind: ask\nprompt: p\nverify:\n  - type: regex\n    must_match: ['(']\n"
    )
    assert any("verify[0].must_match" in d and "(" in d for d in details), details


def test_messages_are_translated(tmp_path: Path) -> None:
    i18n.set_language("tr")
    details = _details(tmp_path, "id: a\nkind: ask\nprompt: p\nverify:\n  - type: magic\n")
    assert details[0].startswith("verify[0]: bilinmeyen tür 'magic'")


def test_yaml_error_has_line(tmp_path: Path) -> None:
    with pytest.raises(UsageError) as exc_info:
        load_task(_write(tmp_path / "t.yaml", "id: a\nkind: [ask\nprompt: p\n"))
    assert "t.yaml" in exc_info.value.message and "line" in exc_info.value.message


def test_missing_file_and_non_mapping(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        load_task(tmp_path / "nope.yaml")
    with pytest.raises(UsageError):
        load_task(_write(tmp_path / "t.yaml", "- a\n- b\n"))
    with pytest.raises(UsageError):
        load_task(_write(tmp_path / "t.json", "{not json"))


def _task(**data: Any) -> TaskSpec:
    return TaskSpec.model_validate({"id": "t", "kind": "ask", "prompt": "p", **data})


def test_default_verifiers_for_edit() -> None:
    defaults = effective_verifiers(_task(kind="edit"))
    assert isinstance(defaults[0], ForbidPaths)
    assert defaults[0].paths == [".env", "*.pem", "*.key", ".git/**"]
    assert isinstance(defaults[1], MaxDiffLines) and defaults[1].value == 2000
    assert effective_verifiers(_task(kind="edit", verify_defaults=False)) == []


def test_ask_has_no_default_verifiers_but_json_output_is_checked() -> None:
    assert effective_verifiers(_task()) == []
    json_task = _task(output={"format": "json", "schema": "s.json"})
    assert [v.type for v in effective_verifiers(json_task)] == ["json_schema"]
    explicit = _task(
        output={"format": "json"}, verify=[{"type": "json_schema", "schema": "o.json"}]
    )
    assert [v.type for v in effective_verifiers(explicit)] == ["json_schema"]  # not twice


def test_example_tasks_are_valid() -> None:
    from orkestra.verify import build_verifiers

    root = Path(__file__).resolve().parents[2]
    examples = sorted((root / "examples" / "tasks").glob("*.yaml"))
    assert examples
    for path in examples:
        task = load_task(path)
        assert build_verifiers(task, base_dir=root)  # schema files exist and are valid


def test_listed_json_schema_without_schema_inherits_the_output_schema() -> None:
    task = _task(output={"format": "json", "schema": "s.json"}, verify=[{"type": "json_schema"}])
    checks = effective_verifiers(task)
    assert [(v.type, getattr(v, "schema_path", None)) for v in checks] == [
        ("json_schema", "s.json")
    ]


def test_output_schema_is_still_checked_next_to_another_schema() -> None:
    task = _task(
        output={"format": "json", "schema": "s.json"},
        verify=[{"type": "json_schema", "schema": "other.json"}],
    )
    schemas = sorted(getattr(v, "schema_path", "") for v in effective_verifiers(task))
    assert schemas == ["other.json", "s.json"]


def test_edit_format_is_optional_and_checked(tmp_path: Path) -> None:
    assert _task().edit_format is None  # the model's setting, then "replace" (Faz 9c)
    assert _task(kind="edit", edit_format="whole").edit_format == "whole"
    details = _details(tmp_path, "id: t\nkind: edit\nprompt: p\nedit_format: diff\n")
    assert any("edit_format" in d for d in details)
