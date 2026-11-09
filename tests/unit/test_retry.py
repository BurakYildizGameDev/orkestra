from __future__ import annotations

import pytest

from orkestra.errors import (
    BudgetExhausted,
    ContextTooLong,
    ProviderAuthError,
    ProviderBadOutput,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimit,
    ProviderTransient,
    ProviderUnavailable,
)
from orkestra.routing.retry import Action, RetryPolicy, classify, delay, give_up


@pytest.mark.parametrize(
    ("error", "action"),
    [
        (ProviderTransient("5xx"), Action.RETRY),
        (ProviderRateLimit("429"), Action.RETRY),
        (ProviderConnectionError("offline"), Action.RETRY),
        (ProviderUnavailable("model missing"), Action.SKIP_PROVIDER),
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


def test_no_connection_gets_one_quick_retry_then_skips_the_provider() -> None:
    err = ProviderConnectionError("offline")
    assert delay(1, err, RetryPolicy()) == 0.5
    assert delay(2, err, RetryPolicy()) is None
    assert give_up(err) is Action.SKIP_PROVIDER
    assert give_up(ProviderTransient("5xx")) is Action.NEXT


def test_missing_model_moves_to_the_next_model_not_the_next_provider() -> None:
    from orkestra.errors import ProviderModelNotFound

    assert classify(ProviderModelNotFound("no such model")) is Action.NEXT
