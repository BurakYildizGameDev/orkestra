"""Config → provider objects, and the pre-router model choice for ``ask``.

Until the router (Faz 4): with no ``--provider``/``--model`` the first enabled chat provider
that has a model on the requested tier (default 1) wins, in config order.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from orkestra.config.schema import (
    CliAgentProvider,
    Config,
    ModelSpec,
    OllamaProvider,
    OpenAICompatProvider,
)
from orkestra.errors import ConfigError, NoProviderAvailable, UsageError
from orkestra.i18n import t
from orkestra.providers.base import ChatProvider
from orkestra.providers.ollama import OllamaChat
from orkestra.providers.openai_compat import OpenAICompatChat

ChatConfig = OllamaProvider | OpenAICompatProvider


def create_chat_provider(
    name: str, config: ChatConfig, environ: Mapping[str, str] | None = None
) -> ChatProvider:
    if isinstance(config, OllamaProvider):
        return OllamaChat(name, config)
    return OpenAICompatChat(name, config, environ)


@dataclass(frozen=True)
class ChatTarget:
    name: str
    config: ChatConfig
    provider: ChatProvider
    model: ModelSpec


def _pick_model(
    config: ChatConfig, model: str | None, tier: int | None, *, forced: bool
) -> ModelSpec | None:
    if model is not None:
        spec = next((m for m in config.models if m.id == model), None)
        if spec is None and forced:
            # Explicit provider + model: trust the user even if the model is not listed.
            spec = ModelSpec.model_validate({"id": model, "tier": tier or 1})
        return spec
    if tier is not None:
        wanted = tier
    elif forced and config.models:
        wanted = min(m.tier for m in config.models)  # chosen provider: its lowest tier
    else:
        wanted = 1
    candidates = [m for m in config.models if m.tier == wanted]
    candidates.sort(key=lambda m: -m.priority)  # stable: config order within a priority
    return candidates[0] if candidates else None


def select_chat_target(
    config: Config,
    *,
    provider: str | None = None,
    model: str | None = None,
    tier: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> ChatTarget:
    env = os.environ if environ is None else environ
    if not config.providers:
        raise ConfigError(t("select.no_providers"))
    if provider is not None and provider not in config.providers:
        raise UsageError(
            t("select.unknown_provider", name=provider, available=", ".join(config.providers))
        )
    names = [provider] if provider is not None else list(config.providers)
    reasons: list[str] = []
    for name in names:
        pcfg = config.providers[name]
        if isinstance(pcfg, CliAgentProvider):
            reasons.append(t("select.reason.agent", name=name))
            continue
        if not pcfg.enabled:
            reasons.append(t("select.reason.disabled", name=name))
            continue
        key_var = pcfg.api_key_env if isinstance(pcfg, OpenAICompatProvider) else None
        if key_var and not env.get(key_var, "").strip():
            reasons.append(t("select.reason.key_missing", name=name, var=key_var))
            continue
        spec = _pick_model(pcfg, model, tier, forced=provider is not None)
        if spec is None:
            if model is not None:
                reasons.append(t("select.reason.no_such_model", name=name, model=model))
            else:
                reasons.append(t("select.reason.no_tier", name=name, tier=tier or 1))
            continue
        return ChatTarget(name, pcfg, create_chat_provider(name, pcfg, env), spec)
    raise NoProviderAvailable(t("select.none"), details=reasons)
