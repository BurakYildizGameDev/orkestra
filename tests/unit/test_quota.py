"""When a provider's quota runs out (Faz 13f): recognise it, pause the provider, move on."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx

from orkestra.config.schema import CliAgentProvider, OllamaProvider, OpenAICompatProvider
from orkestra.errors import (
    ProviderBadOutput,
    ProviderQuotaExhausted,
    ProviderRateLimit,
    ProviderTransient,
)
from orkestra.providers import cli_agent as ca
from orkestra.providers import quota
from orkestra.providers.base import AgentRequest, CompletionRequest
from orkestra.providers.ollama import OllamaChat
from orkestra.providers.openai_compat import OpenAICompatChat
from orkestra.routing.retry import Action, classify
from orkestra.state import db, health

FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_agent.py"
TZ = timezone(timedelta(hours=3))
NOON = datetime(2026, 11, 9, 12, 0, tzinfo=TZ)

CODEX_LIMIT = (
    "You've hit your usage limit. Upgrade to Pro (https://openai.com/chatgpt/pricing) "
    "or try again in 2 days 3 hours 4 minutes."
)
AGY_LIMIT = (
    "Error: RESOURCE_EXHAUSTED: You have exhausted your capacity on this model. "
    "Your quota will reset after 2h30m15s."
)


# --- recognising the message -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "hard", "seconds"),
    [
        (CODEX_LIMIT, True, 2 * 86400 + 3 * 3600 + 4 * 60),
        (
            '{"type":"error","message":"You\'ve hit your usage limit. Try again in 5 hours '
            '19 minutes."}',
            True,
            5 * 3600 + 19 * 60,
        ),
        ('{"error":{"type":"usage_limit_reached","resets_in_seconds":7200}}', True, 7200),
        (AGY_LIMIT, True, 2 * 3600 + 30 * 60 + 15),
        (
            '{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": '
            '[{"retryDelay": "36s"}]}}',
            True,
            36,
        ),
        ("Quota exceeded for quota metric 'Generate Content API requests per day'", True, None),
        ("You exceeded your current quota, please check your plan. insufficient_quota", True, None),
        ("Rate limit exceeded: free-models-per-day. Add 10 credits to unlock more.", True, None),
        ("you've reached your weekly usage limit", True, None),
        ("429 Too Many Requests", False, None),
        ("Rate limit exceeded. Please retry after 30 seconds.", False, 30),
        ("request failed with status code 429", False, None),
    ],
)
def test_quota_messages_are_recognised(text: str, hard: bool, seconds: float | None) -> None:
    hit = quota.detect(text)
    assert hit is not None, text
    assert hit.hard is hard
    assert hit.retry_after_s == seconds


@pytest.mark.parametrize(
    "text",
    [
        "boom: not logged in",
        "FAILED tests/test_quota_exceeded.py::test_usage - assert 1 == 2",
        "processed 429 files, 3 errors",
        "the rate limiter module was updated",
        "exit status 1",
        "",
    ],
)
def test_ordinary_failures_are_not_quota(text: str) -> None:
    assert quota.detect(text) is None


def test_the_shown_detail_is_the_matching_line_shortened() -> None:
    hit = quota.detect("starting\nloading tools\n" + CODEX_LIMIT + "\nbye\n")
    assert hit is not None
    assert hit.detail.startswith("You've hit your usage limit") and "\n" not in hit.detail
    assert len(quota.detect("x" * 500 + " usage limit " + "y" * 500).detail) <= 200  # type: ignore[union-attr]


def test_pause_uses_the_reset_time_then_the_default() -> None:
    assert quota.pause_seconds(quota.detect(AGY_LIMIT), 3600) == 9015  # type: ignore[arg-type]
    assert quota.pause_seconds(quota.detect("insufficient_quota"), 3600) == 3600  # type: ignore[arg-type]
    # A plain rate limit without a hint: the short pause, not the quota one.
    assert quota.pause_seconds(quota.detect("429 Too Many Requests"), 3600) == 300  # type: ignore[arg-type]


# --- the circuit breaker ---------------------------------------------------------------


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "state.db")) as connection:
        yield connection


def test_quota_pauses_at_once_until_the_reset(conn: sqlite3.Connection) -> None:
    error = ProviderQuotaExhausted("agy: usage limit", pause_s=2 * 3600)
    state = health.record_failure(conn, "agy", error, NOON)
    assert state.is_open(NOON + timedelta(hours=1, minutes=59))
    assert not state.is_open(NOON + timedelta(hours=2, seconds=1))
    stored = health.get(conn, "agy")
    assert stored.reason == "quota" and stored.last_error == "agy: usage limit"
    assert stored.open_until == NOON + timedelta(hours=2)


def test_a_quota_pause_is_at_least_a_minute_and_at_most_a_week(conn: sqlite3.Connection) -> None:
    state = health.record_failure(conn, "a", ProviderQuotaExhausted("x", pause_s=5), NOON)
    assert state.open_until == NOON + timedelta(minutes=1)
    state = health.record_failure(conn, "b", ProviderQuotaExhausted("x", pause_s=30 * 86400), NOON)
    assert state.open_until == NOON + timedelta(days=7)


def test_providers_enable_opens_a_quota_pause(conn: sqlite3.Connection) -> None:
    health.record_failure(conn, "agy", ProviderQuotaExhausted("x", pause_s=3600), NOON)
    health.reset(conn, "agy")
    state = health.get(conn, "agy")
    assert not state.is_open(NOON) and state.reason is None


def test_other_pauses_say_why(conn: sqlite3.Connection) -> None:
    for _ in range(3):
        state = health.record_failure(conn, "p", ProviderTransient("x"), NOON)
    assert state.reason == "errors" and health.get(conn, "p").reason == "errors"


def test_quota_paused_lists_only_quota_pauses_that_still_hold(conn: sqlite3.Connection) -> None:
    health.record_failure(conn, "agy", ProviderQuotaExhausted("x", pause_s=3600), NOON)
    health.record_failure(conn, "old", ProviderQuotaExhausted("x", pause_s=60), NOON)
    for _ in range(3):
        health.record_failure(conn, "flaky", ProviderTransient("x"), NOON)
    paused = health.quota_paused(conn, NOON + timedelta(minutes=2))
    assert [h.provider for h in paused] == ["agy"]


def test_until_text_adds_the_date_when_it_is_not_today() -> None:
    assert health.until_text(NOON + timedelta(hours=2), NOON) == "14:00"
    assert health.until_text(NOON + timedelta(days=2), NOON) == "2026-11-11 12:00"


def test_quota_skips_the_provider_for_the_rest_of_the_run() -> None:
    assert classify(ProviderQuotaExhausted("x", pause_s=60)) is Action.SKIP_PROVIDER


# --- code agents -----------------------------------------------------------------------


def _agent(mode: str, **fields: object) -> ca.CliAgent:
    cfg = CliAgentProvider.model_validate(
        {"type": "cli_agent", "command": sys.executable, "kind": "generic",
         "extra_args": [str(FAKE), mode], **fields}
    )  # fmt: skip
    return ca.create_agent("fake", cfg, os.environ)


def _request(tmp_path: Path) -> AgentRequest:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    attempt = tmp_path / "attempt"
    attempt.mkdir(exist_ok=True)
    return AgentRequest(
        prompt="do it", workdir=work, model=None, sandbox="workspace-write", timeout_s=30,
        output_file=attempt / "agent_output.md",
    )  # fmt: skip


def test_an_agent_that_ran_out_of_quota_raises_quota_with_its_reset(tmp_path: Path) -> None:
    with pytest.raises(ProviderQuotaExhausted) as exc_info:
        asyncio.run(_agent("quota").run(_request(tmp_path)))
    error = exc_info.value
    assert error.pause_s == 5 * 3600 + 19 * 60
    assert "usage limit" in error.message and "fake" in error.message


def test_without_a_reset_time_the_configured_pause_is_used(tmp_path: Path) -> None:
    with pytest.raises(ProviderQuotaExhausted) as exc_info:
        asyncio.run(_agent("quota_plain", quota_pause_s=1800).run(_request(tmp_path)))
    assert exc_info.value.pause_s == 1800


def test_a_successful_answer_about_quotas_is_not_a_quota_error(tmp_path: Path) -> None:
    result = asyncio.run(_agent("quota_ok").run(_request(tmp_path)))
    assert "usage limit" in result.final_message


def test_an_ordinary_crash_is_still_bad_output(tmp_path: Path) -> None:
    with pytest.raises(ProviderBadOutput):
        asyncio.run(_agent("fail").run(_request(tmp_path)))


def test_agy_quota_in_its_own_log_is_looked_at(tmp_path: Path) -> None:
    cfg = CliAgentProvider.model_validate({"type": "cli_agent", "command": "agy"})
    agent = ca.AgyAgent("agy", cfg, os.environ, executable="agy")
    req = _request(tmp_path)
    records = req.output_file.parent
    (records / ca.STDOUT_FILE).write_bytes(b"")
    (records / ca.STDERR_FILE).write_bytes(b"exit status 1\n")
    lines = [f"I1117 10:00:{i:02d} noise line {i}" for i in range(50)] + [AGY_LIMIT]
    (records / ca.AGENT_LOG).write_bytes("\n".join(lines).encode())
    hit = quota.detect(agent.quota_text(req, records / ca.STDOUT_FILE, records / ca.STDERR_FILE))
    assert hit is not None and hit.retry_after_s == 2 * 3600 + 30 * 60 + 15


# --- chat providers --------------------------------------------------------------------


def _req() -> CompletionRequest:
    return CompletionRequest(model="m", system="s", user="u", max_output_tokens=16)


def _openai(**fields: object) -> OpenAICompatChat:
    cfg = OpenAICompatProvider.model_validate(
        {"type": "openai_compat", "base_url": "https://router.test/api/v1",
         "api_key_env": "K", "models": [{"id": "m", "tier": 1}], **fields}
    )  # fmt: skip
    return OpenAICompatChat("router", cfg, {"K": "sk-fake-0000"})


def _ollama() -> OllamaChat:
    cfg = OllamaProvider.model_validate(
        {
            "type": "ollama",
            "base_url": "http://ollama.test:11434",
            "models": [{"id": "m", "tier": 1}],
        }
    )
    return OllamaChat("ollama", cfg)


@respx.mock
async def test_an_api_whose_quota_is_used_up_pauses_instead_of_retrying() -> None:
    body = {"error": {"message": "Rate limit exceeded: free-models-per-day", "code": 429}}
    respx.post("https://router.test/api/v1/chat/completions").mock(
        return_value=httpx.Response(429, json=body)
    )
    with pytest.raises(ProviderQuotaExhausted) as exc_info:
        await _openai(quota_pause_s=7200).complete(_req())
    assert exc_info.value.pause_s == 7200


@respx.mock
async def test_an_api_quota_with_retry_after_pauses_that_long() -> None:
    body = {"error": {"message": "You exceeded your current quota", "type": "insufficient_quota"}}
    respx.post("https://router.test/api/v1/chat/completions").mock(
        return_value=httpx.Response(429, headers={"retry-after": "900"}, json=body)
    )
    with pytest.raises(ProviderQuotaExhausted) as exc_info:
        await _openai().complete(_req())
    assert exc_info.value.pause_s == 900


@respx.mock
async def test_an_ordinary_429_is_still_retried() -> None:
    respx.post("https://router.test/api/v1/chat/completions").mock(
        return_value=httpx.Response(429, headers={"retry-after": "3"}, json={"error": {}})
    )
    with pytest.raises(ProviderRateLimit):
        await _openai().complete(_req())


@respx.mock
async def test_ollama_cloud_usage_limit_is_quota() -> None:
    respx.post("http://ollama.test:11434/api/chat").mock(
        return_value=httpx.Response(429, json={"error": "you've reached your hourly usage limit"})
    )
    with pytest.raises(ProviderQuotaExhausted):
        await _ollama().complete(_req())


# --- notifications ---------------------------------------------------------------------


def test_the_notification_names_quota_paused_providers_and_nothing_else() -> None:
    from orkestra.i18n import t
    from orkestra.notify import notify

    now = db.local_now()
    paused = [health.Health("agy", 1, now + timedelta(hours=1), "secret detail", "quota")]
    message = notify.with_quota("3 finished, 0 failed", paused)
    lines = message.split("\n")
    until = health.until_text(now + timedelta(hours=1), now)
    assert lines == ["3 finished, 0 failed", t("notify.quota", providers=f"agy ({until})")]
    assert "secret detail" not in message
    assert notify.with_quota("3 finished, 0 failed", []) == "3 finished, 0 failed"
