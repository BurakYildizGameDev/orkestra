"""``json_schema`` verifier: the answer is JSON and matches the schema (Mimari §10)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from orkestra.errors import UsageError
from orkestra.i18n import t
from orkestra.verify.base import CheckResult, Message, VerifyContext, failed, passed


def load_schema(path: Path) -> dict[str, Any]:
    """Read and check a JSON Schema file; a bad one is a usage error before anything runs."""
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as exc:
        raise UsageError(t("ask.error.schema", path=path, reason=exc)) from exc
    if not isinstance(schema, dict):
        raise UsageError(t("ask.error.schema", path=path, reason=t("ask.error.schema_not_object")))
    return schema


def strip_fences(text: str) -> str:
    """Models often wrap JSON in a ```json fence; accept that."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1])
    return stripped


@dataclass(frozen=True)
class JsonSchemaCheck:
    schema: dict[str, Any] | None  # None: only check that the answer is JSON
    type: str = "json_schema"

    async def check(self, ctx: VerifyContext) -> CheckResult:
        try:
            value = json.loads(strip_fences(ctx.output))
        except ValueError as exc:
            return failed(self.type, Message("ask.verify.not_json", {"reason": exc}))
        if self.schema is None:
            return passed(self.type)
        errors = sorted(
            Draft202012Validator(self.schema).iter_errors(value), key=lambda e: list(e.path)
        )
        if not errors:
            return passed(self.type)
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "$"
        # jsonschema's message is technical English in every language.
        return failed(self.type, Message("verify.schema.mismatch", {"where": where}),
                      f" {first.message}"[:300])  # fmt: skip
