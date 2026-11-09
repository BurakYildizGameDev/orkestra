"""Real services. Skipped by default; run with ``uv run pytest -m live``.

Environment:
- ``ORKESTRA_LIVE_OLLAMA_MODEL``: installed Ollama model (default ``qwen2.5-coder:1.5b``)
- ``OPENROUTER_API_KEY`` and ``ORKESTRA_LIVE_OPENROUTER_MODEL`` for the OpenRouter test
"""

from __future__ import annotations

import os

import httpx
import pytest

from orkestra.config.schema import OllamaProvider, OpenAICompatProvider
from orkestra.providers.base import CompletionRequest
from orkestra.providers.ollama import OllamaChat
from orkestra.providers.openai_compat import OpenAICompatChat

pytestmark = pytest.mark.live


def _ollama_running() -> bool:
    try:
        return httpx.get("http://localhost:11434/api/tags", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


async def test_live_ollama_ask() -> None:
    if not _ollama_running():
        pytest.skip("Ollama is not running on localhost:11434")
    model = os.environ.get("ORKESTRA_LIVE_OLLAMA_MODEL", "qwen2.5-coder:1.5b")
    cfg = OllamaProvider.model_validate(
        {"type": "ollama", "models": [{"id": model, "tier": 1, "context_window": 4096}]}
    )
    result = await OllamaChat("ollama", cfg).complete(
        CompletionRequest(
            model=model,
            system="Answer briefly.",
            user="merhaba",
            max_output_tokens=32,
            timeout_s=600,
        )
    )
    assert result.text.strip()
    assert result.usage.prompt_tokens


async def test_live_openrouter_ask() -> None:
    model = os.environ.get("ORKESTRA_LIVE_OPENROUTER_MODEL")
    if not (os.environ.get("OPENROUTER_API_KEY") and model):
        pytest.skip("OPENROUTER_API_KEY / ORKESTRA_LIVE_OPENROUTER_MODEL not set")
    cfg = OpenAICompatProvider.model_validate(
        {
            "type": "openai_compat",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            "models": [{"id": model, "tier": 2}],
        }
    )
    result = await OpenAICompatChat("openrouter", cfg).complete(
        CompletionRequest(model=model, system="Answer briefly.", user="hi", max_output_tokens=16)
    )
    assert result.text.strip()
