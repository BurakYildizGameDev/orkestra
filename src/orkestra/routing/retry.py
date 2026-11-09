"""What to do after a provider error (Mimari §7.1, D-029, D-032).

- Timeouts, 5xx, rate limits: wait and retry the same candidate (1 s, 2 s, 4 s plus jitter,
  or the server's ``retry-after``), at most 3 times. These retries do not count against
  ``max_retries`` (that one is for verification feedback, Faz 5a).
- No connection at all (offline, DNS, refused): one quick retry after 0.5 s to ride out a
  network blip, then skip the provider. Offline, the fallback to a local model costs half a
  second instead of seven.
- Authentication failure, key or model missing: skip the provider for the rest of the run.
- Context too long: next candidate with a bigger context window.
- Anything else (bad output, other 4xx, budget race): next candidate.

The circuit breaker counts every failed attempt; once it opens, retrying stops at once.
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
    ProviderConnectionError,
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
    connection_retries: int = 1
    connection_delay_s: float = 0.5


def classify(error: ProviderError | BudgetExhausted) -> Action:
    if isinstance(error, ProviderTransient | ProviderRateLimit | ProviderConnectionError):
        return Action.RETRY
    if isinstance(error, ProviderAuthError | ProviderUnavailable):
        return Action.SKIP_PROVIDER
    if isinstance(error, ContextTooLong):
        return Action.BIGGER_CONTEXT
    return Action.NEXT


def give_up(error: ProviderError) -> Action:
    """What to do when a retryable error is not retried any more."""
    return Action.SKIP_PROVIDER if isinstance(error, ProviderConnectionError) else Action.NEXT


def delay(
    retry: int,
    error: ProviderError,
    policy: RetryPolicy,
    rand: Callable[[], float] = random.random,
) -> float | None:
    """Seconds to wait before retry number ``retry`` (1-based); ``None`` = do not retry."""
    if isinstance(error, ProviderConnectionError):
        return policy.connection_delay_s if retry <= policy.connection_retries else None
    if retry > policy.max_transport_retries:
        return None
    if isinstance(error, ProviderRateLimit) and error.retry_after is not None:
        return error.retry_after if error.retry_after <= policy.max_wait_s else None
    base = policy.base_delay_s * 2 ** (retry - 1)
    return base * (1 + policy.jitter * rand())
