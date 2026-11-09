"""Router (Mimari §7): which (provider, model) pairs may run a task, and in what order.

``route()`` is a pure function of the task, the config, the profile and a ``Snapshot`` of
the state, so it can be tested without a database or network. ``take_snapshot()`` reads the
state. Every candidate that is left out gets a reason; ``--dry-run`` prints them.

Order: tier ascending → priority descending → remaining budget ratio descending →
provider and model name (deterministic). Adaptive scoring arrives in Faz 12.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from orkestra.config.schema import (
    CliAgentProvider,
    Config,
    ModelSpec,
    OpenAICompatProvider,
    Profile,
)
from orkestra.errors import ConfigError, ConsentRequired, NoProviderAvailable, UsageError
from orkestra.i18n import t
from orkestra.providers import pricing
from orkestra.providers.pricing import Price
from orkestra.providers.registry import ChatConfig
from orkestra.state import budget, consent, health

CONTEXT_FILL = 0.8  # the estimated prompt may use at most 80% of the context window

Privacy = Literal["normal", "local_only"]


@dataclass(frozen=True)
class TaskNeeds:
    """What the router needs to know about a task."""

    kind: Literal["ask", "edit"] = "ask"
    tier: int = 1
    privacy: Privacy = "normal"
    provider: str | None = None
    model: str | None = None
    prompt_chars: int = 0
    has_secrets: bool = False
    allow_secrets: bool = False


@dataclass(frozen=True)
class ProviderState:
    consent: consent.ConsentState = "missing"
    open_until: datetime | None = None
    last_error: str | None = None
    key_present: bool = True
    used: budget.Amount = field(default_factory=budget.Amount)


@dataclass(frozen=True)
class Snapshot:
    now: datetime
    providers: Mapping[str, ProviderState] = field(default_factory=dict)
    prices: Mapping[tuple[str, str], Price | None] = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    provider: str
    config: ChatConfig
    model: ModelSpec
    budget_ratio: float  # 0..1, lowest remaining share over the provider's limits
    price: Price | None

    @property
    def tier(self) -> int:
        return self.model.tier

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model.id}"


@dataclass(frozen=True)
class Elimination:
    provider: str
    model: str | None
    code: str  # stable, English (JSON)
    reason: str  # translated
    consent: bool = False

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}" if self.model else self.provider


@dataclass(frozen=True)
class Route:
    profile: str
    tier_range: tuple[int, int]
    prompt_tokens: int
    candidates: tuple[Candidate, ...]
    eliminated: tuple[Elimination, ...]

    def error(self) -> ConsentRequired | NoProviderAvailable:
        details = [e.reason for e in self.eliminated]
        if any(e.consent for e in self.eliminated):
            return ConsentRequired(t("select.consent_needed"), details=details)
        return NoProviderAvailable(t("select.none"), details=details)


def prompt_tokens(chars: int) -> int:
    return math.ceil(chars / budget.CHARS_PER_TOKEN)


def resolve_profile(config: Config, name: str | None) -> tuple[str, Profile]:
    chosen = name or config.defaults.profile
    if chosen not in config.profiles:
        raise UsageError(
            t("route.unknown_profile", name=chosen, available=", ".join(sorted(config.profiles)))
        )
    return chosen, config.profiles[chosen]


def _budget_ratio(limits: Any, used: budget.Amount) -> float:
    ratios = [
        max(getattr(limits, limit) - used.get(limit), 0) / getattr(limits, limit)
        for limit in budget.LIMITS
        if getattr(limits, limit)
    ]
    return min(ratios) if ratios else 1.0


def _models_for(name: str, cfg: ChatConfig, needs: TaskNeeds, low: int) -> list[ModelSpec]:
    if needs.model is None:
        return list(cfg.models)
    listed = [m for m in cfg.models if m.id == needs.model]
    if listed or needs.provider != name:
        return listed
    # Explicit provider + unlisted model: trust the user, place it on the lowest allowed tier.
    return [ModelSpec.model_validate({"id": needs.model, "tier": max(needs.tier, low)})]


def route(
    needs: TaskNeeds,
    config: Config,
    snapshot: Snapshot,
    *,
    profile: str | None = None,
    max_output_tokens: int | None = None,
) -> Route:
    """Ordered candidates and the reason for every left-out (provider, model)."""
    if not config.providers:
        raise ConfigError(t("select.no_providers"))
    if needs.provider is not None and needs.provider not in config.providers:
        raise UsageError(
            t("select.unknown_provider", name=needs.provider, available=", ".join(config.providers))
        )
    profile_name, prof = resolve_profile(config, profile)
    low, high = max(needs.tier, prof.min_tier), prof.max_tier
    tokens = prompt_tokens(needs.prompt_chars)
    names = [needs.provider] if needs.provider else list(config.providers)

    candidates: list[Candidate] = []
    eliminated: list[Elimination] = []

    def drop(
        name: str,
        model_id: str | None,
        code: str,
        key: str,
        /,
        needs_consent: bool = False,
        **params: Any,
    ) -> None:
        reason = t(key, name=name, **params)
        eliminated.append(Elimination(name, model_id, code, reason, needs_consent))

    for name in names:
        cfg = config.providers[name]
        state = snapshot.providers.get(name, ProviderState())
        # --- provider level -------------------------------------------------------------
        if isinstance(cfg, CliAgentProvider):
            drop(name, None, "agent_not_supported", "select.reason.agent")
            continue
        if not cfg.enabled:
            drop(name, None, "disabled", "select.reason.disabled")
            continue
        if cfg.experimental and "enabled" not in cfg.model_fields_set:
            drop(name, None, "experimental", "route.reason.experimental")
            continue
        if state.consent != "granted":
            key = (
                "select.reason.consent_changed"
                if state.consent == "changed"
                else "select.reason.consent"
            )
            drop(name, None, f"consent_{state.consent}", key, True)
            continue
        if isinstance(cfg, OpenAICompatProvider) and cfg.api_key_env and not state.key_present:
            drop(name, None, "key_missing", "select.reason.key_missing", var=cfg.api_key_env)
            continue
        if needs.privacy == "local_only" and not cfg.local:
            drop(name, None, "not_local", "route.reason.not_local")
            continue
        if needs.has_secrets and not cfg.local and not needs.allow_secrets:
            drop(name, None, "secrets_remote", "route.reason.secrets")
            continue
        if state.open_until is not None and snapshot.now < state.open_until:
            drop(
                name, None, "circuit_open", "select.reason.circuit_open",
                until=state.open_until.strftime("%H:%M"), error=state.last_error or "-",
            )  # fmt: skip
            continue
        models = _models_for(name, cfg, needs, low)
        if not models and needs.model is not None:
            drop(
                name, needs.model, "no_such_model", "select.reason.no_such_model", model=needs.model
            )
            continue
        # --- model level ----------------------------------------------------------------
        ratio = _budget_ratio(cfg.budget, state.used)
        for model in models:
            label = model.id
            if not low <= model.tier <= high:
                drop(
                    name, label, "tier_out_of_range", "route.reason.tier",
                    model=label, tier=model.tier, low=low, high=high, profile=profile_name,
                )  # fmt: skip
                continue
            if tokens > model.context_window * CONTEXT_FILL:
                drop(
                    name, label, "context_too_small", "route.reason.context",
                    model=label, tokens=tokens, window=model.context_window,
                )  # fmt: skip
                continue
            price = snapshot.prices.get((name, model.id))
            amount = budget.estimate(
                needs.prompt_chars,
                max_output_tokens or model.max_output_tokens or config.defaults.max_output_tokens,
                price,
            )
            limit = budget.exceeded(cfg.budget, state.used, amount)
            if limit is not None:
                drop(name, label, "budget", "route.reason.budget", model=label, limit=limit)
                continue
            candidates.append(Candidate(name, cfg, model, ratio, price))

    candidates.sort(
        key=lambda c: (c.tier, -c.model.priority, -c.budget_ratio, c.provider, c.model.id)
    )
    return Route(profile_name, (low, high), tokens, tuple(candidates), tuple(eliminated))


def take_snapshot(
    conn: sqlite3.Connection,
    config: Config,
    now: datetime,
    *,
    environ: Mapping[str, str] | None = None,
    price_cache: Mapping[str, Any] | None = None,
) -> Snapshot:
    env = os.environ if environ is None else environ
    states: dict[str, ProviderState] = {}
    prices: dict[tuple[str, str], Price | None] = {}
    for name, cfg in config.providers.items():
        h = health.get(conn, name)
        key_env = cfg.api_key_env if isinstance(cfg, OpenAICompatProvider) else None
        states[name] = ProviderState(
            consent=consent.state(conn, name, cfg),
            open_until=h.open_until,
            last_error=h.last_error,
            key_present=bool(env.get(key_env, "").strip()) if key_env else True,
            used=budget.used(conn, name, now),
        )
        if not isinstance(cfg, CliAgentProvider):
            for model in cfg.models:
                prices[(name, model.id)] = pricing.resolve(
                    name, cfg, model, conn=conn, cache=price_cache or {}
                )
    return Snapshot(now, states, prices)


def describe_candidates(candidates: Sequence[Candidate]) -> list[dict[str, Any]]:
    return [
        {
            "provider": c.provider,
            "model": c.model.id,
            "tier": c.tier,
            "context_window": c.model.context_window,
            "priority": c.model.priority,
            "budget_ratio": round(c.budget_ratio, 4),
            "price_source": c.price.source if c.price else None,
            "local": c.config.local,
        }
        for c in candidates
    ]
