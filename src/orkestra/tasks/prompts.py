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
    edit_format: EditFormat = "replace",
) -> tuple[str, str]:
    """Return ``(system, user)`` for an ``edit`` task (Mimari §8.2).

    ``replace``: SEARCH/REPLACE blocks (Faz 9c); ``whole``: whole files as JSON.
    """
    parts: list[str] = []
    if context.files:
        parts.append("Context files:\n\n" + render_context(context))
    parts.append("Task:\n" + prompt.strip())
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
    parts.append(rules.strip())
    return load_prompt("worker_system.md").strip(), "\n\n".join(parts)


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
PREVIOUS_ANSWER_CHARS = 8000


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[... truncated]"


def build_retry_message(user: str, answer: str, failures: list[str], *, edit: bool = False) -> str:
    """The original task plus what went wrong last time (``prompts/retry_feedback.md``).

    ``edit``: say that the previous change was discarded. Otherwise a model may read an error
    such as "duplicated export" as a fault of the original file and give up (Faz 9c).
    """
    details = _cut("\n".join(f"- {f}" for f in failures), FEEDBACK_CHARS)
    feedback = (
        load_prompt("retry_feedback.md")
        .strip()
        .format(answer=_cut(answer.strip(), PREVIOUS_ANSWER_CHARS), failures=details)
    )
    if edit:
        feedback += "\n\n" + load_prompt("retry_edit.md").strip()
    return f"{user}\n\n{feedback}"
