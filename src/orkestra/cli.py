"""Command line interface: argument parsing and calls into services only (Mimari §2)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from collections.abc import Sequence
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from orkestra import __version__, doctor, envelope, i18n
from orkestra.cache import responses
from orkestra.chief import status
from orkestra.config import loader
from orkestra.config.schema import Config, Provider
from orkestra.errors import ExitCode, OrkestraError, UsageError, exit_code_for
from orkestra.handoff import brief as handoff_brief
from orkestra.handoff import check as handoff_check_service
from orkestra.handoff import launch as handoff_launch
from orkestra.handoff import model as handoff_model
from orkestra.handoff import store as handoff_store
from orkestra.i18n import t
from orkestra.providers import registry
from orkestra.routing.router import Route, describe_candidates
from orkestra.security.redact import Redactor, config_for_display, configured_secrets
from orkestra.state import consent, db, stats
from orkestra.tasks import batch, runner, spec, templates
from orkestra.workspace import service


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
    code = i18n.normalize_language(value)  # "TR", "tr_TR" … like ORKESTRA_LANG
    if code is None:
        raise typer.BadParameter(
            t(
                "cli.error.unsupported_language",
                lang=value,
                choices=", ".join(i18n.SUPPORTED_LANGUAGES),
            )
        )
    i18n.set_language(code)
    return code


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
                + (t("route.dry.edit_format", format=c.edit_format) if c.edit_format else "")
            )
    else:
        lines.append(t("route.dry.none"))
    if plan.eliminated:
        lines.append(t("route.dry.eliminated"))
        lines.extend(f"  - {e.reason}" for e in plan.eliminated)
    return "\n".join(lines)


def _patch_redactor(config_path: Path | None) -> Redactor:
    """Masks configured key values and key patterns in a worker's patch.

    ``password = …`` lines are code, as in the runner's worker output (D-041); a broken
    config must not block ``show`` or ``apply``.
    """
    try:
        config = loader.load_config(config_path).config
    except OrkestraError:
        return Redactor(passwords=False)
    return Redactor(configured_secrets(config), passwords=False)


def _execute(
    task: spec.TaskSpec,
    config: Config,
    options: runner.RunOptions,
    *,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Shared by ``ask`` and ``run``: plan or run the task and print the result."""
    if dry_run:
        plan = asyncio.run(runner.plan_task(task, config, options))
        for warning in plan.warnings:
            typer.echo(warning, err=True)
        if as_json:
            _echo_json(_route_json(plan.route))
        else:
            typer.echo(_route_text(plan.route))
        if plan.exit_code:
            raise typer.Exit(plan.exit_code)
        return
    outcome = asyncio.run(runner.run_task(task, config, options))
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


def _no_cache_option() -> Any:
    return typer.Option("--no-cache", help=t("cli.option.no_cache"))


def _run_batch(
    batch_spec: batch.BatchSpec,
    config: Config,
    options: runner.RunOptions,
    *,
    parallel: int | None = None,
    fail_fast: bool = False,
    estimate: bool = False,
    yes_cost: bool = False,
    as_json: bool = False,
) -> None:
    """Shared by ``batch`` and ``run --template``: plan, estimate or check the cost, run."""
    plan = batch.plan_batch(batch_spec, cwd=Path.cwd(), ignore_file=config.security.ignore_file)
    for warning in plan.warnings:
        typer.echo(warning, err=True)
    if estimate:
        costs = asyncio.run(batch.estimate_batch(batch_spec, config, options))
        if not as_json:
            for warning in costs.warnings:
                typer.echo(warning, err=True)
        typer.echo(envelope.to_json(costs) if as_json else envelope.estimate_summary(costs))
        if code := batch.estimate_exit_code(costs):
            raise typer.Exit(code)
        return
    if not yes_cost and batch.checks_cost(config):
        costs = asyncio.run(batch.estimate_batch(batch_spec, config, options, fetch_prices=True))
        if costs.needs_confirmation:
            _confirm_cost(costs, as_json=as_json)
    progress = None if as_json else (lambda item: typer.echo(envelope.batch_line(item), err=True))
    document, code = asyncio.run(
        batch.run_batch(
            batch_spec, plan, config, options,
            parallel=parallel or batch_spec.parallel or batch.DEFAULT_PARALLEL,
            fail_fast=fail_fast, on_done=progress,
        )
    )  # fmt: skip
    if not as_json:  # in --json they are in the document
        for warning in batch.run_warnings(document, plan):
            typer.echo(warning, err=True)
    typer.echo(envelope.to_json(document) if as_json else envelope.batch_summary(document))
    if code:
        raise typer.Exit(code)


