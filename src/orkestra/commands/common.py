"""Helpers every command group shares (düzeltme-fable b, D-106)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from orkestra.config import loader
from orkestra.config.schema import Provider
from orkestra.errors import UsageError
from orkestra.i18n import t


@dataclass
class _State:
    config_path: Path | None = None


def _echo_json(data: Any) -> None:
    # ASCII escapes keep the output safe on non-UTF-8 Windows pipes.
    typer.echo(json.dumps(data, indent=2))


def _sources_json(sources: Sequence[loader.ConfigSource]) -> list[dict[str, str]]:
    return [{"kind": s.kind, "path": str(s.path)} for s in sources]


def _echo_sources(sources: Sequence[loader.ConfigSource], *, err: bool) -> None:
    if not sources:
        typer.echo(t("config.sources.none"), err=err)
        return
    typer.echo(t("config.sources"), err=err)
    for source in sources:
        typer.echo(f"  - {t(f'config.source.{source.kind}')}: {source.path}", err=err)


def _json_option() -> Any:
    # Called when typer resolves the annotations, i.e. after the language is set.
    return typer.Option("--json", help=t("cli.option.json"))


def _provider_config(ctx: typer.Context, name: str) -> Provider:
    loaded = loader.load_config(ctx.ensure_object(_State).config_path)
    if name not in loaded.config.providers:
        raise UsageError(
            t(
                "select.unknown_provider",
                name=name,
                available=", ".join(loaded.config.providers) or "-",
            )
        )
    return loaded.config.providers[name]


def _no_cache_option() -> Any:
    return typer.Option("--no-cache", help=t("cli.option.no_cache"))
