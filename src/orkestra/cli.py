"""Command line interface: argument parsing and calls into services only (Mimari §2)."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Any

import typer

from orkestra import __version__, doctor, envelope, i18n
from orkestra.config import loader
from orkestra.config.schema import Provider
from orkestra.errors import ExitCode, OrkestraError, UsageError, exit_code_for
from orkestra.i18n import t
from orkestra.providers import registry
from orkestra.routing.router import Route, describe_candidates
from orkestra.state import consent, db
from orkestra.tasks import runner


@dataclass
class _State:
    config_path: Path | None = None


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(t("cli.version", version=__version__))
        raise typer.Exit()


def _lang_callback(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in i18n.SUPPORTED_LANGUAGES:
        raise typer.BadParameter(
            t(
                "cli.error.unsupported_language",
                lang=value,
                choices=", ".join(i18n.SUPPORTED_LANGUAGES),
            )
        )
    i18n.set_language(value)
    return value


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
        },
        "budget": _limits_json(row),
        "api_key_env": row.key_env,
        "api_key_present": row.key_present,
    }


def _row_text(row: registry.ProviderRow) -> str:
    parts = [
        row.type,
        t("providers.enabled") if row.enabled else t("providers.disabled"),
        t(f"providers.consent.{row.consent}"),
    ]
    h = row.health
    if h.open_until is not None and h.is_open(db.local_now()):
        parts.append(t("providers.circuit_open", until=h.open_until.strftime("%H:%M")))
    elif h.consecutive_failures:
        parts.append(t("providers.failures", count=h.consecutive_failures))
    if row.key_env:
        key = "providers.key_present" if row.key_present else "providers.key_missing"
        parts.append(t(key, var=row.key_env))
    parts.extend(
        t("providers.budget_left", limit=s.limit, remaining=_num(s.remaining)) for s in row.limits
    )
    return f"{row.name}: " + " | ".join(parts)


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.4f}"


def _budget_text(row: registry.ProviderRow) -> str:
    if not row.limits:
        return t(
            "budget.unlimited", name=row.name, tokens=row.used.tokens, requests=row.used.requests
        )
    limits = ", ".join(
        t("budget.limit", limit=s.limit, used=_num(s.used), value=_num(s.value)) for s in row.limits
    )
    return f"{row.name}: {limits}"


def _route_json(plan: Route) -> dict[str, Any]:
    return {
        "profile": plan.profile,
        "tier_range": list(plan.tier_range),
        "prompt_tokens": plan.prompt_tokens,
        "candidates": describe_candidates(plan.candidates),
        "eliminated": [
            {"provider": e.provider, "model": e.model, "code": e.code, "reason": e.reason}
            for e in plan.eliminated
        ],
    }


def _route_text(plan: Route) -> str:
    low, high = plan.tier_range
    lines = [
        t("route.dry.header", profile=plan.profile, low=low, high=high, tokens=plan.prompt_tokens)
    ]
    if plan.candidates:
        lines.append(t("route.dry.candidates"))
        for index, c in enumerate(plan.candidates, start=1):
            lines.append(
                t(
                    "route.dry.candidate",
                    index=index,
                    label=c.label,
                    tier=c.tier,
                    window=c.model.context_window,
                    priority=c.model.priority,
                    budget=f"{c.budget_ratio:.0%}",
                    where=t("route.dry.local") if c.config.local else t("route.dry.remote"),
                )
            )
    else:
        lines.append(t("route.dry.none"))
    if plan.eliminated:
        lines.append(t("route.dry.eliminated"))
        lines.extend(f"  - {e.reason}" for e in plan.eliminated)
    return "\n".join(lines)


def build_app() -> typer.Typer:
    """Build the typer app. Help texts are translated here, so set the language first."""
    app = typer.Typer(name="orkestra", help=t("cli.help"), no_args_is_help=True)
    config_app = typer.Typer(name="config", help=t("cli.config.help"), no_args_is_help=True)
    app.add_typer(config_app)
    providers_app = typer.Typer(
        name="providers", help=t("cli.providers.help"), no_args_is_help=True
    )
    app.add_typer(providers_app)

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
            typer.echo(_row_text(row))

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
            consent.grant(conn, name, cfg, db.local_now())
        typer.echo(t("consent.granted", name=name))

    @providers_app.command("disable", help=t("cli.providers.disable.help"))
    def providers_disable(
        ctx: typer.Context, name: Annotated[str, typer.Argument(metavar="NAME")]
    ) -> None:
        _provider_config(ctx, name)
        with closing(db.connect()) as conn:
            removed = consent.revoke(conn, name)
        typer.echo(t("consent.revoked" if removed else "consent.not_granted", name=name))

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
        for row in rows:
            typer.echo(_budget_text(row))

    @app.callback()
    def main(
        ctx: typer.Context,
        version: Annotated[
            bool,
            typer.Option(
                "--version",
                help=t("cli.option.version"),
                callback=_version_callback,
                is_eager=True,
            ),
        ] = False,
        lang: Annotated[
            str | None,
            typer.Option(
                "--lang", metavar="LANG", help=t("cli.option.lang"), callback=_lang_callback
            ),
        ] = None,
        config: Annotated[
            Path | None,
            typer.Option("--config", metavar="PATH", help=t("cli.option.config")),
        ] = None,
    ) -> None:
        ctx.obj = _State(config_path=config)

    @app.command("init", help=t("cli.init.help"))
    def init_command(
        ctx: typer.Context,
        force: Annotated[bool, typer.Option("--force", help=t("cli.init.option.force"))] = False,
        project: Annotated[
            bool, typer.Option("--project", help=t("cli.init.option.project"))
        ] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        state = ctx.ensure_object(_State)
        target = loader.init_target(state.config_path, project=project)
        result = loader.init_config(target, force=force)
        if as_json:
            _echo_json(
                {
                    "path": str(result.path),
                    "written": result.written,
                    "backup": str(result.backup) if result.backup else None,
                    "gitignore": str(result.gitignore) if result.gitignore else None,
                }
            )
            return
        if not result.written:
            typer.echo(t("init.exists", path=result.path))
        elif result.backup:
            typer.echo(t("init.overwritten", path=result.path, backup=result.backup))
        else:
            typer.echo(t("init.created", path=result.path))
        if result.gitignore:
            typer.echo(t("init.gitignore", entry=loader.GITIGNORE_ENTRY, path=result.gitignore))
        if result.written:
            typer.echo(t("init.next"))

    @config_app.command("show", help=t("cli.config.show.help"))
    def config_show(ctx: typer.Context, as_json: Annotated[bool, _json_option()] = False) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        data = loaded.config.model_dump(mode="json")
        if as_json:
            _echo_json({"sources": _sources_json(loaded.sources), "config": data})
            return
        _echo_sources(loaded.sources, err=True)
        typer.echo(loader.dump_yaml(data), nl=False)

    @config_app.command("validate", help=t("cli.config.validate.help"))
    def config_validate(
        ctx: typer.Context, as_json: Annotated[bool, _json_option()] = False
    ) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        if as_json:
            _echo_json({"valid": True, "sources": _sources_json(loaded.sources)})
            return
        typer.echo(t("config.valid"))
        _echo_sources(loaded.sources, err=False)

    @app.command("ask", help=t("cli.ask.help"))
    def ask_command(
        ctx: typer.Context,
        prompt: Annotated[str, typer.Argument(metavar="PROMPT", help=t("cli.ask.arg.prompt"))],
        provider: Annotated[
            str | None, typer.Option("--provider", help=t("cli.ask.option.provider"))
        ] = None,
        model: Annotated[
            str | None, typer.Option("--model", help=t("cli.ask.option.model"))
        ] = None,
        tier: Annotated[
            int | None, typer.Option("--tier", min=1, max=3, help=t("cli.ask.option.tier"))
        ] = None,
        context: Annotated[
            list[Path] | None,
            typer.Option("--context", metavar="FILE", help=t("cli.ask.option.context")),
        ] = None,
        schema: Annotated[
            Path | None, typer.Option("--schema", metavar="FILE", help=t("cli.ask.option.schema"))
        ] = None,
        allow_secrets: Annotated[
            bool, typer.Option("--allow-secrets", help=t("cli.ask.option.allow_secrets"))
        ] = False,
        profile: Annotated[
            str | None,
            typer.Option("--profile", metavar="NAME", help=t("cli.ask.option.profile")),
        ] = None,
        local_only: Annotated[
            bool, typer.Option("--local-only", help=t("cli.ask.option.local_only"))
        ] = False,
        dry_run: Annotated[
            bool, typer.Option("--dry-run", help=t("cli.ask.option.dry_run"))
        ] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        request = runner.AskRequest(
            allow_secrets=allow_secrets,
            prompt=prompt,
            provider=provider,
            model=model,
            tier=tier,
            profile=profile,
            local_only=local_only,
            context=tuple(context or ()),
            schema=schema,
        )
        if dry_run:
            plan = asyncio.run(runner.plan_ask(request, loaded.config))
            for warning in plan.warnings:
                typer.echo(warning, err=True)
            if as_json:
                _echo_json(_route_json(plan.route))
            else:
                typer.echo(_route_text(plan.route))
            if plan.exit_code:
                raise typer.Exit(plan.exit_code)
            return
        outcome = asyncio.run(runner.run_ask(request, loaded.config))
        for warning in outcome.warnings:
            typer.echo(warning, err=True)
        if as_json:
            typer.echo(envelope.to_json(outcome.envelope))
        else:
            if outcome.output is not None:
                typer.echo(outcome.output)
            typer.echo(envelope.human_summary(outcome.envelope), err=True)
        if outcome.exit_code:
            raise typer.Exit(outcome.exit_code)

    @app.command("doctor", help=t("cli.doctor.help"))
    def doctor_command(
        ctx: typer.Context,
        warm: Annotated[bool, typer.Option("--warm", help=t("cli.doctor.option.warm"))] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        report = asyncio.run(
            doctor.run_doctor(config_flag=ctx.ensure_object(_State).config_path, warm=warm)
        )
        if as_json:
            _echo_json({"ok": report.ok, "checks": [asdict(c) for c in report.checks]})
        else:
            for check in report.checks:
                label = t(f"doctor.status.{check.status}")
                typer.echo(f"[{label}] {check.name}: {check.message}")
                for detail in check.data.get("details", []):
                    typer.echo(f"    - {detail}")
                if "hint" in check.data:
                    typer.echo(f"    {t('doctor.hint', command=check.data['hint'])}")
            typer.echo(t("doctor.summary.ok" if report.ok else "doctor.summary.fail"))
        if not report.ok:
            raise typer.Exit(int(ExitCode.TASK_FAILED))

    return app


def _find_option(args: Sequence[str], name: str) -> str | None:
    """Read a global option before typer parses (help texts depend on the language)."""
    for i, arg in enumerate(args):
        if arg == "--":
            break
        if arg == name:
            return args[i + 1] if i + 1 < len(args) else None
        if arg.startswith(f"{name}="):
            return arg.split("=", 1)[1]
    return None


def _find_lang_arg(args: Sequence[str]) -> str | None:
    return _find_option(args, "--lang")


def _wants_json(args: Sequence[str]) -> bool:
    return "--json" in (args[: args.index("--")] if "--" in args else args)


def _report_error(exc: OrkestraError, *, as_json: bool) -> None:
    if as_json:
        _echo_json(
            {
                "error": {
                    "code": exit_code_for(exc),
                    "type": type(exc).__name__,
                    "message": exc.message,
                    "details": list(exc.details),
                }
            }
        )
        return
    typer.echo(t("errors.prefix", message=exc.message), err=True)
    for detail in exc.details:
        typer.echo(f"  - {detail}", err=True)


def app(argv: Sequence[str] | None = None) -> None:
    """Console entry point (``orkestra``)."""
    args = list(sys.argv[1:] if argv is None else argv)
    config_flag = _find_option(args, "--config")
    i18n.init_language(
        cli=_find_lang_arg(args),
        config=loader.read_language(Path(config_flag) if config_flag else None),
    )
    try:
        build_app()(args=args, prog_name="orkestra")
    except OrkestraError as exc:
        _report_error(exc, as_json=_wants_json(args))
        raise SystemExit(exit_code_for(exc)) from None
    except Exception as exc:
        typer.echo(t("errors.internal", detail=f"{type(exc).__name__}: {exc}"), err=True)
        raise SystemExit(int(ExitCode.INTERNAL)) from None
