"""Build worker prompts from the templates in ``orkestra/prompts`` (Mimari §8.1).

Worker prompts are always English.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from orkestra.tasks.context import Context, render_context


@cache
def load_prompt(name: str) -> str:
    return (
        resources.files("orkestra").joinpath("prompts").joinpath(name).read_text(encoding="utf-8")
    )


def build_ask_messages(
    prompt: str, context: Context, schema: dict[str, Any] | None = None
) -> tuple[str, str]:
    """Return ``(system, user)`` for an ``ask`` task."""
    parts: list[str] = []
    if context.files:
        parts.append("Context files:\n\n" + render_context(context))
    parts.append("Task:\n" + prompt.strip())
    if schema is not None:
        parts.append(
            "Output format: a single JSON value that validates against this JSON Schema. "
            "Output only the JSON.\n" + json.dumps(schema, indent=2)
        )
    return load_prompt("worker_system.md").strip(), "\n\n".join(parts)


FEEDBACK_CHARS = 2000  # failed-check details sent back (Mimari §8)
PREVIOUS_ANSWER_CHARS = 8000


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[... truncated]"


def build_retry_message(user: str, answer: str, failures: list[str]) -> str:
    """The original task plus what went wrong last time (``prompts/retry_feedback.md``)."""
    details = _cut("\n".join(f"- {f}" for f in failures), FEEDBACK_CHARS)
    feedback = (
        load_prompt("retry_feedback.md")
        .strip()
        .format(answer=_cut(answer.strip(), PREVIOUS_ANSWER_CHARS), failures=details)
    )
    return f"{user}\n\n{feedback}"
