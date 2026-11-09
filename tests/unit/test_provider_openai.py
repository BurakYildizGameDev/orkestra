from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from orkestra.config.schema import OpenAICompatProvider
from orkestra.errors import (
    ContextTooLong,
    ProviderAuthError,
    ProviderBadOutput,
    ProviderModelNotFound,
    ProviderRateLimit,
    ProviderTimeout,
    ProviderTransient,
    ProviderUnavailable,
)
from orkestra.providers.base import CompletionRequest
from orkestra.providers.openai_compat import OpenAICompatChat

BASE = "https://router.test/api/v1"
URL = f"{BASE}/chat/completions"
FAKE_KEY = "sk-or-v1-FAKEKEYVALUE1234567890abcdef"
ENV = {"ROUTER_KEY": FAKE_KEY}


def _chat(prices: dict[str, float] | None = None, **extra: Any) -> OpenAICompatChat:
    model: dict[str, Any] = {"id": "provider/model", "tier": 2}
    if prices:
        model["price_per_mtok"] = prices
    cfg = OpenAICompatProvider.model_validate(
        {
            "type": "openai_compat",
            "base_url": BASE,
            "api_key_env": "ROUTER_KEY",
            "models": [model],
            **extra,
        }
    )
    return OpenAICompatChat("router", cfg, ENV)


def _req(**kw: Any) -> CompletionRequest:
    return CompletionRequest(
        **{"model": "provider/model", "system": "sys", "user": "hi", "max_output_tokens": 64, **kw}
    )


def _completion(
    content: str | None = "answer", finish: str = "stop", usage: dict[str, Any] | None = None
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "provider/model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish,
                }
            ],
            "usage": usage
            if usage is not None
            else {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


@respx.mock
async def test_success_sends_key_and_reads_usage() -> None:
    route = respx.post(URL).mock(return_value=_completion())
    result = await _chat().complete(_req())
    assert result.text == "answer"
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 5
    assert result.usage.cost_usd is None  # no cost field, no prices
    request = route.calls.last.request
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    body = json.loads(request.content)
    assert body["max_tokens"] == 64
    assert "response_format" not in body


@respx.mock
async def test_openrouter_usage_cost_is_read() -> None:
    respx.post(URL).mock(
        return_value=_completion(
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0.0042}
        )
    )
    result = await _chat(prices={"input": 100.0, "output": 100.0}).complete(_req())
    assert result.usage.cost_usd == pytest.approx(0.0042)  # reported cost wins over prices


@respx.mock
async def test_unreported_cost_is_left_to_the_runner() -> None:
    """Prices may come from the config, the provider's list or history: the runner knows."""
    respx.post(URL).mock(return_value=_completion())
    result = await _chat(prices={"input": 1.0, "output": 2.0}).complete(_req())
    assert result.usage.cost_usd is None


@respx.mock
async def test_finish_reason_length() -> None:
    respx.post(URL).mock(return_value=_completion(finish="length"))
    result = await _chat().complete(_req())
    assert result.raw_finish_reason == "length"


@respx.mock
async def test_extra_headers_sent() -> None:
    route = respx.post(URL).mock(return_value=_completion())
    await _chat(extra_headers={"X-Title": "Orkestra"}).complete(_req())
    assert route.calls.last.request.headers["x-title"] == "Orkestra"


@respx.mock
async def test_401_is_auth_error_without_key() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            401, json={"error": {"message": f"Incorrect API key provided: {FAKE_KEY}"}}
        )
    )
    with pytest.raises(ProviderAuthError) as exc_info:
        await _chat().complete(_req())
    assert FAKE_KEY not in exc_info.value.message
    assert exc_info.value.__cause__ is None


@respx.mock
async def test_429_with_retry_after() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(429, headers={"retry-after": "12"}, json={"error": {}})
    )
    with pytest.raises(ProviderRateLimit) as exc_info:
        await _chat().complete(_req())
    assert exc_info.value.retry_after == 12.0


@respx.mock
async def test_500_is_transient() -> None:
    respx.post(URL).mock(return_value=httpx.Response(500, json={"error": {"message": "oops"}}))
    with pytest.raises(ProviderTransient):
        await _chat().complete(_req())


@respx.mock
async def test_context_error() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            400, json={"error": {"message": "This model's maximum context length is 8192"}}
        )
    )
    with pytest.raises(ContextTooLong):
        await _chat().complete(_req())


