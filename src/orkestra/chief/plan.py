"""Plan expander (Mimari §19).

Takes a draft document (+ MAP.md if present) and prompts a medium tier model to generate
a TaskSpec-compliant batch YAML file. Validates the output with pydantic, retrying up to 2 times
with feedback on failure. Emits warnings for edit tasks without verifiers.
Does NOT execute the batch.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from orkestra.chief.call import query_chief_model
from orkestra.config.loader import dump_yaml, find_git_root
from orkestra.config.schema import Config
from orkestra.errors import UsageError
from orkestra.i18n import t
from orkestra.tasks import batch
from orkestra.tasks.spec import TaskSpec, parse_task

MAX_RETRIES = 2  # up to 2 retries (3 attempts total, Mimari §19)


class PlanFormatError(UsageError):
    """Raised when plan expansion fails to generate a valid batch YAML."""


_SYSTEM_PROMPT = """\
You are an assistant expanding a high-level task plan into an Orkestra batch YAML specification.
The batch specification format is:
tasks:
  - id: <unique-alphanumeric-id>
    kind: ask | edit
    prompt: <clear, self-contained instruction for the worker>
    context:
      files: [<files needed>]
    verify:
      - type: command
        run: "<command>"
      - type: protect_paths
        paths: ["tests/**"]
    depends_on: [<task-ids>]

Rules:
1. Every task must have a unique id (letters, numbers, underscores, hyphens).
2. For edit tasks, include verifiers (e.g. command) whenever feasible.
3. Keep dependency order valid (no cycles).
4. Output ONLY valid YAML.
"""


def _clean_yaml_fence(text: str) -> str:
    stripped = text.strip()
    match = re.search(r"```(?:yaml)?\s*([\s\S]*?)\s*```", stripped)
    if match:
        return match.group(1).strip()
    return stripped


def parse_and_validate_batch(raw: str) -> batch.BatchSpec:
    """Parse raw model output as YAML and validate into a BatchSpec."""
    cleaned = _clean_yaml_fence(raw)
    try:
        data = YAML(typ="safe").load(cleaned)
    except YAMLError as exc:
        raise PlanFormatError(t("plan.error.invalid_yaml", reason=exc)) from exc

    if not isinstance(data, dict):
        raise PlanFormatError(t("plan.error.not_a_mapping"))

    items = data.get("tasks")
    if not isinstance(items, list) or not items:
        raise PlanFormatError(t("plan.error.no_tasks"))

    tasks: list[TaskSpec] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise PlanFormatError(t("plan.error.task_not_mapping", index=i))
        try:
            tasks.append(parse_task(item, source=f"tasks[{i}]"))
        except UsageError as exc:
            reason = "; ".join([exc.message, *exc.details])
            raise PlanFormatError(t("plan.error.task_validation", index=i, reason=reason)) from exc

    try:
        return batch.from_tasks(tasks, source="plan expand", parallel=data.get("parallel"))
    except UsageError as exc:
        reason = "; ".join([exc.message, *exc.details])
        raise PlanFormatError(t("plan.error.batch_validation", reason=reason)) from exc


def check_verifier_warnings(spec: batch.BatchSpec) -> list[str]:
    """Return warnings for edit tasks with no verifiers."""
    warnings: list[str] = []
    for task in spec.tasks:
        if task.kind == "edit" and not task.verify:
            warnings.append(t("plan.warning.no_verifiers", task_id=task.id))
    return warnings


def _find_map_content(cwd: Path) -> str:
    """Read .orkestra/MAP.md if present in project."""
    root = find_git_root(cwd) or cwd
    map_file = root / ".orkestra" / "MAP.md"
    if map_file.is_file():
        try:
            return map_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return ""


async def expand_plan(
    draft_path: Path,
    output_path: Path,
    config: Config,
) -> tuple[batch.BatchSpec, list[str]]:
    """Expand draft plan into batch YAML, write to output_path, and return (BatchSpec, warnings).

    Does NOT execute the batch. Only an answer that is not a valid batch is retried (with
    the error as feedback); routing, budget and provider errors are raised as they are
    (D-062).
    """
    if not draft_path.is_file():
        raise UsageError(t("plan.error.draft_not_found", path=draft_path))

    draft_text = draft_path.read_text(encoding="utf-8", errors="replace")
    map_text = _find_map_content(draft_path.parent)

    user_prompt = f"Draft Plan:\n{draft_text}"
    if map_text:
        user_prompt += f"\n\nProject Map:\n{map_text}"

    last_error: PlanFormatError | None = None
    spec: batch.BatchSpec | None = None

    for attempt in range(1 + MAX_RETRIES):
        prompt_to_send = (
            user_prompt
            if attempt == 0
            else f"Your previous response was invalid: {last_error}.\n"
            f"Please output strictly valid YAML with tasks matching the schema:\n\n{user_prompt}"
        )
        resp, _ = await query_chief_model(
            config,
            tier=2,
            system=_SYSTEM_PROMPT,
            user=prompt_to_send,
        )
        try:
            spec = parse_and_validate_batch(resp)
            break
        except PlanFormatError as exc:
            last_error = exc

    if spec is None:
        raise PlanFormatError(
            t("plan.error.invalid_after_retries", attempts=1 + MAX_RETRIES, reason=last_error)
        )

    warnings = check_verifier_warnings(spec)

    # Convert BatchSpec to clean YAML data and write to output_path
    data: dict[str, Any] = {"tasks": [t.model_dump(mode="json", by_alias=True) for t in spec.tasks]}
    if spec.parallel:
        data["parallel"] = spec.parallel

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dump_yaml(data), encoding="utf-8")

    return spec, warnings
