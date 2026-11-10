"""OpenAI-compatible HTTP APIs: OpenRouter, LM Studio, vLLM… (Mimari §5.2).

The SDK runs with ``max_retries=0``; retrying is Orkestra's job. The API key is read from the
environment variable named in the config and never appears in messages.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from orkestra.config.schema import OpenAICompatProvider
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
    retry_after,
)

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
        # Models that rejected max_tokens and want max_completion_tokens (reasoning models).
        self._completion_tokens: set[str] = set()

    # --- key -----------------------------------------------------------------------------

    def key_present(self) -> bool:
        return self.config.api_key_env is None or bool(read_api_key(self.config, self._environ))

    def _api_key(self) -> str:
        var = self.config.api_key_env
        if var is None:
            return NO_KEY
        value = read_api_key(self.config, self._environ)
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

    async def _create(self, client: AsyncOpenAI, req: CompletionRequest) -> ChatCompletion:
        json_object = req.json_mode and req.model not in self._no_json_object
        system = req.system
        if req.json_mode and not json_object:
            system = f"{system}\n\n{JSON_ONLY}"
        # OpenAI reasoning models (o-series, gpt-5) reject max_tokens; most other servers do
        # not know max_completion_tokens yet. Start with max_tokens, switch when told to.
        new_style = req.model in self._completion_tokens
        return await client.chat.completions.create(
            model=req.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": req.user},
            ],
            max_tokens=openai.omit if new_style else req.max_output_tokens,
            max_completion_tokens=req.max_output_tokens if new_style else openai.omit,
            response_format={"type": "json_object"} if json_object else openai.omit,
        )

    async def _send(self, client: AsyncOpenAI, req: CompletionRequest) -> ChatCompletion:
        """Send, adapting once per rejected optional parameter (remembered per model)."""
        while True:
            try:
                return await self._create(client, req)
            except openai.BadRequestError as exc:
                if _is_context_error(exc):
                    raise
                message = str(exc.message).lower()
                if "max_completion_tokens" in message and req.model not in self._completion_tokens:
                    self._completion_tokens.add(req.model)
                elif req.json_mode and req.model not in self._no_json_object:
                    self._no_json_object.add(req.model)
                else:
                    raise

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        api_key = self._api_key()
        try:
            async with self._client(api_key, req.timeout_s) as client:
                response = await self._send(client, req)
        except openai.OpenAIError as exc:
            # "from None": SDK messages may echo the key (e.g. "Incorrect API key: sk-...").
            raise self._map_error(exc, req.model, api_key, req.timeout_s) from None
        return self._result(response)

    def _result(self, response: ChatCompletion) -> CompletionResult:
        if not response.choices:
            raise ProviderBadOutput(t("provider.error.empty", provider=self.name))
        choice = response.choices[0]
        text = choice.message.content or ""
        if not text.strip():
            raise ProviderBadOutput(t("provider.error.empty", provider=self.name))
        usage = response.usage
        return CompletionResult(
            text=text,
            usage=Usage(
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
                cost_usd=_reported_cost(usage),
            ),
            raw_finish_reason=choice.finish_reason,
        )

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
                retry_after=retry_after(exc.response.headers),
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
            if not model:  # health check: GET /models itself is missing, i.e. a wrong base_url
                return ProviderUnavailable(
                    t("provider.error.endpoint_not_found", provider=name, url=self.config.base_url)
                )
            return ProviderModelNotFound(
                t("provider.error.model_not_found", provider=name, model=model)
            )
        if isinstance(exc, openai.APITimeoutError):  # subclass of APIConnectionError
            return ProviderTimeout(t("provider.error.timeout", provider=name, seconds=timeout_s))
        if isinstance(exc, openai.APIConnectionError):
            # No connection at all (offline, DNS, refused): one quick retry, then skip (D-029).
            return ProviderConnectionError(
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
    """Mask the key first, then shorten: cutting first could leave half a key behind."""
    if secret and secret != NO_KEY:
        text = text.replace(secret, "***")
    return text[:300]


def read_api_key(config: OpenAICompatProvider, environ: Mapping[str, str]) -> str | None:
    """The key from the variable named in the config (stripped); ``None`` if unset or empty."""
    if not config.api_key_env:
        return None
    return environ.get(config.api_key_env, "").strip() or None


def _reported_cost(usage: Any) -> float | None:
    """The charged cost if the provider reports it (OpenRouter: ``usage.cost``, USD).

    Otherwise ``None``; the runner prices the tokens with the model's resolved price.
    """
    if usage is None:
        return None
    reported = getattr(usage, "cost", None)
    if reported is None:
        reported = (getattr(usage, "model_extra", None) or {}).get("cost")
    return float(reported) if isinstance(reported, int | float) else None
