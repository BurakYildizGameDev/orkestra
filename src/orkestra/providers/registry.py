"""Config → provider objects, and the provider overview for ``providers list`` / ``budget``.

Choosing which provider runs a task is the router's job (``routing/router.py``).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from orkestra.config.schema import Config, OllamaProvider, OpenAICompatProvider
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
