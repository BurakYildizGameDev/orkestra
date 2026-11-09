from __future__ import annotations

import pytest

from orkestra.errors import (
    BudgetExhausted,
    ContextTooLong,
    ProviderAuthError,
    ProviderBadOutput,
    ProviderError,
    ProviderRateLimit,
    ProviderTransient,
    ProviderUnavailable,
)
from orkestra.routing.retry import Action, RetryPolicy, classify, delay


@pytest.mark.parametrize(
    ("error", "action"),
    [
        (ProviderTransient("5xx"), Action.RETRY),
        (ProviderRateLimit("429"), Action.RETRY),
        (ProviderUnavailable("offline"), Action.SKIP_PROVIDER),
        (ProviderAuthError("401"), Action.SKIP_PROVIDER),
        (ContextTooLong("big"), Action.BIGGER_CONTEXT),
        (ProviderBadOutput("empty"), Action.NEXT),
        (ProviderError("400"), Action.NEXT),
        (BudgetExhausted("race"), Action.NEXT),
    ],
)
def test_classify(error: ProviderError, action: Action) -> None:
    assert classify(error) is action


def test_exponential_backoff_without_jitter() -> None:
    policy = RetryPolicy()
    err = ProviderTransient("x")
    assert [delay(n, err, policy, rand=lambda: 0.0) for n in (1, 2, 3)] == [1.0, 2.0, 4.0]
    assert delay(4, err, policy) is None  # at most 3 retries


def test_jitter_adds_up_to_a_quarter() -> None:
    assert delay(1, ProviderTransient("x"), RetryPolicy(), rand=lambda: 1.0) == pytest.approx(1.25)


def test_retry_after_is_honoured() -> None:
    assert delay(1, ProviderRateLimit("x", retry_after=7.0), RetryPolicy()) == 7.0
    assert delay(1, ProviderRateLimit("x"), RetryPolicy(), rand=lambda: 0.0) == 1.0


def test_too_long_retry_after_moves_on() -> None:
    assert delay(1, ProviderRateLimit("x", retry_after=3600.0), RetryPolicy()) is None
