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
