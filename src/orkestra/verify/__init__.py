"""Verifiers (Mimari §10): turn a task's ``verify`` list into checks and run them."""

from __future__ import annotations

from pathlib import Path

from orkestra.tasks.spec import (
    CommandVerifier,
    FilesExist,
    ForbidPaths,
    JsonSchemaVerifier,
    MaxChangedFiles,
    MaxDiffLines,
    ProtectPaths,
    RegexVerifier,
    TaskSpec,
    VerifierSpec,
    effective_verifiers,
)
from orkestra.verify.base import CheckResult, FileChange, Verifier, VerifyContext, run_verifiers
from orkestra.verify.command import CommandCheck
from orkestra.verify.files import (
    FilesExistCheck,
    MaxChangedFilesCheck,
    MaxDiffLinesCheck,
    PathsCheck,
)
from orkestra.verify.regex import RegexCheck
from orkestra.verify.schema import JsonSchemaCheck, load_schema

__all__ = [
    "CheckResult",
    "FileChange",
    "Verifier",
    "VerifyContext",
    "build_verifiers",
    "run_verifiers",
]


def _build(spec: VerifierSpec, base_dir: Path) -> Verifier:
    if isinstance(spec, CommandVerifier):
        return CommandCheck(spec.run, spec.timeout_s, spec.shell)
    if isinstance(spec, JsonSchemaVerifier):
        schema = load_schema(base_dir / spec.schema_path) if spec.schema_path else None
        return JsonSchemaCheck(schema)
    if isinstance(spec, RegexVerifier):
        return RegexCheck(tuple(spec.must_match), tuple(spec.must_not_match))
    if isinstance(spec, MaxChangedFiles):
        return MaxChangedFilesCheck(spec.value)
    if isinstance(spec, MaxDiffLines):
        return MaxDiffLinesCheck(spec.value)
    if isinstance(spec, ProtectPaths | ForbidPaths):
        return PathsCheck(spec.type, tuple(spec.paths))
    if isinstance(spec, FilesExist):
        return FilesExistCheck(tuple(spec.paths))
    raise AssertionError(f"unhandled verifier {spec!r}")  # pragma: no cover


def build_verifiers(task: TaskSpec, *, base_dir: Path) -> list[Verifier]:
    """Checks for the task, implicit ones included. Bad schema files fail here (exit 2)."""
    return [_build(spec, base_dir) for spec in effective_verifiers(task)]