@respx.mock
async def test_bad_request_detail_is_scrubbed() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(400, json={"error": {"message": f"bad thing {FAKE_KEY}"}})
    )
    with pytest.raises(Exception) as exc_info:
        await _chat().complete(_req())
    assert FAKE_KEY not in str(exc_info.value)


@respx.mock
async def test_404_model_is_model_not_found() -> None:
    respx.post(URL).mock(return_value=httpx.Response(404, json={"error": {"message": "nope"}}))
    with pytest.raises(ProviderModelNotFound):
        await _chat().complete(_req())


@respx.mock
async def test_connection_error_is_unavailable() -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ProviderUnavailable):
        await _chat().complete(_req())


@respx.mock
async def test_empty_answer_is_bad_output() -> None:
    respx.post(URL).mock(return_value=_completion(content=None))
    with pytest.raises(ProviderBadOutput):
        await _chat().complete(_req())


async def test_missing_key_names_variable_only() -> None:
    cfg = _chat().config
    chat = OpenAICompatChat("router", cfg, environ={})
    with pytest.raises(ProviderUnavailable) as exc_info:
        await chat.complete(_req())
    assert "ROUTER_KEY" in exc_info.value.message


@respx.mock
async def test_json_mode_uses_response_format() -> None:
    route = respx.post(URL).mock(return_value=_completion('{"a": 1}'))
    await _chat().complete(_req(json_mode=True))
    assert json.loads(route.calls.last.request.content)["response_format"] == {
        "type": "json_object"
    }


@respx.mock
async def test_json_mode_falls_back_and_remembers() -> None:
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(400, json={"error": {"message": "response_format not supported"}}),
            _completion('{"a": 1}'),
            _completion('{"b": 2}'),
        ]
    )
    chat = _chat()
    first = await chat.complete(_req(json_mode=True))
    assert first.text == '{"a": 1}'
    bodies = [json.loads(call.request.content) for call in route.calls]
    assert "response_format" in bodies[0]
    assert "response_format" not in bodies[1]
    assert "JSON" in bodies[1]["messages"][0]["content"]
    await chat.complete(_req(json_mode=True))  # remembered: no json_object attempt
    assert "response_format" not in json.loads(route.calls.last.request.content)
    assert route.call_count == 3


@respx.mock
async def test_health_lists_models() -> None:
    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "provider/model", "object": "model", "created": 0, "owned_by": "x"}
                ],
            },
        )
    )
    report = await _chat().health()
    assert report.ok
    assert report.models == ("provider/model",)


@respx.mock
async def test_health_auth_failure() -> None:
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(401, json={"error": {}}))
    report = await _chat().health()
    assert not report.ok
    assert isinstance(report.error, ProviderAuthError)


# --- code review fixes (Faz 2, PR #3) ---------------------------------------------------


@respx.mock
async def test_key_crossing_the_cut_point_is_still_masked() -> None:
    message = "x" * 280 + FAKE_KEY + " tail"
    respx.post(URL).mock(return_value=httpx.Response(400, json={"error": {"message": message}}))
    with pytest.raises(Exception) as exc_info:
        await _chat().complete(_req())
    assert FAKE_KEY[:12] not in str(exc_info.value)


@respx.mock
async def test_max_completion_tokens_fallback_is_remembered() -> None:
    rejected = httpx.Response(
        400,
        json={
            "error": {
                "message": "Unsupported parameter: 'max_tokens' is not supported with this "
                "model. Use 'max_completion_tokens' instead."
            }
        },
    )
    route = respx.post(URL).mock(side_effect=[rejected, _completion('{"a": 1}'), _completion()])
    chat = _chat()
    await chat.complete(_req(json_mode=True))
    bodies = [json.loads(call.request.content) for call in route.calls]
    assert bodies[0]["max_tokens"] == 64
    assert "max_tokens" not in bodies[1] and bodies[1]["max_completion_tokens"] == 64
    assert bodies[1]["response_format"] == {"type": "json_object"}  # JSON mode not blamed
    await chat.complete(_req())
    assert "max_tokens" not in json.loads(route.calls.last.request.content)
    assert route.call_count == 3


@respx.mock
async def test_timeout_is_provider_timeout() -> None:
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderTimeout):
        await _chat().complete(_req())


@respx.mock
async def test_health_404_points_at_base_url() -> None:
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(404, json={"error": {}}))
    report = await _chat().health()
    assert not report.ok and report.error is not None
    assert "model ''" not in report.error.message
    assert BASE in report.error.message
