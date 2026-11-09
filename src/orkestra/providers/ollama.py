"""Ollama adapter over the native ``/api/chat`` endpoint (Mimari §5.1).

The OpenAI-compatible endpoint ignores ``num_ctx``, so long prompts would be cut silently;
the native endpoint gets ``num_ctx`` on every request.
"""

from __future__ import annotations

from typing import Any

import httpx

from orkestra.config.schema import OllamaProvider
from orkestra.errors import (
    ContextTooLong,
    ProviderAuthError,
    ProviderBadOutput,
    ProviderError,
    ProviderRateLimit,
    ProviderTransient,
    ProviderUnavailable,
)
from orkestra.i18n import t
from orkestra.providers.base import CompletionRequest, CompletionResult, HealthReport, Usage

DEFAULT_CONTEXT_WINDOW = 8192
HEALTH_TIMEOUT_S = 5.0


class OllamaChat:
    def __init__(self, name: str, config: OllamaProvider) -> None:
        self.name = name
        self.config = config
        self._base = config.base_url.rstrip("/")

    def context_window(self, model: str) -> int:
        for spec in self.config.models:
            if spec.id == model:
                return spec.context_window
        return DEFAULT_CONTEXT_WINDOW

    def _payload(self, req: CompletionRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": req.model,
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.user},
            ],
            "stream": False,
            "options": {
                "num_ctx": self.context_window(req.model),
                "num_predict": req.max_output_tokens,
            },
        }
        if req.json_mode:
            payload["format"] = "json"
        return payload

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        url = f"{self._base}/api/chat"
        try:
            async with httpx.AsyncClient(timeout=req.timeout_s) as client:
                response = await client.post(url, json=self._payload(req))
        except httpx.TimeoutException as exc:
            raise ProviderTransient(
                t("provider.error.timeout", provider=self.name, seconds=req.timeout_s)
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderUnavailable(
                t("provider.error.unreachable", provider=self.name, url=self._base)
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderTransient(
                t("provider.error.network", provider=self.name, detail=type(exc).__name__)
            ) from exc
        self._raise_for_status(response, req.model)
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderBadOutput(t("provider.error.bad_json", provider=self.name)) from exc
        message = data.get("message") if isinstance(data, dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ProviderBadOutput(t("provider.error.empty", provider=self.name))
        usage = Usage(
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
            cost_usd=0.0,
        )
        return CompletionResult(text=text, usage=usage, raw_finish_reason=data.get("done_reason"))

    def _raise_for_status(self, response: httpx.Response, model: str) -> None:
        status = response.status_code
        if status < 400:
            return
        detail = _error_text(response)
        if status == 404:
            raise ProviderUnavailable(
                t("provider.error.ollama_model_missing", provider=self.name, model=model)
            )
        if status == 400 and "context" in detail.lower():
            raise ContextTooLong(t("provider.error.context", provider=self.name, model=model))
        if status in (401, 403):
            raise ProviderAuthError(t("provider.error.auth", provider=self.name, status=status))
        if status == 429:
            raise ProviderRateLimit(
                t("provider.error.rate_limit", provider=self.name),
                retry_after=_retry_after(response.headers),
            )
        if status >= 500:
            raise ProviderTransient(
                t("provider.error.server", provider=self.name, status=status, detail=detail)
            )
        raise ProviderError(
            t("provider.error.http", provider=self.name, status=status, detail=detail)
        )

    async def health(self) -> HealthReport:
        try:
            async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_S) as client:
                response = await client.get(f"{self._base}/api/tags")
            self._raise_for_status(response, model="")
            data = response.json()
        except ProviderError as exc:
            return HealthReport(ok=False, error=exc)
        except httpx.TimeoutException:
            return HealthReport(
                ok=False,
                error=ProviderTransient(
                    t("provider.error.timeout", provider=self.name, seconds=HEALTH_TIMEOUT_S)
                ),
            )
        except (httpx.HTTPError, ValueError):
            return HealthReport(
                ok=False,
                error=ProviderUnavailable(
                    t("provider.error.unreachable", provider=self.name, url=self._base)
                ),
            )
        names: list[str] = []
        for entry in data.get("models", []) if isinstance(data, dict) else []:
            name = (entry.get("name") or entry.get("model")) if isinstance(entry, dict) else None
            if isinstance(name, str):
                names.append(name)
        return HealthReport(ok=True, models=tuple(names))


def has_model(available: tuple[str, ...], model: str) -> bool:
    """Ollama lists ``llama3`` as ``llama3:latest``."""
    return model in available or (":" not in model and f"{model}:latest" in available)


def _error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(data, dict) and isinstance(data.get("error"), str):
        return data["error"][:200]
    return response.text[:200]


def _retry_after(headers: httpx.Headers) -> float | None:
    value = headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
