"""When a shorter session pays off (Faz 13j): the hint from the session's own numbers."""

from __future__ import annotations

import pytest

from orkestra.chief import tokens
from orkestra.config.schema import TokenWeights

W = TokenWeights()


def _session(*contexts: int) -> tokens.Session:
    session = tokens.Session("s")
    session.turns = [tokens.Usage(0, 0, c, 10) for c in contexts]
    return session


@pytest.mark.parametrize(
    ("contexts", "over", "saving"),
    [
        # 180k now, a fresh start is the first request's 47k plus a ~3k brief:
        # every later request reads 130k less, at 0.1 each, over 100 requests.
        ((47_000, 90_000, 180_000), True, (180_000 - 50_000) * 0.1 * 100),
        ((47_000, 60_000, 100_000), False, (100_000 - 50_000) * 0.1 * 100),
        ((47_000, 48_000), False, 0),  # nothing to gain yet
    ],
)
def test_the_hint_compares_this_context_with_a_fresh_start(
    contexts: tuple[int, ...], over: bool, saving: float
) -> None:
    hint = tokens.handoff_hint(_session(*contexts), W, threshold=120_000)
    assert hint is not None
    assert hint.context == contexts[-1] and hint.start == contexts[0] + tokens.BRIEF_TOKENS
    assert hint.over is over
    assert hint.saving_per_100 == pytest.approx(saving)


def test_no_requests_no_hint() -> None:
    assert tokens.handoff_hint(tokens.Session("s"), W, threshold=1) is None


def test_the_hint_follows_the_weights() -> None:
    cheap_reads = TokenWeights(cache_read=0.05)
    hint = tokens.handoff_hint(_session(10_000, 200_000), cheap_reads, threshold=100_000)
    assert hint is not None
    assert hint.saving_per_100 == pytest.approx((200_000 - 13_000) * 0.05 * 100)
