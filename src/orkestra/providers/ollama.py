"""Ollama adapter over the native ``/api/chat`` endpoint (Mimari §5.1).

The OpenAI-compatible endpoint ignores ``num_ctx``, so long prompts would be cut silently;
the native endpoint gets ``num_ctx`` on every request. Ollama itself also truncates a prompt
longer than ``num_ctx`` without an error, so a prompt whose estimate does not fit is refused
here with ``ContextTooLong`` before anything is sent (D-036).
"""

from __future__ import annotations

from typing import Any

import httpx

from orkestra.config.schema import OllamaProvider
from orkestra.errors import (
    ContextTooLong,
    ProviderAuthError,
    ProviderBadOutput,
    ProviderConnectionError,
    ProviderError,
    ProviderModelNotFound,
    ProviderRateLimit,
    ProviderTimeout,
    ProviderTransient,
    ProviderUnavailable,
)
from orkestra.i18n import t
from orkestra.providers.base import (
    CompletionRequest,
    CompletionResult,
    HealthReport,
    Usage,
    estimate_tokens,
    retry_after,
)

DEFAULT_CONTEXT_WINDOW = 8192
HEALTH_TIMEOUT_S = 5.0
OLLAMA_TIMEOUT_S = 600  # the first request loads the model into memory (cold start)


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
        window = self.context_window(req.model)
        if estimate_tokens(len(req.system) + len(req.user)) > window:
            raise ContextTooLong(t("provider.error.context", provider=self.name, model=req.model))
        url = f"{self._base}/api/chat"
        try:
            async with httpx.AsyncClient(timeout=req.timeout_s) as client:
                response = await client.post(url, json=self._payload(req))
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(
                t("provider.error.timeout", provider=self.name, seconds=req.timeout_s)
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderConnectionError(
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
            raise ProviderModelNotFound(
                t("provider.error.ollama_model_missing", provider=self.name, model=model)
            )
        if status == 400 and "context" in detail.lower():
            raise ContextTooLong(t("provider.error.context", provider=self.name, model=model))
        if status in (401, 403):
            raise ProviderAuthError(t("provider.error.auth", provider=self.name, status=status))
        if status == 429:
            raise ProviderRateLimit(
                t("provider.error.rate_limit", provider=self.name),
                retry_after=retry_after(response.headers),
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
        except httpx.TimeoutException:
            error: ProviderError = ProviderTimeout(
                t("provider.error.timeout", provider=self.name, seconds=HEALTH_TIMEOUT_S)
            )
            return HealthReport(ok=False, error=error)
        except httpx.HTTPError:
            error = ProviderConnectionError(
                t("provider.error.unreachable", provider=self.name, url=self._base)
            )
            return HealthReport(ok=False, error=error)
        if response.status_code == 404:  # no /api/tags: not Ollama, or a wrong base_url
            error = ProviderUnavailable(
                t("provider.error.endpoint_not_found", provider=self.name, url=self._base)
            )
            return HealthReport(ok=False, error=error)
        try:
            self._raise_for_status(response, model="")
            data = response.json()
        except ProviderError as exc:
            return HealthReport(ok=False, error=exc)
        except ValueError:
            error = ProviderBadOutput(t("provider.error.bad_json", provider=self.name))
            return HealthReport(ok=False, error=error)
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
