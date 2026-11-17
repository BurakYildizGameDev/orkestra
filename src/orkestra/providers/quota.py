"""Recognise "quota used up" in what a provider says (Faz 13f, D-084).

Code agents (codex, agy, any generic agent) and APIs say it in their own words; the
patterns live here, together, with a table of tests. They are looked at only when a request
already failed (a non-zero exit, an empty answer, an HTTP 429): a successful answer that talks
about quotas is never a quota error, and bare numbers (``429 files``) never count.

- **hard** (quota, usage limit): ``ProviderQuotaExhausted``; the provider is paused until its
  reset time, or for the configured ``quota_pause_s`` when the message has none. Some quotas
  belong to one model, not the account (OpenRouter's free models, Gemini's per-model quotas):
  those are ``model_only`` and skip just that model (D-085).
- **soft** (rate limited, too many requests): a ``ProviderRateLimit`` as before (retried or
  counted by the circuit breaker), never reported as a used-up quota.

A message these patterns miss still fails the run the old way (bad output, next candidate);
only the pause is lost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from orkestra.errors import ProviderError, ProviderQuotaExhausted, ProviderRateLimit
from orkestra.i18n import t

DETAIL_CHARS = 200

_HARD = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\binsufficient_quota\b",
        r"\bRESOURCE_EXHAUSTED\b",
        r"\busage[ _]limit",
        r"free-models-per-day",
        r"\bquota\b[^\n]{0,40}?\b(?:exceeded|exhausted|reached|used up|will reset|resets?)\b",
        r"\b(?:exceeded|exhausted|used up)\b[^\n]{0,30}?\b(?:quota|capacity)\b",
    )
]
_SOFT = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\brate[ _-]?limit(?:ed\b|[ _](?:exceeded|reached|hit|error)\b)",
        r"\btoo many requests\b",
        r"\b(?:HTTP|status(?: code)?)[ :=/]*429\b",
    )
]

# Quotas of one model (or one group of models), not of the whole account.
_MODEL_ONLY = [
    re.compile(p, re.IGNORECASE)
    for p in (r"free-models-per-day", r"\bRESOURCE_EXHAUSTED\b", r"\bquota metric\b")
]

_UNIT = r"(?:days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)"
_HUMAN = re.compile(
    rf"(?:try again|retry|reset|available again)\s+(?:in|after)\s+"
    rf"((?:\d+(?:\.\d+)?\s*{_UNIT}\b(?:\s*,?\s*(?:and\s+)?)?)+)",
    re.IGNORECASE,
)
_HUMAN_PART = re.compile(rf"(\d+(?:\.\d+)?)\s*({_UNIT})\b", re.IGNORECASE)
_GO = re.compile(
    r"(?:reset|try again|retry)\s+(?:in|after)\s+((?:\d+(?:\.\d+)?(?:h|ms|m|s))+)\b",
    re.IGNORECASE,
)
# JSON, or a Python repr of it (the openai SDK's messages): either quote.
_JSON_SECONDS = re.compile(
    r"[\"'](?:resets_in_seconds|retry_after(?:_seconds)?)[\"']\s*:\s*(\d+(?:\.\d+)?)"
)
_RETRY_DELAY = re.compile(r"[\"']retryDelay[\"']\s*:\s*[\"'](\d+(?:\.\d+)?)s[\"']")
_UNIT_SECONDS = {"d": 86400.0, "h": 3600.0, "m": 60.0, "s": 1.0}
_GO_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(h|ms|m|s)")
_GO_UNITS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}


@dataclass(frozen=True)
class QuotaHit:
    hard: bool
    retry_after_s: float | None  # the reset time in the message, if it has one
    detail: str  # the matching line, shortened: shown to the user and kept in health


def detect(text: str) -> QuotaHit | None:
    """The quota or rate limit ``text`` reports; None if it reports neither."""
    if not text:
        return None
    hard = _first(_HARD, text)
    match = hard or _first(_SOFT, text)
    if match is None:
        return None
    return QuotaHit(hard is not None, reset_seconds(text), _line(text, match))


def reset_seconds(text: str) -> float | None:
    """Seconds until the quota resets, when the message says so."""
    for pattern in (_JSON_SECONDS, _RETRY_DELAY):
        if found := pattern.search(text):
            return float(found[1])
    if found := _GO.search(text):
        seconds = go_seconds(found[1].lower())
        if seconds is not None:
            return seconds
    if found := _HUMAN.search(text):
        return sum(
            float(number) * _UNIT_SECONDS[unit[0].lower()]
            for number, unit in _HUMAN_PART.findall(found[1])
        )
    return None


def go_seconds(duration: str) -> float | None:
    """Seconds in a Go duration such as ``30s``, ``1m30s`` or ``1h0m0s``; None if it is not one."""
    parts = _GO_DURATION_PART.findall(duration)
    if not parts or "".join(n + u for n, u in parts) != duration:
        return None
    return sum(float(n) * _GO_UNITS[u] for n, u in parts)


def pause_seconds(hit: QuotaHit, quota_pause_s: float) -> float:
    """How long to pause: the reset time in the message, else the configured pause."""
    return hit.retry_after_s if hit.retry_after_s is not None else quota_pause_s


def api_rate_limit(
    provider: str, text: str, retry_after_s: float | None, quota_pause_s: float
) -> ProviderError:
    """An API's HTTP 429. A used-up quota pauses the provider (or skips the model, for a quota
    of one model); any other 429 is retried as before (APIs rate limit for seconds, and the
    retry honours ``retry-after``).

    The reset time written in the message wins over ``retry-after``: a generic one-minute
    header must not turn "resets in 3 days" into a request a minute.
    """
    hit = detect(text)
    if hit is None or not hit.hard:
        return ProviderRateLimit(
            t("provider.error.rate_limit", provider=provider), retry_after=retry_after_s
        )
    pause = hit.retry_after_s
    if pause is None:
        pause = retry_after_s if retry_after_s is not None else quota_pause_s
    return ProviderQuotaExhausted(
        t("provider.error.quota", provider=provider, detail=hit.detail),
        pause_s=pause,
        model_only=any(p.search(text) for p in _MODEL_ONLY),
    )


def _first(patterns: list[re.Pattern[str]], text: str) -> re.Match[str] | None:
    found = [m for p in patterns if (m := p.search(text))]
    return min(found, key=lambda m: m.start()) if found else None


def _line(text: str, match: re.Match[str]) -> str:
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    line = text[start : len(text) if end == -1 else end].strip()
    if len(line) <= DETAIL_CHARS:
        return line
    # Keep the match in view: a window around it.
    offset = max(0, match.start() - start - DETAIL_CHARS // 2)
    return line[offset : offset + DETAIL_CHARS].strip()