def _template_json(item: templates.Template) -> dict[str, Any]:
    return {
        "name": item.name, "source": item.source, "description": item.description,
        "path": item.path or None, "overrides_builtin": item.overrides,
        "params": [{"name": p.name, "default": p.default, "required": p.default is None,
                    "description": p.description} for p in item.params],
        "task": dict(item.task),
    }  # fmt: skip


def _interactive() -> bool:
    """Whether the user can be asked a question (tests replace this)."""
    return sys.stdin.isatty()


def _confirm_cost(costs: envelope.BatchEstimate, *, as_json: bool) -> None:
    """A batch whose estimate is above ``estimate.confirm_above_usd`` (Mimari §19): ``--json``
    returns the estimate and needs ``--yes-cost``; a terminal is asked; anything else stops.
    Stopping is exit code 2 and nothing has run."""
    limit_usd = costs.confirm_above_usd or 0.0
    cost, limit = f"${costs.totals.cost_usd:.4f}", f"${limit_usd:.4f}"
    # Above the limit, or under it only because some paid models have no known price.
    suffix = "" if costs.totals.cost_usd > limit_usd else "_unknown"
    params = {"cost": cost, "limit": limit, "count": costs.totals.unpriced_remote}
    stop = t(f"batch.estimate.needs_yes_cost{suffix}", **params)
    if as_json:
        typer.echo(envelope.to_json(costs))
        typer.echo(stop, err=True)
        raise typer.Exit(int(ExitCode.USAGE))
    typer.echo(envelope.estimate_summary(costs))
    if not _interactive():
        typer.echo(stop, err=True)
        raise typer.Exit(int(ExitCode.USAGE))
    try:
        agreed = typer.confirm(t(f"batch.estimate.confirm{suffix}", **params), default=False)
    except (typer.Abort, EOFError):  # Windows reports NUL as a TTY; reading it hits EOF
        agreed = False
    if not agreed:
        typer.echo(t("batch.estimate.declined"), err=True)
        raise typer.Exit(int(ExitCode.USAGE))


def _stop_json(stop: service.Conflict | None) -> dict[str, Any] | None:
    if stop is None:
        return None
    return {"run_id": stop.run.run_id, "task_id": stop.run.task_id, "message": stop.message,
            "details": list(stop.details)}  # fmt: skip


def _echo_batch_applied(report: service.BatchApplied, *, as_json: bool) -> None:
    if as_json:
        _echo_json({
            "batch_id": report.batch_id,
            "applied": [
                {"run_id": run.run_id, "task_id": run.task_id, "repo": str(done.repo),
                 "files": list(done.files), "merged": list(done.merged)}
                for run, done in report.applied
            ],
            "skipped": [{"run_id": s.run.run_id, "task_id": s.run.task_id, "reason": s.reason}
                        for s in report.skipped],
            "conflict": _stop_json(report.conflict),
            "error": _stop_json(report.error),
            "not_tried": [{"run_id": r.run_id, "task_id": r.task_id} for r in report.not_tried],
        })  # fmt: skip
        return
    for run, done in report.applied:
        typer.echo(t("apply.batch.applied", run_id=run.run_id, task_id=run.task_id,
                     count=len(done.files)))  # fmt: skip
        if done.merged:
            typer.echo(t("apply.batch.merged", files=", ".join(done.merged)))
    for item in report.skipped:
        typer.echo(t("apply.batch.skipped", run_id=item.run.run_id, task_id=item.run.task_id,
                     reason=item.reason))  # fmt: skip
    stop = report.conflict or report.error
    if stop is not None:
        key = "apply.batch.conflict" if report.conflict is not None else "apply.batch.error"
        typer.echo(t(key, run_id=stop.run.run_id, task_id=stop.run.task_id,
                     message=stop.message), err=True)  # fmt: skip
        c = stop
        for line in c.details:
            typer.echo(f"  {line}", err=True)
        if report.not_tried:
            runs = ", ".join(f"{r.task_id} ({r.run_id})" for r in report.not_tried)
            typer.echo(t("apply.batch.not_tried", runs=runs), err=True)
    typer.echo(t("apply.batch.summary", batch_id=report.batch_id, applied=len(report.applied),
                 skipped=len(report.skipped)))  # fmt: skip


def _handoff_target(ctx: typer.Context) -> tuple[Config, Path]:
    loaded = loader.load_config(ctx.ensure_object(_State).config_path)
    return loaded.config, handoff_store.handoff_path(loaded.config, Path.cwd())


