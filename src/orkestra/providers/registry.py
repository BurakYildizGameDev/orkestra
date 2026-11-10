"""Config → provider objects, and the provider overview for ``providers list`` / ``budget``.

Choosing which provider runs a task is the router's job (``routing/router.py``).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from orkestra.config.schema import (
    CliAgentProvider,
    Config,
    Defaults,
    OllamaProvider,
    OpenAICompatProvider,
    Provider,
)
from orkestra.providers.base import ChatProvider
from orkestra.providers.ollama import OLLAMA_TIMEOUT_S, OllamaChat
from orkestra.providers.openai_compat import OpenAICompatChat, read_api_key
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
                key_env=cfg.api_key_env if isinstance(cfg, OpenAICompatProvider) else None,
                key_present=key_present(cfg, env),
            )
        )
    return rows


def enable_provider(conn: sqlite3.Connection, name: str, config: Provider, now: datetime) -> None:
    """``providers enable``: record consent and give the provider a fresh start.

    Re-enabling is what a user does after fixing a key, so an open circuit (e.g. one hour
    after an authentication failure) is closed too.
    """
    consent.grant(conn, name, config, now)
    health.reset(conn, name)


AGENT_TIMEOUT_S = 1800  # code agents run tests and edit many files


def agent_timeout(config: CliAgentProvider, defaults: Defaults) -> int:
    """Seconds a code agent may run: its ``timeout_s``, else at least 30 minutes."""
    return config.timeout_s or max(defaults.timeout_s, AGENT_TIMEOUT_S)


def request_timeout(config: ChatConfig, defaults: Defaults) -> int:
    """Seconds to wait for one request: the provider's ``timeout_s``, else the default.

    Ollama gets at least 600 s: the first request loads the model into memory (Mimari §5.1).
    """
    if config.timeout_s:
        return config.timeout_s
    if isinstance(config, OllamaProvider):
        return max(defaults.timeout_s, OLLAMA_TIMEOUT_S)
    return defaults.timeout_s


def key_present(config: Provider, environ: Mapping[str, str]) -> bool | None:
    """Whether the API key variable is set; ``None`` when the provider needs no key."""
    if not isinstance(config, OpenAICompatProvider) or not config.api_key_env:
        return None
    return read_api_key(config, environ) is not None


def create_chat_provider(
    name: str, config: ChatConfig, environ: Mapping[str, str] | None = None
) -> ChatProvider:
    if isinstance(config, OllamaProvider):
        return OllamaChat(name, config)
    return OpenAICompatChat(name, config, environ)
