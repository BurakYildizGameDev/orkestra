"""Exception hierarchy and exit code mapping.

Exit codes (README "Result envelope and exit codes"):

    0  success
    1  task failed verification (failed / escalate)
    2  configuration or usage error
    3  no suitable provider (budget exhausted, all unhealthy, privacy constraint)
    4  user consent required
    5  worktree / apply conflict
    10 unexpected internal error
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    TASK_FAILED = 1
    USAGE = 2
    NO_PROVIDER = 3
    CONSENT_REQUIRED = 4
    CONFLICT = 5
    INTERNAL = 10


class OrkestraError(Exception):
    """Base class for all Orkestra errors.

    ``message`` and ``details`` are shown to the user, so callers pass already translated
    ``t()`` strings. ``details`` holds one line per problem (e.g. each invalid config field).
    """

    exit_code: ExitCode = ExitCode.INTERNAL

    def __init__(self, message: str = "", details: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.details = tuple(details)


class TaskFailed(OrkestraError):
    """Task did not pass verification and could not be escalated further."""

    exit_code = ExitCode.TASK_FAILED


class ConfigError(OrkestraError):
    """Invalid or missing configuration."""

    exit_code = ExitCode.USAGE


class UsageError(OrkestraError):
    """Invalid command line usage."""

    exit_code = ExitCode.USAGE


class NoProviderAvailable(OrkestraError):
    """No provider survived routing (budget, health, privacy, consent filters)."""

    exit_code = ExitCode.NO_PROVIDER


class BudgetExhausted(NoProviderAvailable):
    """A daily budget limit would be exceeded."""


class ConsentRequired(OrkestraError):
    """Provider has not been enabled by the user (``orkestra providers enable``)."""

    exit_code = ExitCode.CONSENT_REQUIRED


class WorkspaceConflict(OrkestraError):
    """Applying worktree changes conflicted with the main working tree."""

    exit_code = ExitCode.CONFLICT


class InternalError(OrkestraError):
    """Unexpected internal failure."""

    exit_code = ExitCode.INTERNAL


class TranslationError(InternalError):
    """A broken or incomplete translation catalog (a bug in Orkestra, not user input)."""


class ProviderError(OrkestraError):
    """Base class for errors raised by provider adapters.

    The router normally handles these; if one escapes to the CLI it means no provider could
    serve the request.
    """

    exit_code = ExitCode.NO_PROVIDER


class ProviderAuthError(ProviderError):
    """Authentication failed. Not retried; the provider is marked unhealthy."""


class ProviderRateLimit(ProviderError):
    """Rate limited by the provider."""

    def __init__(self, message: str = "", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderTransient(ProviderError):
    """Temporary failure: 5xx, connection error, timeout."""


class ContextTooLong(ProviderError):
    """Prompt does not fit into the model's context window."""


class ProviderBadOutput(ProviderError):
    """Provider returned empty, truncated or unparsable output."""


class ProviderUnavailable(ProviderError):
    """Provider is not reachable or not installed."""


class ProviderConnectionError(ProviderUnavailable):
    """No connection at all (offline, DNS failure, connection refused).

    Retried once after a short pause (a network blip), then the provider is skipped.
    """


def exit_code_for(exc: BaseException) -> int:
    """Return the process exit code for an exception."""
    if isinstance(exc, OrkestraError):
        return int(exc.exit_code)
    return int(ExitCode.INTERNAL)
