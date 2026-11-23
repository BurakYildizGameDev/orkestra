"""Team management service layer (Faz 11c-c, Mimari §19 & §22).

Handles patron (chief) selection and workers (providers) management:
add, remove, toggle, reorder, change tier, select model, and grant consent.
All modifications use ruamel round-trip through ``config.writer`` to preserve
user comments and formatting, with atomic writing and backups.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from orkestra.config import edits, loader, provider_entry, writer
from orkestra.config.schema import (
    PROVIDER_NAME,
    CliAgentProvider,
    Config,
    OllamaProvider,
    OpenAICompatProvider,
)
from orkestra.errors import UsageError
from orkestra.i18n import t
from orkestra.state import consent

ConsentDisplay = Literal["granted", "missing", "changed", "not_needed"]


@dataclass(frozen=True)
class ChiefSummary:
    name: str
    is_default: bool
    launch: tuple[str, ...]
    prompt_mode: str


@dataclass(frozen=True)
class WorkerSummary:
    name: str
    type: Literal["ollama", "openai_compat", "cli_agent"]
    enabled: bool
    local: bool
    tier: int
    models: tuple[str, ...]
    selected_model: str
    base_url: str | None
    api_key_env: str | None
    command: str | None
    consent_state: ConsentDisplay
    consent_description: tuple[str, ...]


@dataclass(frozen=True)
class TeamSummary:
    patron: str
    chiefs: tuple[ChiefSummary, ...]
    workers: tuple[WorkerSummary, ...]
    # The patron, then the chiefs in config order: ``chief.limits`` hands off to the first
    # chief that is not the current one.
    handoff_order: tuple[str, ...] = ()


def _worker_models(provider: Any) -> tuple[str, ...]:
    if isinstance(provider, (OllamaProvider, OpenAICompatProvider)):
        return tuple(m.id for m in provider.models)
    if isinstance(provider, CliAgentProvider) and provider.model:
        return (provider.model,)
    return ()


def _worker_tier(provider: Any) -> int:
    if isinstance(provider, (OllamaProvider, OpenAICompatProvider)):
        return provider.models[0].tier if provider.models else 2
    if isinstance(provider, CliAgentProvider):
        return provider.tier
    return 2


def _worker_selected_model(provider: Any) -> str:
    models = _worker_models(provider)
    return models[0] if models else ""


def _worker_consent(
    conn: sqlite3.Connection | None, name: str, provider: Any
) -> tuple[ConsentDisplay, tuple[str, ...]]:
    if conn is None:
        return "not_needed", ()
    desc = tuple(consent.describe(name, provider))
    state = consent.state(conn, name, provider)
    return state, desc


def _model_name(raw: str) -> str:
    """A model name from the interface: not empty, one line (B-15, D-141)."""
    name = raw.strip()
    if not name:
        raise UsageError(t("team.error.no_model"))
    if any(ord(c) < 32 for c in name):
        raise UsageError(t("team.error.invalid_model"))
    return name


def team_summary(config: Config, conn: sqlite3.Connection | None = None) -> TeamSummary:
    """Summarize patron, available chiefs, and worker providers."""
    chiefs = tuple(
        ChiefSummary(
            name=name,
            is_default=(name == config.defaults.chief),
            launch=tuple(c.launch),
            prompt_mode=c.prompt_mode,
        )
        for name, c in config.chiefs.items()
    )

    workers = []
    for name, p in config.providers.items():
        c_state, c_desc = _worker_consent(conn, name, p)
        workers.append(
            WorkerSummary(
                name=name,
                type=p.type,
                enabled=p.enabled,
                local=p.local,
                tier=_worker_tier(p),
                models=_worker_models(p),
                selected_model=_worker_selected_model(p),
                base_url=getattr(p, "base_url", None),
                api_key_env=getattr(p, "api_key_env", None),
                command=getattr(p, "command", None),
                consent_state=c_state,
                consent_description=c_desc,
            )
        )

    patron = config.defaults.chief
    return TeamSummary(
        patron=patron,
        chiefs=chiefs,
        workers=tuple(workers),
        handoff_order=(patron, *(name for name in config.chiefs if name != patron)),
    )


def set_patron(
    config_path: Path | None, chief_name: str, *, cwd: Path | None = None
) -> writer.SaveResult:
    """Set default chief (patron) in config, preserving comments."""
    loaded = loader.load_config(config_path, cwd)
    if chief_name not in loaded.config.chiefs:
        raise UsageError(t("team.error.unknown_chief", name=chief_name))
    return edits.set_value(("defaults", "chief"), chief_name, config_flag=config_path, cwd=cwd)


def toggle_worker(
    config_path: Path | None, name: str, enabled: bool, *, cwd: Path | None = None
) -> writer.SaveResult:
    """Enable or disable worker provider, preserving comments."""
    return edits.set_value(
        ("providers", name, "enabled"), enabled, config_flag=config_path, cwd=cwd
    )


def _worker_type(config_path: Path | None, name: str, cwd: Path | None) -> str:
    provider = loader.load_config(config_path, cwd).config.providers.get(name)
    if provider is None:
        raise UsageError(t("team.error.unknown_worker", name=name))
    return provider.type


def _target(
    config_path: Path | None, name: str, field: str, cwd: Path | None
) -> tuple[Path, Path | None]:
    """The file that defines ``providers.<name>.<field>`` (a project file that only turns the
    provider off has no models: writing there would change nothing)."""
    return edits.target_for(("providers", name, field), config_flag=config_path, cwd=cwd)


def set_worker_tier(
    config_path: Path | None, name: str, tier: int, *, cwd: Path | None = None
) -> writer.SaveResult:
    """Set provider tier (1, 2, or 3), updating models or provider definition."""
    if tier not in (1, 2, 3):
        raise UsageError(t("team.error.invalid_tier"))
    ptype = _worker_type(config_path, name, cwd)
    field = "tier" if ptype == "cli_agent" else "models"
    target, base = _target(config_path, name, field, cwd)
    doc = writer.load_document(target)
    entry = doc.get("providers", {}).get(name)
    if not isinstance(entry, CommentedMap):
        raise UsageError(t("team.error.unknown_worker", name=name))

    if ptype == "cli_agent":
        entry["tier"] = tier
    else:
        models = entry.get("models")
        if isinstance(models, list):
            for m in models:
                if isinstance(m, CommentedMap):
                    m["tier"] = tier

    return writer.save(target, doc, base=base)


def set_worker_model(
    config_path: Path | None, name: str, model_id: str, *, cwd: Path | None = None
) -> writer.SaveResult:
    """Set the primary model for a provider."""
    model_id = _model_name(model_id)
    ptype = _worker_type(config_path, name, cwd)
    field = "model" if ptype == "cli_agent" else "models"
    target, base = _target(config_path, name, field, cwd)
    doc = writer.load_document(target)
    entry = doc.get("providers", {}).get(name)
    if not isinstance(entry, CommentedMap):
        raise UsageError(t("team.error.unknown_worker", name=name))

    if ptype == "cli_agent":
        entry["model"] = model_id
    else:
        models = entry.get("models")
        if isinstance(models, list):
            # If model already in list, move to front; else create as front
            existing_idx = next(
                (
                    i
                    for i, m in enumerate(models)
                    if isinstance(m, CommentedMap) and m.get("id") == model_id
                ),
                None,
            )
            if existing_idx is not None:
                item = models.pop(existing_idx)
                models.insert(0, item)
            elif models and isinstance(models[0], CommentedMap):
                old_tier = models[0].get("tier", 2)
                new_m = CommentedMap({"id": model_id, "tier": old_tier})
                models.insert(0, new_m)
            else:
                entry["models"] = CommentedSeq([CommentedMap({"id": model_id, "tier": 2})])

    return writer.save(target, doc, base=base)


def reorder_workers(
    config_path: Path | None, order: Sequence[str], *, cwd: Path | None = None
) -> writer.SaveResult:
    """Reorder providers CommentedMap in config, preserving key comments."""
    sources, base = edits._sources(config_path, cwd)  # pyright: ignore[reportPrivateUsage]
    target = sources[0].path
    doc = writer.load_document(target)
    providers = doc.get("providers")
    if not isinstance(providers, CommentedMap):
        return writer.save(target, doc, base=base)

    new_providers = CommentedMap()
    for key in order:
        if key in providers:
            new_providers[key] = providers[key]
    for key in providers:
        if key not in new_providers:
            new_providers[key] = providers[key]

    doc["providers"] = new_providers
    return writer.save(target, doc, base=base)


def add_worker(
    config_path: Path | None,
    *,
    name: str,
    provider_type: str,
    model: str,
    tier: int = 2,
    base_url: str | None = None,
    api_key_env: str | None = None,
    command: str | None = None,
    no_key: bool = False,
    force: bool = False,
    cwd: Path | None = None,
) -> writer.SaveResult:
    """Add a new worker provider (ollama, openai_compat, or cli_agent) through ruamel."""
    name = name.strip()
    if not PROVIDER_NAME.match(name):
        raise UsageError(t("team.error.invalid_name", name=name))

    sources, base = edits._sources(config_path, cwd)  # pyright: ignore[reportPrivateUsage]
    target = sources[0].path
    model = _model_name(model)
    if tier not in (1, 2, 3):
        raise UsageError(t("team.error.invalid_tier"))

    if provider_type == "openai_compat":
        url = (base_url or "").strip()
        if not provider_entry.valid_base_url(url):
            raise UsageError(t("providers.error.base_url", value=url))
        if api_key_env is not None and not provider_entry.valid_key_env(api_key_env):
            raise UsageError(t("providers.error.key_env"))
        # Same as ``providers add``: no variable given → the suggested ``<NAME>_API_KEY``.
        api = provider_entry.from_flags(
            name, url, (model,), api_key_env=api_key_env, no_key=no_key, tier=tier
        )
        return provider_entry.add(target, api, force=force, base=base)

    # For ollama and cli_agent:
    doc = writer.load_document(target)
    providers = doc.get("providers")
    if not isinstance(providers, CommentedMap):
        providers = doc["providers"] = CommentedMap()

    if name in providers and not force:
        raise UsageError(t("team.error.name_taken", name=name))

    if provider_type == "ollama":
        url = (base_url or "http://localhost:11434").strip()
        if not provider_entry.valid_base_url(url):
            raise UsageError(t("providers.error.base_url", value=url))
        entry_data: dict[str, Any] = {
            "type": "ollama",
            "base_url": url,
            "local": True,
            "models": [{"id": model, "tier": tier}],
        }
    elif provider_type == "cli_agent":
        cmd = (command or name).strip()
        if not cmd:
            raise UsageError(t("team.error.command_required"))
        entry_data = {
            "type": "cli_agent",
            "command": cmd,
            "tier": tier,
            "sandbox": "workspace-write",
        }
        if model:
            entry_data["model"] = model
    else:
        raise UsageError(
            t(
                "config.validation.provider_type_unknown",
                tag=provider_type,
                expected="ollama, openai_compat, cli_agent",
            )
        )

    providers[name] = writer.to_yaml(entry_data)
    return writer.save(target, doc, base=base)


def remove_worker(
    config_path: Path | None,
    name: str,
    *,
    conn: sqlite3.Connection | None = None,
    cwd: Path | None = None,
) -> provider_entry.RemoveOutcome:
    """Remove a worker provider and revoke consent if completely removed."""
    sources, base = edits._sources(config_path, cwd)  # pyright: ignore[reportPrivateUsage]
    target = sources[0].path
    all_sources = [s.path for s in sources]
    return provider_entry.remove(target, name, base=base, sources=all_sources, conn=conn)


def grant_consent(conn: sqlite3.Connection, config: Config, name: str, now: datetime) -> None:
    """Grant consent for a provider in the state database."""
    if name not in config.providers:
        raise UsageError(t("team.error.unknown_worker", name=name))
    consent.grant(conn, name, config.providers[name], now)
