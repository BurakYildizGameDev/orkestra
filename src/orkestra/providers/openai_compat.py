"""OpenAI-compatible HTTP APIs: OpenRouter, LM Studio, vLLM… (Mimari §5.2).

The SDK runs with ``max_retries=0``; retrying is Orkestra's job. The API key is read from the
environment variable named in the config and never appears in messages.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import httpx
import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from orkestra.config.schema import ModelSpec, OpenAICompatProvider
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

HEALTH_TIMEOUT_S = 10.0
NO_KEY = "unused"  # local servers without auth still need a non-empty key for the SDK
JSON_ONLY = "Respond with a single valid JSON value only. No prose, no code fences."


class OpenAICompatChat:
    def __init__(
        self, name: str, config: OpenAICompatProvider, environ: Mapping[str, str] | None = None
    ) -> None:
        self.name = name
        self.config = config
        self._environ = os.environ if environ is None else environ
        # Models that rejected response_format=json_object; asked for JSON in the prompt instead.
        self._no_json_object: set[str] = set()

    # --- key -----------------------------------------------------------------------------

    def key_present(self) -> bool:
        var = self.config.api_key_env
        return var is None or bool(self._environ.get(var, "").strip())

    def _api_key(self) -> str:
        var = self.config.api_key_env
        if var is None:
            return NO_KEY
        value = self._environ.get(var, "").strip()
        if not value:
            raise ProviderUnavailable(t("provider.error.key_missing", provider=self.name, var=var))
        return value

    def _client(self, api_key: str, timeout: float) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=self.config.base_url,
            api_key=api_key,
            max_retries=0,
            timeout=timeout,
            default_headers=self.config.extra_headers or None,
        )

    # --- completion ----------------------------------------------------------------------

    async def _create(
        self, client: AsyncOpenAI, req: CompletionRequest, *, json_object: bool
    ) -> ChatCompletion:
        system = req.system
        if req.json_mode and not json_object:
            system = f"{system}\n\n{JSON_ONLY}"
        return await client.chat.completions.create(
            model=req.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": req.user},
            ],
            max_tokens=req.max_output_tokens,
            response_format={"type": "json_object"} if json_object else openai.omit,
        )

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        api_key = self._api_key()
        json_object = req.json_mode and req.model not in self._no_json_object
        try:
            async with self._client(api_key, req.timeout_s) as client:
                try:
                    response = await self._create(client, req, json_object=json_object)
                except openai.BadRequestError as exc:
                    if not json_object or _is_context_error(exc):
                        raise
                    self._no_json_object.add(req.model)
                    response = await self._create(client, req, json_object=False)
        except openai.OpenAIError as exc:
            # "from None": SDK messages may echo the key (e.g. "Incorrect API key: sk-...").
            raise self._map_error(exc, req.model, api_key, req.timeout_s) from None
        return self._result(response, req.model)

    def _result(self, response: ChatCompletion, model: str) -> CompletionResult:
        if not response.choices:
            raise ProviderBadOutput(t("provider.error.empty", provider=self.name))
        choice = response.choices[0]
        text = choice.message.content or ""
        if not text.strip():
            raise ProviderBadOutput(t("provider.error.empty", provider=self.name))
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else None
        completion_tokens = usage.completion_tokens if usage else None
        return CompletionResult(
            text=text,
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=self._cost(usage, model, prompt_tokens, completion_tokens),
            ),
            raw_finish_reason=choice.finish_reason,
        )

    def _cost(
        self, usage: Any, model: str, prompt_tokens: int | None, completion_tokens: int | None
    ) -> float | None:
        # OpenRouter returns the charged cost (credits = USD) as an extra "usage.cost" field.
        reported = getattr(usage, "cost", None) if usage is not None else None
        if reported is None and usage is not None:
            reported = (getattr(usage, "model_extra", None) or {}).get("cost")
        if isinstance(reported, int | float):
            return float(reported)
        spec = self._spec(model)
        prices = spec.price_per_mtok if spec else None
        if not prices or prompt_tokens is None or completion_tokens is None:
            return None
        return (
            prompt_tokens * prices.get("input", 0.0) + completion_tokens * prices.get("output", 0.0)
        ) / 1_000_000

    def _spec(self, model: str) -> ModelSpec | None:
        return next((m for m in self.config.models if m.id == model), None)

    # --- errors --------------------------------------------------------------------------

    def _map_error(
        self, exc: openai.OpenAIError, model: str, api_key: str, timeout_s: float
    ) -> ProviderError:
        name = self.name
        if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
            return ProviderAuthError(
                t("provider.error.auth", provider=name, status=exc.status_code)
            )
        if isinstance(exc, openai.RateLimitError):
            return ProviderRateLimit(
                t("provider.error.rate_limit", provider=name),
                retry_after=_retry_after(exc.response.headers),
            )
        if isinstance(exc, openai.BadRequestError):
            if _is_context_error(exc):
                return ContextTooLong(t("provider.error.context", provider=name, model=model))
            return ProviderError(
                t(
                    "provider.error.http",
                    provider=name,
                    status=400,
                    detail=_scrub(exc.message, api_key),
                )
            )
        if isinstance(exc, openai.NotFoundError):
            return ProviderUnavailable(
                t("provider.error.model_not_found", provider=name, model=model)
            )
        if isinstance(exc, openai.APITimeoutError):  # subclass of APIConnectionError
            return ProviderTransient(t("provider.error.timeout", provider=name, seconds=timeout_s))
        if isinstance(exc, openai.APIConnectionError):
            return ProviderTransient(
                t("provider.error.unreachable", provider=name, url=self.config.base_url)
            )
        if isinstance(exc, openai.APIStatusError):
            detail = _scrub(exc.message, api_key)
            if exc.status_code >= 500:
                return ProviderTransient(
                    t("provider.error.server", provider=name, status=exc.status_code, detail=detail)
                )
            return ProviderError(
                t("provider.error.http", provider=name, status=exc.status_code, detail=detail)
            )
        return ProviderError(
            t("provider.error.http", provider=name, status="-", detail=type(exc).__name__)
        )

    # --- health --------------------------------------------------------------------------

    async def health(self) -> HealthReport:
        try:
            api_key = self._api_key()
        except ProviderError as exc:
            return HealthReport(ok=False, error=exc)
        try:
            async with self._client(api_key, HEALTH_TIMEOUT_S) as client:
                page = await client.models.list()
                ids = tuple(model.id for model in page.data)
        except openai.OpenAIError as exc:
            return HealthReport(ok=False, error=self._map_error(exc, "", api_key, HEALTH_TIMEOUT_S))
        return HealthReport(ok=True, models=ids)


def _is_context_error(exc: openai.APIStatusError) -> bool:
    return "context" in str(exc.message).lower()


def _scrub(text: str, secret: str) -> str:
    text = text[:300]
    return text.replace(secret, "***") if secret and secret != NO_KEY else text


def _retry_after(headers: httpx.Headers) -> float | None:
    value = headers.get("retry-after")
    if value is None and headers.get("retry-after-ms") is not None:
        try:
            return float(headers["retry-after-ms"]) / 1000
        except ValueError:
            return None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
