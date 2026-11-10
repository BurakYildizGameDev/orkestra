"""Config → provider objects, and the pre-router model choice for ``ask``.

Until the router (Faz 4): with no ``--provider``/``--model`` the first enabled chat provider
that has a model on the requested tier (default 1) wins, in config order.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from orkestra.config.schema import (
    CliAgentProvider,
    Config,
    ModelSpec,
    OllamaProvider,
    OpenAICompatProvider,
)
from orkestra.errors import ConfigError, ConsentRequired, NoProviderAvailable, UsageError
from orkestra.i18n import t
from orkestra.providers.base import ChatProvider
from orkestra.providers.ollama import OllamaChat
from orkestra.providers.openai_compat import OpenAICompatChat
from orkestra.state import budget, consent, health

ChatConfig = OllamaProvider | OpenAICompatProvider


@dataclass(frozen=True)
class ProviderRow:
    """One line of ``orkestra providers list``."""

    name: str
    type: str
    enabled: bool
    local: bool
    consent: consent.ConsentState
    health: health.Health
    used: budget.Amount
    limits: list[budget.LimitStatus]
    key_env: str | None
    key_present: bool | None


def provider_overview(
    config: Config,
    conn: sqlite3.Connection,
    now: datetime,
    environ: Mapping[str, str] | None = None,
) -> list[ProviderRow]:
    env = os.environ if environ is None else environ
    rows: list[ProviderRow] = []
    for name, cfg in config.providers.items():
        key_env = cfg.api_key_env if isinstance(cfg, OpenAICompatProvider) else None
        used, limits = budget.status(conn, name, cfg.budget, now)
        rows.append(
            ProviderRow(
                name=name,
                type=cfg.type,
                enabled=cfg.enabled,
                local=cfg.local,
                consent=consent.state(conn, name, cfg),
                health=health.get(conn, name),
                used=used,
                limits=limits,
                key_env=key_env,
                key_present=bool(env.get(key_env, "").strip()) if key_env else None,
            )
        )
    return rows


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


@dataclass(frozen=True)
class Rejection:
    reason: str
    consent: bool = False  # fixable with "orkestra providers enable"


# A state check (consent, circuit breaker, secrets, budget) for one candidate.
CandidateCheck = Callable[[str, ChatConfig, ModelSpec], Rejection | None]


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
    checks: Sequence[CandidateCheck] = (),
) -> ChatTarget:
    """First candidate that passes the static rules and every state check.

    Raises ``ConsentRequired`` (exit 4) when consent is what blocks a candidate, otherwise
    ``NoProviderAvailable`` (exit 3); both list the reason for every provider.
    """
    env = os.environ if environ is None else environ
    if not config.providers:
        raise ConfigError(t("select.no_providers"))
    if provider is not None and provider not in config.providers:
        raise UsageError(
            t("select.unknown_provider", name=provider, available=", ".join(config.providers))
        )
    names = [provider] if provider is not None else list(config.providers)
    reasons: list[str] = []
    needs_consent = False
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
        rejection = next((r for check in checks if (r := check(name, pcfg, spec))), None)
        if rejection is not None:
            reasons.append(rejection.reason)
            needs_consent = needs_consent or rejection.consent
            continue
        return ChatTarget(name, pcfg, create_chat_provider(name, pcfg, env), spec)
    if needs_consent:
        raise ConsentRequired(t("select.consent_needed"), details=reasons)
    raise NoProviderAvailable(t("select.none"), details=reasons)
