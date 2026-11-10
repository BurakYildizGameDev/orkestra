"""Task files (Mimari §4.2) and their verifiers (§10).

A task file is YAML or JSON. Relative paths in it (context files and globs, schema files,
``files_exist``) are resolved against the task's base directory: ``workspace`` if given,
otherwise the directory ``orkestra`` runs in (D-038).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from orkestra.config.loader import format_validation_error, read_yaml
from orkestra.config.schema import EditFormatSetting, NonNegInt, PosInt, Tier
from orkestra.errors import ConfigError, UsageError
from orkestra.i18n import t

VERIFIER_TYPES = (
    "command", "json_schema", "regex", "max_changed_files", "max_diff_lines",
    "protect_paths", "forbid_paths", "files_exist",
)  # fmt: skip
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Added to every edit task unless ``verify_defaults: false`` (Mimari §10).
DEFAULT_FORBIDDEN = [".env", "*.pem", "*.key", ".git/**"]
DEFAULT_MAX_DIFF_LINES = 2000


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


Paths = Annotated[list[Annotated[str, Field(min_length=1)]], Field(min_length=1)]


# --- verifiers -------------------------------------------------------------------------


class CommandVerifier(_Model):
    """Runs a command; exit code 0 passes. No shell unless ``shell: true`` (pipes, ``&&``)."""

    type: Literal["command"]
    run: Annotated[str, Field(min_length=1)]
    timeout_s: PosInt = 300
    shell: bool = False


class JsonSchemaVerifier(_Model):
    """The answer is JSON (fences allowed) and, with a schema, valid against it."""

    type: Literal["json_schema"]
    schema_path: str | None = Field(default=None, alias="schema")


class RegexVerifier(_Model):
    """Every ``must_match`` pattern is found in the answer, no ``must_not_match`` pattern is."""

    type: Literal["regex"]
    must_match: list[str] = Field(default_factory=list)
    must_not_match: list[str] = Field(default_factory=list)

    @field_validator("must_match", "must_not_match")
    @classmethod
    def _compiles(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    t("task.validation.regex_invalid", pattern=pattern, error=exc)
                ) from exc
        return patterns

    @model_validator(mode="after")
    def _has_patterns(self) -> RegexVerifier:
        if not self.must_match and not self.must_not_match:
            raise ValueError(t("task.validation.regex_empty"))
        return self


class MaxChangedFiles(_Model):
    type: Literal["max_changed_files"]
    value: NonNegInt


class MaxDiffLines(_Model):
    type: Literal["max_diff_lines"]
    value: NonNegInt


class ProtectPaths(_Model):
    """Files matching these patterns must not change (no passing by editing the tests)."""

    type: Literal["protect_paths"]
    paths: Paths


class ForbidPaths(_Model):
    """Files matching these patterns must not be created or changed (``.env``, keys)."""

    type: Literal["forbid_paths"]
    paths: Paths


class FilesExist(_Model):
    """Each path exists; a glob pattern needs at least one match."""

    type: Literal["files_exist"]
    paths: Paths


VerifierSpec = Annotated[
    CommandVerifier
    | JsonSchemaVerifier
    | RegexVerifier
    | MaxChangedFiles
    | MaxDiffLines
    | ProtectPaths
    | ForbidPaths
    | FilesExist,
    Field(discriminator="type"),
]


# --- task ------------------------------------------------------------------------------


class ContextSpec(_Model):
    files: list[str] = Field(default_factory=list)
    globs: list[str] = Field(default_factory=list)


class OutputSpec(_Model):
    format: Literal["text", "json"] = "text"
    schema_path: str | None = Field(default=None, alias="schema")

    @model_validator(mode="after")
    def _schema_needs_json(self) -> OutputSpec:
        if self.schema_path is not None and self.format != "json":
            raise ValueError(t("task.validation.schema_needs_json"))
        return self


class Limits(_Model):
    timeout_s: PosInt | None = None  # per request; default: the provider's timeout
    max_retries: NonNegInt | None = None  # retries with feedback; default: defaults.max_retries


class TaskSpec(_Model):
    id: str
    kind: Literal["ask", "edit"]
    tier: Tier = 1
    prompt: Annotated[str, Field(min_length=1)]
    context: ContextSpec = Field(default_factory=ContextSpec)
    workspace: str | None = None
    output: OutputSpec = Field(default_factory=OutputSpec)
    verify: list[VerifierSpec] = Field(default_factory=list)
    verify_defaults: bool = True
    edit_format: EditFormatSetting | None = None  # API workers: None = the model's, then auto
    allow_new_files: bool = True  # edit: the worker may create files that are not in context
    limits: Limits = Field(default_factory=Limits)
    privacy: Literal["normal", "local_only"] = "normal"
    provider: str | None = None
    model: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not _TASK_ID.match(value):
            raise ValueError(t("task.validation.id", id=value))
        return value

    @field_validator("prompt")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(t("config.validation.empty"))
        return value

    def base_dir(self, cwd: Path) -> Path:
        """Where relative paths in the task point to (see the module docstring)."""
        return (cwd / self.workspace).resolve() if self.workspace else cwd.resolve()


def effective_verifiers(task: TaskSpec) -> list[VerifierSpec]:
    """The task's verifiers plus the implicit ones.

    - ``output.format: json`` adds a ``json_schema`` check with ``output.schema`` unless the
      task already checks that schema; a listed ``json_schema`` without a schema of its own
      checks ``output.schema``.
    - Edit tasks get ``forbid_paths`` for secrets and ``.git`` and ``max_diff_lines: 2000``
      unless ``verify_defaults: false`` (Mimari §10).
    """
    declared = task.output.schema_path
    checks: list[VerifierSpec] = [
        # A json_schema check without its own schema means "the output schema".
        v.model_copy(update={"schema_path": declared})
        if isinstance(v, JsonSchemaVerifier) and v.schema_path is None and declared
        else v
        for v in task.verify
    ]
    schemas = [v.schema_path for v in checks if isinstance(v, JsonSchemaVerifier)]
    if task.output.format == "json" and (declared not in schemas if declared else not schemas):
        checks.insert(0, JsonSchemaVerifier(type="json_schema", schema=declared))
    if task.kind == "edit" and task.verify_defaults:
        checks.append(ForbidPaths(type="forbid_paths", paths=list(DEFAULT_FORBIDDEN)))
        checks.append(MaxDiffLines(type="max_diff_lines", value=DEFAULT_MAX_DIFF_LINES))
    return checks


# --- loading ---------------------------------------------------------------------------

TASK_UNION_TAGS = {"verify": VERIFIER_TYPES}


def read_document(path: Path) -> Any:
    """A task or batch file as data: YAML, or JSON for ``.json``; problems are usage errors."""
    return _read(path)


def _read(path: Path) -> Any:
    if path.suffix.lower() != ".json":
        try:
            return read_yaml(path)
        except ConfigError as exc:  # same messages; a task file is a usage problem
            raise UsageError(exc.message, exc.details) from exc
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise UsageError(t("config.error.read", path=path, reason=exc)) from exc
    except ValueError as exc:
        raise UsageError(t("task.error.json", path=path, reason=exc)) from exc


def load_task(path: Path) -> TaskSpec:
    """Read and validate a task file. Problems raise ``UsageError`` (exit code 2)."""
    data = _read(path)
    if not isinstance(data, dict):
        raise UsageError(t("config.error.not_mapping", path=path))
    return parse_task(data, source=str(path))


def ask_task(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    tier: int | None = None,
    local_only: bool = False,
    context: Sequence[Path] = (),
    schema: Path | None = None,
) -> TaskSpec:
    """The task behind ``orkestra ask`` (same lifecycle as a task file)."""
    data: dict[str, Any] = {
        "id": "ask",
        "kind": "ask",
        "tier": tier or 1,
        "prompt": prompt,
        "context": {"files": [str(p) for p in context]},
        "privacy": "local_only" if local_only else "normal",
        "provider": provider,
        "model": model,
    }
    if schema is not None:
        data["output"] = {"format": "json", "schema": str(schema)}
    return parse_task(data, source="ask")


def parse_task(data: dict[str, Any], *, source: str) -> TaskSpec:
    try:
        return TaskSpec.model_validate(data)
    except ValidationError as exc:
        raise UsageError(
            t("task.error.invalid", path=source),
            details=format_validation_error(exc, TASK_UNION_TAGS),
        ) from exc
