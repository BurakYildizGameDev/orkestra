from __future__ import annotations

import json

import httpx
import pytest
import respx

from orkestra.config.schema import OllamaProvider
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
from orkestra.providers.ollama import OllamaChat, has_model

BASE = "http://ollama.test:11434"


def _chat(**models: int) -> OllamaChat:
    cfg = OllamaProvider.model_validate(
        {
            "type": "ollama",
            "base_url": BASE + "/",
            "models": [{"id": "coder", "tier": 1, "context_window": 32768}],
        }
    )
    return OllamaChat("ollama", cfg)


def _req(**kw: object) -> CompletionRequest:
    data: dict[str, object] = {
        "model": "coder",
        "system": "sys",
        "user": "hello",
        "max_output_tokens": 256,
        **kw,
    }
    return CompletionRequest(**data)  # type: ignore[arg-type]


def _ok(content: str = "hi there", **extra: object) -> httpx.Response:
    body = {
        "model": "coder",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 12,
        "eval_count": 3,
        **extra,
    }
    return httpx.Response(200, json=body)


@respx.mock
async def test_success_and_usage() -> None:
    respx.post(f"{BASE}/api/chat").mock(return_value=_ok())
    result = await _chat().complete(_req())
    assert result.text == "hi there"
    assert result.usage.prompt_tokens == 12
    assert result.usage.completion_tokens == 3
    assert result.usage.cost_usd == 0.0
    assert result.raw_finish_reason == "stop"


@respx.mock
async def test_num_ctx_and_num_predict_sent_to_native_endpoint() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(return_value=_ok())
    await _chat().complete(_req())
    body = json.loads(route.calls.last.request.content)
    assert body["options"] == {"num_ctx": 32768, "num_predict": 256}
    assert body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    assert "format" not in body


@respx.mock
async def test_unknown_model_uses_default_context_window() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(return_value=_ok())
    await _chat().complete(_req(model="other"))
    assert json.loads(route.calls.last.request.content)["options"]["num_ctx"] == 8192


@respx.mock
async def test_json_mode_sets_format() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(return_value=_ok('{"a": 1}'))
    await _chat().complete(_req(json_mode=True))
    assert json.loads(route.calls.last.request.content)["format"] == "json"


@respx.mock
async def test_length_finish_reason_passed_through() -> None:
    respx.post(f"{BASE}/api/chat").mock(return_value=_ok(done_reason="length"))
    result = await _chat().complete(_req())
    assert result.raw_finish_reason == "length"


@respx.mock
async def test_missing_model_404() -> None:
    respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(404, json={"error": "model 'coder' not found"})
    )
    with pytest.raises(ProviderModelNotFound) as exc_info:
        await _chat().complete(_req())
    assert "ollama pull coder" in exc_info.value.message


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(500, json={"error": "boom"}), ProviderTransient),
        (httpx.Response(503, text="busy"), ProviderTransient),
        (httpx.Response(401, text="no"), ProviderAuthError),
        (httpx.Response(400, json={"error": "input exceeds context length"}), ContextTooLong),
        (httpx.Response(200, json={"message": {"content": "  "}}), ProviderBadOutput),
        (httpx.Response(200, text="not json"), ProviderBadOutput),
    ],
)
async def test_error_mapping(response: httpx.Response, error: type[Exception]) -> None:
    with respx.mock:
        respx.post(f"{BASE}/api/chat").mock(return_value=response)
        with pytest.raises(error):
            await _chat().complete(_req())


@respx.mock
async def test_rate_limit_retry_after() -> None:
    respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(429, headers={"retry-after": "7"})
    )
    with pytest.raises(ProviderRateLimit) as exc_info:
        await _chat().complete(_req())
    assert exc_info.value.retry_after == 7.0


@respx.mock
async def test_connection_refused_is_unavailable() -> None:
    respx.post(f"{BASE}/api/chat").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ProviderUnavailable):
        await _chat().complete(_req())


@respx.mock
async def test_timeout_is_transient() -> None:
    respx.post(f"{BASE}/api/chat").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderTimeout):
        await _chat().complete(_req())


@respx.mock
async def test_health_lists_models() -> None:
    respx.get(f"{BASE}/api/tags").mock(
        return_value=httpx.Response(
            200, json={"models": [{"name": "coder:latest"}, {"model": "llama3:8b"}]}
        )
    )
    report = await _chat().health()
    assert report.ok
    assert report.models == ("coder:latest", "llama3:8b")


@respx.mock
async def test_health_unreachable() -> None:
    respx.get(f"{BASE}/api/tags").mock(side_effect=httpx.ConnectError("refused"))
    report = await _chat().health()
    assert not report.ok
    assert isinstance(report.error, ProviderUnavailable)


def test_has_model_latest_alias() -> None:
    assert has_model(("coder:latest",), "coder")
    assert has_model(("coder:14b",), "coder:14b")
    assert not has_model(("coder:14b",), "coder")


# --- code review fixes (Faz 2, PR #3) ---------------------------------------------------


@respx.mock
async def test_prompt_larger_than_num_ctx_is_rejected_before_sending() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(return_value=_ok())
    with pytest.raises(ContextTooLong):
        await _chat().complete(_req(user="x" * 200_000))  # ~57k tokens > 32768
    assert not route.called


@respx.mock
async def test_health_404_points_at_the_url_not_a_model() -> None:
    respx.get(f"{BASE}/api/tags").mock(return_value=httpx.Response(404, text="not found"))
    report = await _chat().health()
    assert not report.ok and report.error is not None
    assert "ollama pull" not in report.error.message
    assert BASE in report.error.message


@respx.mock
async def test_health_non_json_is_not_reported_as_unreachable() -> None:
    respx.get(f"{BASE}/api/tags").mock(return_value=httpx.Response(200, text="<html>"))
    report = await _chat().health()
    assert isinstance(report.error, ProviderBadOutput)
