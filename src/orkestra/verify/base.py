"""Verifier building blocks (Mimari §10).

Every verifier returns a ``CheckResult``: the envelope entry (``detail`` in the interface
language), the same message in English for the worker's retry feedback (worker prompts are
always English), and the full log for ``attempts/<n>/verify.log``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from orkestra.envelope import VerificationResult
from orkestra.i18n import t, t_in

DETAIL_CHARS = 2000  # command output kept in the envelope (the full output is in verify.log)


@dataclass(frozen=True)
class FileChange:
    """One changed file, relative to the workspace (filled by edit tasks, Faz 5b/5c)."""

    path: str
    insertions: int = 0
    deletions: int = 0


@dataclass(frozen=True)
class VerifyContext:
    workdir: Path  # commands run here; relative paths are resolved here
    output: str  # the worker's answer, unmasked
    changes: tuple[FileChange, ...] = ()  # empty for ask tasks


@dataclass(frozen=True)
class Message:
    """A translatable message, rendered once for the user and once (English) for the worker."""

    key: str
    params: Mapping[str, object] = field(default_factory=dict)

    def user(self) -> str:
        return t(self.key, **self.params)

    def english(self) -> str:
        return t_in("en", self.key, **self.params)


@dataclass(frozen=True)
class CheckResult:
    result: VerificationResult
    feedback: str = ""  # English, for the retry prompt; empty when the check passed
    log: str = ""


def passed(kind: str, detail: str = "", log: str = "") -> CheckResult:
    return CheckResult(VerificationResult(type=kind, ok=True, detail=detail), log=log)


def failed(kind: str, message: Message, extra: str = "", log: str = "") -> CheckResult:
    """``extra``: untranslated text appended to the message (e.g. command output)."""
    return CheckResult(
        VerificationResult(type=kind, ok=False, detail=message.user() + extra),
        feedback=f"{kind}: {message.english()}{extra}",
        log=log,
    )


class Verifier(Protocol):
    @property
    def type(self) -> str: ...

    async def check(self, ctx: VerifyContext) -> CheckResult: ...


async def run_verifiers(checks: Sequence[Verifier], ctx: VerifyContext) -> list[CheckResult]:
    """Run every check (in order, all of them: the feedback should name every problem)."""
    return [await check.check(ctx) for check in checks]