def _chief(flag: str | None, config: Config, *, required: bool) -> str:
    """``--chief`` > ``ORKESTRA_CHIEF``; ``update`` must know who is writing (Faz 10a)."""
    name = (flag or os.environ.get("ORKESTRA_CHIEF", "")).strip()
    if name:
        return name
    if required:
        raise UsageError(t("handoff.error.no_chief"))
    return config.defaults.chief


def build_app() -> typer.Typer:
    """Build the typer app. Help texts are translated here, so set the language first."""
    app = typer.Typer(name="orkestra", help=t("cli.help"), no_args_is_help=True)
    config_app = typer.Typer(name="config", help=t("cli.config.help"), no_args_is_help=True)
    app.add_typer(config_app)
    providers_app = typer.Typer(
        name="providers", help=t("cli.providers.help"), no_args_is_help=True
    )
    app.add_typer(providers_app)
    templates_app = typer.Typer(
        name="templates", help=t("cli.templates.help"), no_args_is_help=True
    )
    app.add_typer(templates_app)
    cache_app = typer.Typer(name="cache", help=t("cli.cache.help"), no_args_is_help=True)
    app.add_typer(cache_app)
    plan_app = typer.Typer(name="plan", help=t("cli.plan.help"), no_args_is_help=True)
    app.add_typer(plan_app)
    handoff_app = typer.Typer(name="handoff", help=t("cli.handoff.help"), no_args_is_help=True)
    app.add_typer(handoff_app)

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
            registry.enable_provider(conn, name, cfg, db.local_now())
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
        result = loader.init_config(target, force=force, project=project)
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
        data = config_for_display(loaded.config)
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
        no_cache: Annotated[bool, _no_cache_option()] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        task = spec.ask_task(
            prompt,
            provider=provider,
            model=model,
            tier=tier,
            local_only=local_only,
            context=tuple(context or ()),
            schema=schema,
        )
        options = runner.RunOptions(profile=profile, allow_secrets=allow_secrets, no_cache=no_cache)
        _execute(task, loaded.config, options, dry_run=dry_run, as_json=as_json)

    @app.command("run", help=t("cli.run.help"))
    def run_command(
        ctx: typer.Context,
        task_file: Annotated[
            Path | None, typer.Argument(metavar="TASK", help=t("cli.run.arg.task"))
        ] = None,
        template: Annotated[
            str | None,
            typer.Option("--template", metavar="NAME", help=t("cli.run.option.template")),
        ] = None,
        files: Annotated[
            list[str] | None,
            typer.Option("--files", metavar="GLOB", help=t("cli.run.option.files")),
        ] = None,
        param: Annotated[
            list[str] | None,
            typer.Option("--param", metavar="KEY=VALUE", help=t("cli.run.option.param")),
        ] = None,
        allow_secrets: Annotated[
            bool, typer.Option("--allow-secrets", help=t("cli.ask.option.allow_secrets"))
        ] = False,
        profile: Annotated[
            str | None,
            typer.Option("--profile", metavar="NAME", help=t("cli.ask.option.profile")),
        ] = None,
        dry_run: Annotated[
            bool, typer.Option("--dry-run", help=t("cli.ask.option.dry_run"))
        ] = False,
        yes_cost: Annotated[
            bool, typer.Option("--yes-cost", help=t("cli.batch.option.yes_cost"))
        ] = False,
        no_cache: Annotated[bool, _no_cache_option()] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        if (task_file is None) == (template is None):
            raise UsageError(t("run.error.target"))
        batch_only = files or param or yes_cost
        if (template is None and batch_only) or (template is not None and not files):
            raise UsageError(t("run.error.files"))
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        options = runner.RunOptions(profile=profile, allow_secrets=allow_secrets, no_cache=no_cache)
        if template is not None:
            cwd = Path.cwd()
            chosen = templates.find(template, cwd=cwd)
            if chosen.overrides:  # the repository's own commands may run: say so
                typer.echo(t("template.warning.overrides", name=chosen.name,
                             path=chosen.path), err=True)  # fmt: skip
            batch_spec = templates.expand(
                chosen, files or [],
                templates.parse_params(param or []), cwd=cwd,
                ignore_file=loaded.config.security.ignore_file,
            )  # fmt: skip
            if dry_run:  # the tasks it would run, as a batch file; nothing is sent
                document = templates.to_batch_document(batch_spec)
                if as_json:
                    _echo_json(document)
                else:
                    typer.echo(loader.dump_yaml(document), nl=False)
                return
            _run_batch(batch_spec, loaded.config, options, yes_cost=yes_cost, as_json=as_json)
            return
        assert task_file is not None
        task = spec.load_task(task_file)
        _execute(task, loaded.config, options, dry_run=dry_run, as_json=as_json)

    @app.command("batch", help=t("cli.batch.help"))
    def batch_command(
        ctx: typer.Context,
        batch_file: Annotated[Path, typer.Argument(metavar="FILE", help=t("cli.batch.arg.file"))],
        parallel: Annotated[
            int | None,
            typer.Option("--parallel", metavar="N", min=1, help=t("cli.batch.option.parallel")),
        ] = None,
        fail_fast: Annotated[
            bool, typer.Option("--fail-fast", help=t("cli.batch.option.fail_fast"))
        ] = False,
        allow_secrets: Annotated[
            bool, typer.Option("--allow-secrets", help=t("cli.ask.option.allow_secrets"))
        ] = False,
        profile: Annotated[
            str | None,
            typer.Option("--profile", metavar="NAME", help=t("cli.ask.option.profile")),
        ] = None,
        estimate: Annotated[
            bool, typer.Option("--estimate", help=t("cli.batch.option.estimate"))
        ] = False,
        yes_cost: Annotated[
            bool, typer.Option("--yes-cost", help=t("cli.batch.option.yes_cost"))
        ] = False,
        no_cache: Annotated[bool, _no_cache_option()] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        options = runner.RunOptions(profile=profile, allow_secrets=allow_secrets, no_cache=no_cache)
        _run_batch(
            batch.load_batch(batch_file), loaded.config, options, parallel=parallel,
            fail_fast=fail_fast, estimate=estimate, yes_cost=yes_cost, as_json=as_json,
        )  # fmt: skip

    @app.command("show", help=t("cli.show.help"))
    def show_command(
        ctx: typer.Context,
        run_id: Annotated[str, typer.Argument(metavar="RUN_ID", help=t("cli.show.arg.run_id"))],
        diff: Annotated[bool, typer.Option("--diff", help=t("cli.show.option.diff"))] = False,
        only_flagged: Annotated[
            bool, typer.Option("--only-flagged", help=t("cli.show.option.only_flagged"))
        ] = False,
        output: Annotated[bool, typer.Option("--output", help=t("cli.show.option.output"))] = False,
        log: Annotated[bool, typer.Option("--log", help=t("cli.show.option.log"))] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        chosen = [name for name, on in (("diff", diff), ("output", output), ("log", log)) if on]
        if only_flagged and (output or log):
            raise UsageError(t("show.error.one_part"))
        if len(chosen) > 1:
            raise UsageError(t("show.error.one_part"))
        part: service.Part = (
            "diff"
            if (diff or only_flagged)
            else "output"
            if output
            else "log"
            if log
            else "envelope"
        )
        redact = _patch_redactor(ctx.ensure_object(_State).config_path) if part == "diff" else str
        result = service.show(run_id, part, only_flagged=only_flagged, redact=redact)
        if part == "envelope":
            if as_json:
                _echo_json(result)
            else:
                typer.echo(envelope.stored_summary(result))
            return
        if part == "diff" and not result:
            msg = (
                t("show.no_flagged_lines") if only_flagged else t("show.no_changes", run_id=run_id)
            )
            typer.echo(msg, err=True)
            return
        typer.echo(result, nl=False)

    @app.command("apply", help=t("cli.apply.help"))
    def apply_command(
        ctx: typer.Context,
        run_id: Annotated[
            str | None, typer.Argument(metavar="RUN_ID", help=t("cli.show.arg.run_id"))
        ] = None,
        batch_id: Annotated[
            str | None,
            typer.Option("--batch", metavar="BATCH_ID", help=t("cli.apply.option.batch")),
        ] = None,
        only_ok: Annotated[
            bool, typer.Option("--only-ok", help=t("cli.apply.option.only_ok"))
        ] = False,
        force: Annotated[bool, typer.Option("--force", help=t("cli.apply.option.force"))] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        if (run_id is None) == (batch_id is None):
            raise UsageError(t("apply.error.target"))
        if only_ok and batch_id is None:
            raise UsageError(t("apply.error.only_ok"))
        redact = _patch_redactor(ctx.ensure_object(_State).config_path)
        if batch_id is not None:
            with closing(db.connect()) as conn:
                report = service.apply_batch(
                    conn, batch_id, only_ok=only_ok, redact=redact, force=force
                )
            _echo_batch_applied(report, as_json=as_json)
            if report.conflict is not None:
                raise typer.Exit(int(ExitCode.CONFLICT))
            if report.error is not None:
                raise typer.Exit(report.error_code)
            return
        assert run_id is not None
        with closing(db.connect()) as conn:
            done = service.apply_run(conn, run_id, redact=redact, force=force)
        if as_json:
            _echo_json(
                {"run_id": run_id, "applied": True, "repo": str(done.repo),
                 "files": list(done.files), "merged": list(done.merged)}
            )  # fmt: skip
            return
        typer.echo(t("apply.done", count=len(done.files), run_id=run_id, repo=done.repo))
        if done.merged:
            typer.echo(t("apply.merged", files=", ".join(done.merged)))

    @app.command("stats", help=t("cli.stats.help"))
    def stats_command(
        since: Annotated[
            str,
            typer.Option("--since", metavar="DURATION", help=t("cli.stats.option.since")),
        ] = stats.DEFAULT_SINCE,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        window = stats.parse_since(since)
        now = db.local_now()
        with closing(db.connect()) as conn:
            report = stats.collect(conn, since=now - window, now=now)
        if as_json:
            _echo_json(stats.to_dict(report))
        else:
            typer.echo(stats.render(report))

    @app.command("status", help=t("cli.status.help"))
    def status_command(
        ctx: typer.Context, as_json: Annotated[bool, _json_option()] = False
    ) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        with closing(db.connect()) as conn:
            report = status.collect(status.default_context(loaded.config, conn, db.local_now()))
        if as_json:
            # One line: ``status`` promises a compact view, and a chief or a script reads it.
            typer.echo(json.dumps({"sections": report.sections}))
        else:
            typer.echo(status.render(report))

    @handoff_app.command("init", help=t("cli.handoff.init.help"))
    def handoff_init(ctx: typer.Context, as_json: Annotated[bool, _json_option()] = False) -> None:
        config, path = _handoff_target(ctx)
        handoff_store.init_file(
            path,
            project=handoff_store.project_root(Path.cwd()).name,
            chief=_chief(None, config, required=False),
            at=db.local_now(),
            commit=handoff_brief.head_commit(Path.cwd()),
        )
        if as_json:
            _echo_json({"path": str(path)})
        else:
            typer.echo(t("handoff.init.created", path=path))

    @handoff_app.command("update", help=t("cli.handoff.update.help"))
    def handoff_update(
        ctx: typer.Context,
        section: Annotated[str, typer.Option("--section", help=t("cli.handoff.option.section"))],
        add: Annotated[str | None, typer.Option("--add", help=t("cli.handoff.option.add"))] = None,
        set_text: Annotated[
            str | None, typer.Option("--set", help=t("cli.handoff.option.set"))
        ] = None,
        chief: Annotated[
            str | None, typer.Option("--chief", help=t("cli.handoff.option.chief"))
        ] = None,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        config, path = _handoff_target(ctx)
        result = handoff_store.update(
            path,
            config=config,
            section=section,
            chief=_chief(chief, config, required=True),
            now=db.local_now(),
            add=add,
            set_text=set_text,
            commit=handoff_brief.head_commit(Path.cwd()),
        )
        updated = result.last_updated
        if as_json:
            _echo_json(
                {
                    "section": result.section,
                    "action": result.action,
                    "archived": result.archived,
                    "last_updated": {
                        "chief": updated.chief,
                        "at": updated.at.isoformat() if updated.at is not None else None,
                        "commit": updated.commit,
                    },
                }
            )
            return
        typer.echo(t("handoff.update.saved", path=path, section=result.section,
                     action=result.action))  # fmt: skip
        if result.archived:
            typer.echo(t("handoff.update.archived", count=result.archived))

    @handoff_app.command("check", help=t("cli.handoff.check.help"))
    def handoff_check(
        ctx: typer.Context,
        strict: Annotated[
            bool, typer.Option("--strict", help=t("cli.handoff.option.strict"))
        ] = False,
        warn_only: Annotated[
            bool, typer.Option("--warn-only", help=t("cli.handoff.option.warn_only"))
        ] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        config, path = _handoff_target(ctx)
        result = handoff_check_service.run(path, config, Path.cwd())
        if as_json:
            _echo_json(
                {"exists": result.exists, "stale": result.stale, "warnings": result.warnings}
            )
        elif result.warnings:
            for line in result.warnings:
                typer.echo(line)
        elif not warn_only:  # the pre-commit hook says nothing when there is nothing to say
            typer.echo(t("handoff.check.ok"))
        if warn_only:
            return
        if strict and (result.warnings or not result.exists):
            raise typer.Exit(code=int(ExitCode.TASK_FAILED))

    @handoff_app.command("show", help=t("cli.handoff.show.help"))
    def handoff_show(
        ctx: typer.Context,
        brief: Annotated[bool, typer.Option("--brief", help=t("cli.handoff.option.brief"))] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        config, path = _handoff_target(ctx)
        if not path.exists():
            raise UsageError(t("handoff.error.missing", path=path))
        if brief:
            with closing(db.connect()) as conn:
                result = handoff_brief.build(
                    config, conn, db.local_now(), path=path, cwd=Path.cwd()
                )
            if as_json:
                _echo_json({"brief": result.text, "lines": len(result.lines)})
            else:
                typer.echo(result.text)
            return
        text = handoff_store.read(path)
        if as_json:
            _echo_json(handoff_model.as_json(handoff_model.parse(text)))
        else:
            typer.echo(text, nl=False)

    @handoff_app.command("to", help=t("cli.handoff.to.help"))
    def handoff_to(
        ctx: typer.Context,
        chief: Annotated[str, typer.Argument(metavar="CHIEF", help=t("cli.handoff.arg.chief"))],
        print_only: Annotated[
            bool, typer.Option("--print-only", help=t("cli.handoff.option.print_only"))
        ] = False,
        allow_dirty: Annotated[
            bool, typer.Option("--allow-dirty", help=t("cli.handoff.option.allow_dirty"))
        ] = False,
    ) -> None:
        config, path = _handoff_target(ctx)

        def announce(mode: str, warnings: list[str]) -> None:
            for line in warnings:
                typer.echo(line, err=True)
            typer.echo(t("handoff.to.starting", chief=chief, mode=mode), err=True)

        with closing(db.connect()) as conn:
            result = handoff_launch.to(
                chief,
                config,
                conn,
                db.local_now(),
                path=path,
                cwd=Path.cwd(),
                from_chief=_chief(None, config, required=False),
                allow_dirty=allow_dirty,
                print_only=print_only,
                before_start=announce,
            )
        if print_only:
            typer.echo(result.brief)
            return
        if result.exit_code:
            raise typer.Exit(code=result.exit_code)

    @handoff_app.command("install-hook", help=t("cli.handoff.install_hook.help"))
    def handoff_install_hook() -> None:
        result = handoff_launch.install_hook(Path.cwd())
        if result.created:
            typer.echo(t("handoff.hook.created", path=result.path))
        elif result.updated:
            typer.echo(t("handoff.hook.updated", path=result.path))
        else:
            typer.echo(t("handoff.hook.exists", path=result.path))

    @templates_app.command("list", help=t("cli.templates.list.help"))
    def templates_list(as_json: Annotated[bool, _json_option()] = False) -> None:
        found = templates.available(Path.cwd())
        if as_json:
            _echo_json({"templates": [_template_json(item) for item in found.values()]})
            return
        for item in found.values():
            typer.echo(t("templates.line", name=item.name, source=item.source,
                         description=item.description))  # fmt: skip

    @templates_app.command("show", help=t("cli.templates.show.help"))
    def templates_show(
        name: Annotated[str, typer.Argument(metavar="NAME", help=t("cli.templates.arg.name"))],
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        item = templates.find(name, cwd=Path.cwd())
        if as_json:
            _echo_json(_template_json(item))
            return
        typer.echo(t("templates.header", name=item.name, source=item.source,
                     description=item.description))  # fmt: skip
        if item.overrides:
            typer.echo(t("template.warning.overrides", name=item.name, path=item.path))
        if item.params:
            params = ", ".join(
                t("templates.param_required", name=p.name) if p.default is None
                else t("templates.param", name=p.name, default=p.default or '""')
                for p in item.params
            )  # fmt: skip
            typer.echo(t("templates.params", params=params))
        typer.echo(loader.dump_yaml(dict(item.task)), nl=False)

    @cache_app.command("clear", help=t("cli.cache.clear.help"))
    def cache_clear(as_json: Annotated[bool, _json_option()] = False) -> None:
        from orkestra.chief import repomap

        removed = responses.clear() + repomap.clear_cache(repomap.project_root(Path.cwd()))
        if as_json:
            _echo_json({"removed": removed})
        else:
            typer.echo(t("cache.cleared", count=removed))

    @app.command("review", help=t("cli.review.help"))
    def review_command(
        ctx: typer.Context,
        run_id: Annotated[str, typer.Argument(metavar="RUN_ID", help=t("cli.review.arg.run_id"))],
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        from orkestra.chief import review

        report = asyncio.run(review.review_run(run_id, loaded.config))
        if as_json:
            _echo_json(report.model_dump(mode="json"))
            return
        typer.echo(t("review.summary", risk=report.risk, summary=report.summary))
        if report.flags:
            typer.echo(t("review.flags", count=len(report.flags)))
            for f in report.flags:
                typer.echo(
                    t(
                        "review.flag_line",
                        severity=f.severity,
                        file=f.file,
                        start=f.start_line,
                        end=f.end_line,
                        reason=f.reason,
                    )
                )

    @app.command("map", help=t("cli.map.help"))
    def map_command(
        ctx: typer.Context,
        paths: Annotated[
            list[Path] | None,
            typer.Argument(metavar="[PATHS...]", help=t("cli.map.arg.paths")),
        ] = None,
        max_files: Annotated[
            int | None,
            typer.Option("--max-files", min=1, help=t("cli.map.option.max_files")),
        ] = None,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        from orkestra.chief import repomap

        cwd = Path.cwd()

        def echo_progress(done: int, total: int, path: str) -> None:
            typer.echo(t("map.progress", done=done, total=total, path=path), err=True)

        progress = echo_progress if not as_json and sys.stderr.isatty() else None
        root = repomap.project_root(cwd)
        result = asyncio.run(
            repomap.generate_repomap(
                root, paths, loaded.config, max_files=max_files, cwd=cwd, on_progress=progress
            )
        )
        for w in result.warnings:
            typer.echo(w, err=True)
        out_path = repomap.save_map(root, result)

        if as_json:
            _echo_json(
                {
                    "files": [
                        {
                            "path": f.path,
                            "summary": f.summary,
                            "symbols": f.symbols,
                            "cached": f.cached,
                        }
                        for f in result.files
                    ],
                    "total_files": result.total_files,
                    "summarized_files": result.summarized_files,
                    "cached_files": result.cached_files,
                    "model_used": result.model_used,
                    "warnings": result.warnings,
                    "truncated": result.truncated,
                    "map_files": len(result.map_files),
                    "map_path": str(out_path),
                }
            )
            return

        typer.echo(t("map.generated", path=str(out_path), files=len(result.map_files)))

    @plan_app.command("expand", help=t("cli.plan.expand.help"))
    def plan_expand(
        ctx: typer.Context,
        draft: Annotated[
            Path, typer.Argument(metavar="DRAFT", help=t("cli.plan.expand.arg.draft"))
        ],
        output: Annotated[
            Path,
            typer.Option("-o", "--output", metavar="FILE", help=t("cli.plan.expand.option.output")),
        ],
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        from orkestra.chief import plan

        spec, warnings = asyncio.run(plan.expand_plan(draft, output, loaded.config))
        for w in warnings:
            typer.echo(w, err=True)

        if as_json:
            _echo_json(
                {
                    "output": str(output),
                    "tasks": [t.model_dump(mode="json", by_alias=True) for t in spec.tasks],
                    "warnings": warnings,
                }
            )
            return
        typer.echo(t("plan.expanded", path=str(output), tasks=len(spec.tasks)))

    @app.command("discard", help=t("cli.discard.help"))
    def discard_command(
        run_id: Annotated[str, typer.Argument(metavar="RUN_ID", help=t("cli.show.arg.run_id"))],
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        removed = service.discard_run(run_id)
        if as_json:
            _echo_json({"run_id": run_id, "discarded": removed})
            return
        typer.echo(t("discard.done" if removed else "discard.nothing", run_id=run_id))

    @app.command("gc", help=t("cli.gc.help"))
    def gc_command(
        older_than: Annotated[
            int,
            typer.Option("--older-than", min=0, metavar="DAYS", help=t("cli.gc.option.older_than")),
        ] = service.DEFAULT_KEEP.days,
        dry_run: Annotated[
            bool, typer.Option("--dry-run", help=t("cli.gc.option.dry_run"))
        ] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        with closing(db.connect()) as conn:
            report = service.gc(
                conn, db.local_now(), keep=timedelta(days=older_than), dry_run=dry_run
            )
        if as_json:
            _echo_json(
                {"dry_run": report.dry_run, "worktrees": [str(p) for p in report.worktrees],
                 "runs": list(report.runs), "reservations": report.reservations,
                 "failed": [str(p) for p, _ in report.failed]}
            )  # fmt: skip
            return
        for path in report.worktrees:
            typer.echo(t("gc.item.worktree", path=path))
        for path, reason in report.failed:
            typer.echo(t("gc.item.failed", path=path, reason=reason), err=True)
        for run in report.runs:
            typer.echo(t("gc.item.run", run_id=run))
        key = "gc.dry" if report.dry_run else "gc.summary"
        typer.echo(t(key, worktrees=len(report.worktrees), runs=len(report.runs),
                     reservations=report.reservations))  # fmt: skip

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


_GLOBAL_VALUE_OPTIONS = ("--lang", "--config")


def _find_option(args: Sequence[str], name: str) -> str | None:
    """Read a global option before typer parses (help texts depend on the language).

    Only the global options before the subcommand are scanned, so a subcommand's own
    arguments (e.g. a prompt text) can never switch the language or the config.
    """
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--" or not arg.startswith("-"):
            break  # end of options, or the subcommand
        if arg == name:
            return args[i + 1] if i + 1 < len(args) else None
        if arg.startswith(f"{name}="):
            return arg.split("=", 1)[1]
        i += 2 if arg in _GLOBAL_VALUE_OPTIONS else 1
    return None


def _find_lang_arg(args: Sequence[str]) -> str | None:
    return _find_option(args, "--lang")


def _wants_json(args: Sequence[str]) -> bool:
    return "--json" in (args[: args.index("--")] if "--" in args else args)


def _report_error(exc: OrkestraError, *, as_json: bool) -> None:
    message = exc.message or t("errors.no_message", type=type(exc).__name__)
    if as_json:
        _echo_json(
            {
                "error": {
                    "code": exit_code_for(exc),
                    "type": type(exc).__name__,
                    "message": message,
                    "details": list(exc.details),
                }
            }
        )
        return
    typer.echo(t("errors.prefix", message=message), err=True)
    for detail in exc.details:
        typer.echo(f"  - {detail}", err=True)


def _safe_streams() -> None:
    """Redirected output is UTF-8; no stream ever crashes on text it cannot encode.

    Redirected output on Windows defaults to the ANSI code page (e.g. cp1254), but whoever
    reads a pipe or a file (Claude Code, Git Bash, an editor) expects UTF-8, so Turkish
    letters arrived broken (D-049). An explicit ``PYTHONIOENCODING`` still wins. A legacy
    console keeps its code page. Characters a stream cannot encode (an emoji on a legacy
    console, a git path decoded with ``surrogateescape``) become ``?`` instead of raising
    ``UnicodeEncodeError`` after a successful run; the full text is always in ``output.md``.
    """
    chosen = bool(os.environ.get("PYTHONIOENCODING"))
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        try:
            to_utf8 = encoding != "utf8" and not chosen and not stream.isatty()
        except (ValueError, OSError):
            continue  # detached or closed: leave it
        with contextlib.suppress(ValueError, OSError):
            if to_utf8:
                reconfigure(encoding="utf-8", errors="replace")
            else:
                reconfigure(errors="replace")


def app(argv: Sequence[str] | None = None) -> None:
    """Console entry point (``orkestra``)."""
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = _wants_json(args)
    try:
        _safe_streams()
        config_flag = _find_option(args, "--config")
        i18n.init_language(
            cli=_find_lang_arg(args),
            config=loader.read_language(Path(config_flag) if config_flag else None),
        )
        build_app()(args=args, prog_name="orkestra")
    except OrkestraError as exc:
        _report_error(exc, as_json=as_json)
        raise SystemExit(exit_code_for(exc)) from None
    except Exception as exc:
        _report_internal(exc, as_json=as_json)
        raise SystemExit(int(ExitCode.INTERNAL)) from None


def _report_internal(exc: Exception, *, as_json: bool) -> None:
    """Never raises. ``--json`` still gets one JSON document on stdout (D-011)."""
    text = _internal_error_text(exc)
    typer.echo(text, err=True)
    if as_json:
        error = {"code": int(ExitCode.INTERNAL), "type": "InternalError", "message": text}
        _echo_json({"error": {**error, "details": []}})


def _internal_error_text(exc: Exception) -> str:
    """Never raises: the translation catalog itself may be what is broken."""
    detail = f"{type(exc).__name__}: {str(exc)[:300]}"
    try:
        return t("errors.internal", detail=detail)
    except Exception:
        return f"Unexpected internal error: {detail}"
