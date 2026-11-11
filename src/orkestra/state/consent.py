"""Explicit user consent per provider (Mimari §6.3).

Consent is stored with a hash of the settings that decide where data goes and what may run
(URL, key variable, headers, command, sandbox, model ids…). Changing one of them invalidates
it; operational settings such as ``enabled``, budget, timeouts or tiers do not (D-027).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from orkestra.config.schema import CliAgentProvider, OllamaProvider, Provider
from orkestra.i18n import t
from orkestra.state.db import transaction

ConsentState = Literal["granted", "missing", "changed"]


# Settings that decide where data goes and what may run. Changing any of them asks again;
# operational settings (enabled, budget, timeouts, concurrency, tiers, prices) do not.
CONSENT_FIELDS = frozenset(
    {
        "type", "base_url", "local", "api_key_env", "extra_headers",
        "command", "kind", "sandbox", "extra_args", "model",
    }
)  # fmt: skip


def settings_hash(config: Provider) -> str:
    data = config.model_dump(mode="json", include=set(CONSENT_FIELDS))
    models = getattr(config, "models", None)
    if models is not None:
        # Model ids matter: on a router each id can mean a different company receives the data.
        data["models"] = sorted({m.id for m in models})
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


def state(conn: sqlite3.Connection, name: str, config: Provider) -> ConsentState:
    row = conn.execute("SELECT settings_hash FROM consents WHERE provider = ?", (name,)).fetchone()
    if row is None:
        return "missing"
    return "granted" if row["settings_hash"] == settings_hash(config) else "changed"


def grant(conn: sqlite3.Connection, name: str, config: Provider, now: datetime) -> None:
    with transaction(conn):
        conn.execute(
            "INSERT INTO consents (provider, settings_hash, granted_at) VALUES (?, ?, ?) "
            "ON CONFLICT(provider) DO UPDATE SET settings_hash = excluded.settings_hash, "
            "granted_at = excluded.granted_at",
            (name, settings_hash(config), now.isoformat()),
        )


def describe(
    name: str,
    config: Provider,
    *,
    agy_settings: Path | None = None,
    agy_mcp_config: Path | None = None,
) -> list[str]:
    """What the user allows by enabling this provider, shown before asking.

    ``agy_settings``, ``agy_mcp_config``: agy's settings and MCP config files (default: the
    real ones in the home directory).
    """
    lines = [t("consent.describe.title", name=name, type=config.type)]
    if isinstance(config, CliAgentProvider):
        lines.append(t("consent.describe.command", command=config.command, sandbox=config.sandbox))
        lines.append(t("consent.describe.agent_warning"))
        if config.kind == "generic":
            lines.append(t("consent.describe.generic_no_sandbox"))
        if config.kind == "agy":
            from orkestra.providers import cli_agent

            gaps = cli_agent.agy_deny_gaps(agy_settings or cli_agent.AGY_SETTINGS)
            if gaps:
                lines.append(t("consent.describe.agy_deny", commands=", ".join(gaps)))
            mcp = agy_mcp_config or cli_agent.AGY_MCP_CONFIG
            if disabled := cli_agent.agy_disabled_mcp_servers(mcp):
                lines.append(t("consent.describe.agy_mcp", servers=", ".join(disabled)))
    else:
        key = "consent.describe.local" if config.local else "consent.describe.remote"
        lines.append(t(key, url=config.base_url))
        if not isinstance(config, OllamaProvider):
            if config.api_key_env:
                lines.append(t("consent.describe.key", var=config.api_key_env))
            else:
                lines.append(t("consent.describe.no_key"))
        models = ", ".join(f"{m.id} ({m.tier})" for m in config.models)
        lines.append(t("consent.describe.models", models=models or "-"))
    if config.experimental:
        lines.append(t("consent.describe.experimental"))
    limits = [
        f"{field}={value}"
        for field, value in config.budget.model_dump().items()
        if value is not None
    ]
    lines.append(
        t("consent.describe.budget", limits=", ".join(limits))
        if limits
        else t("consent.describe.no_budget")
    )
    return lines


def revoke(conn: sqlite3.Connection, name: str) -> bool:
    with transaction(conn):
        cursor = conn.execute("DELETE FROM consents WHERE provider = ?", (name,))
    return cursor.rowcount > 0
