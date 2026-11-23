"""Build worker prompts from the templates in ``orkestra/prompts`` (Mimari §8.1).

Worker prompts are always English.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import cache
from importlib import resources
from typing import Any

from orkestra.config.schema import EditFormat
from orkestra.tasks.context import Context, render_context


@cache
def load_prompt(name: str) -> str:
    return (
        resources.files("orkestra").joinpath("prompts").joinpath(name).read_text(encoding="utf-8")
    )


def build_ask_messages(
    prompt: str,
    context: Context,
    schema: dict[str, Any] | None = None,
    *,
    json_output: bool = False,
) -> tuple[str, str]:
    """Return ``(system, user)`` for an ``ask`` task (``json_output``: JSON without a schema)."""
    parts: list[str] = []
    if context.files:
        parts.append("Context files:\n\n" + render_context(context))
    parts.append("Task:\n" + prompt.strip())
    if schema is not None:
        parts.append(
            "Output format: a single JSON value that validates against this JSON Schema. "
            "Output only the JSON.\n" + json.dumps(schema, indent=2)
        )
    elif json_output:
        parts.append("Output format: a single JSON value. Output only the JSON.")
    return load_prompt("worker_system.md").strip(), "\n\n".join(parts)


def build_edit_messages(
    prompt: str,
    context: Context,
    *,
    editable: Sequence[str],
    allow_new: bool,
    protected: Sequence[str],
    edit_format: EditFormat,
) -> tuple[str, str]:
    """Return ``(system, user)`` for an ``edit`` task (Mimari §8.2).

    ``replace``: SEARCH/REPLACE blocks (Faz 9c); ``whole``: whole files as JSON. The format
    is required: the router chooses it per candidate (``edit_format: auto``).
    """
    rules = edit_rules(
        editable=editable, allow_new=allow_new, protected=protected, edit_format=edit_format
    )
    return load_prompt("worker_system.md").strip(), f"{edit_body(prompt, context)}\n\n{rules}"


def edit_body(prompt: str, context: Context) -> str:
    """The context and the task: the same for every answer format (rendered once per run)."""
    parts: list[str] = []
    if context.files:
        parts.append("Context files:\n\n" + render_context(context))
    parts.append("Task:\n" + prompt.strip())
    return "\n\n".join(parts)


def edit_rules(
    *, editable: Sequence[str], allow_new: bool, protected: Sequence[str], edit_format: EditFormat
) -> str:
    """The answer format's rules (``prompts/edit_replace.md`` or ``edit_format.md``)."""
    new_files = (
        "You may also create new files."
        if allow_new
        else "Do not create new files; change only the files listed above."
    )
    guarded = (
        f"- Never create or change files matching: {', '.join(protected)}" if protected else ""
    )
    # Plain replacement: the template is full of JSON braces.
    rules = (
        load_prompt("edit_replace.md" if edit_format == "replace" else "edit_format.md")
        .replace("{editable}", ", ".join(editable) if editable else "(none)")
        .replace("{new_files}", new_files)
        .replace("{protected}", guarded)
    )
    return rules.strip()


def build_agent_prompt(
    prompt: str,
    context: Context,
    *,
    edit: bool,
    editable: Sequence[str] = (),
    allow_new: bool = True,
    protected: Sequence[str] = (),
    schema: dict[str, Any] | None = None,
    json_output: bool = False,
) -> str:
    """The prompt for a code agent (Mimari §5.3): agents read the files themselves."""
    rules = [load_prompt("agent_task.md").strip()]
    if edit:
        rules += [
            "- You are in a git worktree made for this task. Change files only inside this "
            "directory, never outside it.",
            "- Do not commit. Leave your changes in the working tree.",
        ]
        if editable:
            rules.append(f"- Files to change: {', '.join(editable)}")
        if not allow_new:
            rules.append("- Do not create new files.")
        if protected:
            rules.append(f"- Never create or change files matching: {', '.join(protected)}")
        rules.append("- When you are done, reply with one or two sentences: what you changed.")
    else:
        rules.append("- Do not change any files; only read them.")
    parts = ["\n".join(rules), "Task:\n" + prompt.strip()]
    others = [f.display for f in context.files if f.display not in editable]
    if others:
        parts.append("Files to read: " + ", ".join(others))
    if not edit and schema is not None:
        parts.append(
            "Final answer format: a single JSON value that validates against this JSON Schema. "
            "Output only the JSON.\n" + json.dumps(schema, indent=2)
        )
    elif not edit and json_output:
        parts.append("Final answer format: a single JSON value. Output only the JSON.")
    return "\n\n".join(parts)


FEEDBACK_CHARS = 2000  # failed-check details sent back (Mimari §8)
TRUNCATED = "\n[... truncated]"
PREVIOUS_ANSWER_CHARS = 8000


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + TRUNCATED


def _allocate_shares(lengths: Sequence[int], budget: int) -> list[int]:
    n = len(lengths)
    if n == 0:
        return []
    if budget <= 0:
        return [0] * n
    allocations = [0] * n
    remaining_indices = set(range(n))
    remaining_budget = budget
    while remaining_indices:
        share = remaining_budget // len(remaining_indices)
        if share == 0:
            for idx in remaining_indices:
                allocations[idx] = remaining_budget // len(remaining_indices)
            break
        satisfied = [i for i in remaining_indices if lengths[i] <= share]
        if not satisfied:
            each = remaining_budget // len(remaining_indices)
            remainder = remaining_budget % len(remaining_indices)
            for j, idx in enumerate(sorted(remaining_indices)):
                allocations[idx] = each + (1 if j < remainder else 0)
            break
        for idx in satisfied:
            allocations[idx] = lengths[idx]
            remaining_budget -= lengths[idx]
            remaining_indices.remove(idx)
    return allocations


def _cut_within(text: str, limit: int) -> str:
    """Like ``_cut``, but the truncation mark counts towards ``limit`` (D-132)."""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(TRUNCATED))] + TRUNCATED


def format_failures(failures: Sequence[str], limit: int = FEEDBACK_CHARS) -> str:
    """Every failed check gets its fair share of ``limit`` (Faz 13r-b1).

    Command output is already digested by the check itself (``verify/command.py``); digesting
    it again here could drop lines (D-132).
    """
    if not failures:
        return ""
    overhead = 3 * len(failures)  # "- " and the newline per item
    allocations = _allocate_shares([len(s) for s in failures], max(0, limit - overhead))
    cut_items = [_cut_within(s, a) for s, a in zip(failures, allocations, strict=True)]
    return "\n".join(f"- {item}" for item in cut_items)


def build_retry_message(user: str, answer: str, failures: list[str], *, edit: bool = False) -> str:
    """The original task plus what went wrong last time (``prompts/retry_feedback.md``).

    ``edit``: say that the previous change was discarded. Otherwise a model may read an error
    such as "duplicated export" as a fault of the original file and give up (Faz 9c).
    """
    details = _cut(format_failures(failures, FEEDBACK_CHARS), FEEDBACK_CHARS)
    feedback = (
        load_prompt("retry_feedback.md")
        .strip()
        .format(answer=_cut(answer.strip(), PREVIOUS_ANSWER_CHARS), failures=details)
    )
    if edit:
        feedback += "\n\n" + load_prompt("retry_edit.md").strip()
    return f"{user}\n\n{feedback}"
