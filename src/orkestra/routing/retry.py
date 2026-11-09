"""What to do after a provider error (Mimari §7.1).

- Timeouts, 5xx, rate limits: wait and retry the same candidate (1 s, 2 s, 4 s plus jitter,
  or the server's ``retry-after``), at most 3 times. These retries do not count against
  ``max_retries`` (that one is for verification feedback, Faz 5a).
- No connection at all (offline, refused, key missing, model missing): next candidate at once;
  waiting would not help and would only delay the fallback to a local model.
- Authentication failure: the provider is skipped for the rest of the run (and paused 1 hour
  by the circuit breaker); next candidate.
- Context too long: next candidate with a bigger context window.
- Anything else (bad output, other 4xx, budget race): next candidate.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from orkestra.errors import (
    BudgetExhausted,
    ContextTooLong,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimit,
    ProviderTransient,
    ProviderUnavailable,
)


class Action(Enum):
    RETRY = "retry"  # same candidate after a delay
    NEXT = "next"  # next candidate
    SKIP_PROVIDER = "skip_provider"  # next candidate of another provider
    BIGGER_CONTEXT = "bigger_context"  # next candidate with a larger context window


@dataclass(frozen=True)
class RetryPolicy:
    max_transport_retries: int = 3
    base_delay_s: float = 1.0
    jitter: float = 0.25  # up to +25 %
    max_wait_s: float = 60.0  # a longer retry-after moves on instead of waiting


def classify(error: ProviderError | BudgetExhausted) -> Action:
    if isinstance(error, ProviderTransient | ProviderRateLimit):
        return Action.RETRY
    if isinstance(error, ProviderAuthError | ProviderUnavailable):
        return Action.SKIP_PROVIDER
    if isinstance(error, ContextTooLong):
        return Action.BIGGER_CONTEXT
    return Action.NEXT


def delay(
    retry: int,
    error: ProviderError,
    policy: RetryPolicy,
    rand: Callable[[], float] = random.random,
) -> float | None:
    """Seconds to wait before retry number ``retry`` (1-based); ``None`` = do not retry."""
    if retry > policy.max_transport_retries:
        return None
    if isinstance(error, ProviderRateLimit) and error.retry_after is not None:
        return error.retry_after if error.retry_after <= policy.max_wait_s else None
    base = policy.base_delay_s * 2 ** (retry - 1)
    return base * (1 + policy.jitter * rand())
