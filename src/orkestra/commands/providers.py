"""``providers`` commands and ``budget`` (düzeltme-fable b, D-106)."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Sequence
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import typer

from orkestra import doctor
from orkestra.commands.common import (
    _echo_json,
    _json_option,
    _provider_config,
    _State,
)
from orkestra.config import loader, provider_entry
from orkestra.errors import ExitCode, UsageError
from orkestra.i18n import t
from orkestra.providers import display, registry
from orkestra.state import consent, db


def _limits_json(row: registry.ProviderRow) -> list[dict[str, Any]]:
    return [
        {"limit": s.limit, "value": s.value, "used": s.used, "remaining": s.remaining}
        for s in row.limits
    ]


def _row_json(row: registry.ProviderRow) -> dict[str, Any]:
    h = row.health
    return {
        "name": row.name,
        "type": row.type,
        "enabled": row.enabled,
        "local": row.local,
        "consent": row.consent,
        "health": {
            "open_until": h.open_until.isoformat() if h.open_until else None,
            "consecutive_failures": h.consecutive_failures,
            "last_error": h.last_error,
            "reason": h.reason,
        },
        "budget": _limits_json(row),
        "api_key_env": row.key_env,
        "api_key_present": row.key_present,
    }


def _entry_target(ctx: typer.Context, project: bool) -> tuple[Path, Path | None]:
    """The file ``providers add/remove`` writes, and the base config a project file needs."""
    config_path = ctx.ensure_object(_State).config_path
    target = loader.init_target(config_path, project=project)
    return target, loader.base_config_target(config_path)[0] if project else None


def _saved_entry(
    name: str,
    result: Any,  # writer.SaveResult
    *,
    check: bool,
    as_json: bool,
    extra: dict[str, Any] | None = None,
    notes: Sequence[str] = (),
) -> None:
    """What ``providers add`` and ``providers import`` print after saving (Faz 13o)."""
    cfg = result.config.providers[name]
    variable = getattr(cfg, "api_key_env", None)
    present = variable is not None and bool(os.environ.get(variable))
    command = f"orkestra providers enable {name}"
    checks = asyncio.run(doctor.check_one(name, result.config)) if check else None
    failed = checks is not None and any(c.status == "fail" for c in checks)
    if as_json:
        data: dict[str, Any] = {
            "name": name,
            "path": str(result.path),
            "backup": str(result.backup) if result.backup else None,
            "api_key_env": variable,
            "key_present": present,
            "models": [
                {"id": m.id, "tier": m.tier, "context_window": m.context_window}
                for m in getattr(cfg, "models", [])
            ],
            "next": command,
            "check": None
            if checks is None
            else {
                "ok": not failed,
                "checks": [{"status": c.status, "message": c.message} for c in checks],
            },
            **(extra or {}),
        }
        _echo_json(data)
    else:
        typer.echo(t("providers.add.saved", name=name, path=result.path))
        if result.backup is not None:
            typer.echo(t("wizard.backup", path=result.backup))
        for note in notes:
            typer.echo(note)
        if variable is None:
            typer.echo(t("providers.add.no_key"))
        elif present:
            typer.echo(t("providers.add.key_present", var=variable))
        else:
            typer.echo(t("providers.add.key_missing", var=variable))
        if checks is not None:
            for line in doctor.report_lines(doctor.DoctorReport(tuple(checks))):
                typer.echo(line)
        typer.echo(t("providers.add.next", command=command))
    if failed:
        raise typer.Exit(int(ExitCode.NO_PROVIDER))


def _opencode_row(found: provider_entry.OpencodeProvider) -> dict[str, Any]:
    return {
        "name": found.name,
        "supported": found.supported,
        "npm": found.npm,
        "base_url": found.base_url,
        "models": list(found.models),
        "key": {"env": found.key_env, "plain": found.plain_key, "file": found.key_file},
    }


def _opencode_line(found: provider_entry.OpencodeProvider) -> str:
    if found.key_env is not None:
        key = t("providers.import.key_env", var=found.key_env)
    elif found.key_file:
        key = t("providers.import.key_file")
    else:
        key = t("providers.import.key_plain" if found.plain_key else "providers.import.key_none")
    if not found.supported:
        return t("providers.import.row_unsupported", name=found.name, npm=found.npm or "-")
    return t("providers.import.row", name=found.name, url=found.base_url,
             models=", ".join(found.models), key=key)  # fmt: skip


# Option factories of the provider entry commands: module level, because typer resolves the
# (string) annotations in the module's namespace, after the language is set.
def _tier_option() -> Any:
    return typer.Option("--tier", min=1, max=3, help=t("cli.providers.add.tier"))


def _window_option() -> Any:
    return typer.Option("--context-window", min=1, help=t("cli.providers.add.window"))


def _project_option() -> Any:
    return typer.Option("--project", help=t("cli.providers.add.project"))


def _force_option() -> Any:
    return typer.Option("--force", help=t("cli.providers.add.force"))


def _check_option() -> Any:
    return typer.Option("--check", help=t("cli.providers.add.check"))


def _key_env_option() -> Any:
    return typer.Option("--api-key-env", metavar="VAR", help=t("cli.providers.add.key_env"))


def _add_provider_entry_commands(providers_app: typer.Typer) -> None:
    """``providers add``, ``providers import opencode``, ``providers remove`` (Faz 13o)."""

    @providers_app.command("add", help=t("cli.providers.add.help"))
    def providers_add(
        ctx: typer.Context,
        name: Annotated[str, typer.Argument(metavar="NAME")],
        base_url: Annotated[
            str, typer.Option("--base-url", metavar="URL", help=t("cli.providers.add.base_url"))
        ],
        model: Annotated[
            list[str] | None,
            typer.Option("--model", metavar="ID", help=t("cli.providers.add.model")),
        ] = None,
        api_key_env: Annotated[str | None, _key_env_option()] = None,
        no_key: Annotated[
            bool, typer.Option("--no-key", help=t("cli.providers.add.no_key"))
        ] = False,
        tier: Annotated[int, _tier_option()] = provider_entry.DEFAULT_TIER,
        context_window: Annotated[int | None, _window_option()] = None,
        project: Annotated[bool, _project_option()] = False,
        force: Annotated[bool, _force_option()] = False,
        check: Annotated[bool, _check_option()] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        api = provider_entry.from_flags(name, base_url, model or (), api_key_env=api_key_env,
                                        no_key=no_key, tier=tier,
                                        context_window=context_window)  # fmt: skip
        target, base = _entry_target(ctx, project)
        result = provider_entry.add(target, api, force=force, base=base)
        _saved_entry(name, result, check=check, as_json=as_json)

    @providers_app.command("import", help=t("cli.providers.import.help"))
    def providers_import(
        ctx: typer.Context,
        source: Annotated[
            str, typer.Argument(metavar="SOURCE", help=t("cli.providers.import.source"))
        ],
        path: Annotated[
            Path | None,
            typer.Option("--path", metavar="FILE", help=t("cli.providers.import.path")),
        ] = None,
        name: Annotated[
            str | None, typer.Option("--name", metavar="NAME", help=t("cli.providers.import.name"))
        ] = None,
        new_name: Annotated[
            str | None, typer.Option("--as", metavar="NAME", help=t("cli.providers.import.as"))
        ] = None,
        api_key_env: Annotated[str | None, _key_env_option()] = None,
        tier: Annotated[int, _tier_option()] = provider_entry.DEFAULT_TIER,
        context_window: Annotated[int | None, _window_option()] = None,
        project: Annotated[bool, _project_option()] = False,
        force: Annotated[bool, _force_option()] = False,
        check: Annotated[bool, _check_option()] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        if source != "opencode":
            raise UsageError(t("providers.import.bad_source", value=source))
        file = path or provider_entry.opencode_path(os.environ, home=Path.home())
        found = provider_entry.read_opencode(file, os.environ)
        chosen = provider_entry.pick_opencode(found, name)
        if chosen is None:
            if as_json:
                rows = [_opencode_row(entry) for entry in found]
                _echo_json({"source": str(file), "imported": None, "providers": rows})
                return
            typer.echo(t("providers.import.found", path=file))
            for entry in found:
                typer.echo(_opencode_line(entry))
            typer.echo(t("providers.import.choose"))
            return
        plan = provider_entry.plan_import(chosen, name=new_name, api_key_env=api_key_env,
                                          tier=tier, context_window=context_window)  # fmt: skip
        api = plan.provider
        target, base = _entry_target(ctx, project)
        result = provider_entry.add(target, api, force=force, base=base)
        notes = []
        if plan.key_note is not None:
            notes.append(t(f"providers.import.{plan.key_note}_key", var=api.api_key_env, path=file))
        extra = {"source": str(file), "imported": chosen.name, "key_note": plan.key_note}
        _saved_entry(api.name, result, check=check, as_json=as_json, extra=extra, notes=notes)

    @providers_app.command("remove", help=t("cli.providers.remove.help"))
    def providers_remove(
        ctx: typer.Context,
        name: Annotated[str, typer.Argument(metavar="NAME")],
        project: Annotated[bool, _project_option()] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        target, base = _entry_target(ctx, project)
        config_path = ctx.ensure_object(_State).config_path
        sources = [source.path for source in loader.find_sources(config_path)]
        with closing(db.connect()) as conn:
            outcome = provider_entry.remove(target, name, base=base, sources=sources, conn=conn)
        result, revoked = outcome.saved, outcome.consent_revoked
        if as_json:
            _echo_json({"name": name, "path": str(result.path),
                        "backup": str(result.backup) if result.backup else None,
                        "still_defined": outcome.still_defined,
                        "consent_revoked": revoked})  # fmt: skip
            return
        typer.echo(t("providers.remove.done", name=name, path=result.path))
        if result.backup is not None:
            typer.echo(t("wizard.backup", path=result.backup))
        if revoked:
            typer.echo(t("consent.revoked", name=name))


def register(app: typer.Typer, providers_app: typer.Typer) -> None:
    """``providers list|enable|disable|add|import|remove`` and ``budget``."""

    @providers_app.command("list", help=t("cli.providers.list.help"))
    def providers_list(
        ctx: typer.Context, as_json: Annotated[bool, _json_option()] = False
    ) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        with closing(db.connect()) as conn:
            rows = registry.provider_overview(loaded.config, conn, db.local_now())
        if as_json:
            _echo_json({"providers": [_row_json(row) for row in rows]})
            return
        if not rows:
            typer.echo(t("select.no_providers"))
        for row in rows:
            typer.echo(display.row_text(row))

    @providers_app.command("enable", help=t("cli.providers.enable.help"))
    def providers_enable(
        ctx: typer.Context,
        name: Annotated[str, typer.Argument(metavar="NAME")],
        yes: Annotated[bool, typer.Option("--yes", help=t("cli.providers.enable.yes"))] = False,
    ) -> None:
        cfg = _provider_config(ctx, name)
        for line in consent.describe(name, cfg):
            typer.echo(line)
        if not yes:
            if not sys.stdin.isatty():
                raise UsageError(t("consent.not_interactive", name=name))
            try:
                agreed = typer.confirm(t("consent.confirm"), default=False)
            except (typer.Abort, EOFError):
                # Windows reports NUL as a TTY; reading it hits EOF at once.
                raise UsageError(t("consent.not_interactive", name=name)) from None
            if not agreed:
                typer.echo(t("consent.declined", name=name))
                raise typer.Exit(int(ExitCode.CONSENT_REQUIRED))
        with closing(db.connect()) as conn:
            registry.enable_provider(conn, name, cfg, db.local_now())
        typer.echo(t("consent.granted", name=name))
        if not registry.usable(cfg) and cfg.enabled:  # experimental: consent is not enough
            typer.echo(t("providers.enable.experimental_hint", name=name))

    @providers_app.command("disable", help=t("cli.providers.disable.help"))
    def providers_disable(
        ctx: typer.Context, name: Annotated[str, typer.Argument(metavar="NAME")]
    ) -> None:
        _provider_config(ctx, name)
        with closing(db.connect()) as conn:
            removed = consent.revoke(conn, name)
        typer.echo(t("consent.revoked" if removed else "consent.not_granted", name=name))

    _add_provider_entry_commands(providers_app)

    @app.command("budget", help=t("cli.budget.help"))
    def budget_command(
        ctx: typer.Context, as_json: Annotated[bool, _json_option()] = False
    ) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        now = db.local_now()
        with closing(db.connect()) as conn:
            rows = registry.provider_overview(loaded.config, conn, now)
        if as_json:
            _echo_json(
                {
                    "day": now.date().isoformat(),
                    "providers": [
                        {"name": r.name, "used": asdict(r.used), "limits": _limits_json(r)}
                        for r in rows
                    ],
                }
            )
            return
        typer.echo(t("budget.title", day=now.date().isoformat()))
        if not rows:
            typer.echo(t("select.no_providers"))
        for row in rows:
            typer.echo(display.budget_text(row))
