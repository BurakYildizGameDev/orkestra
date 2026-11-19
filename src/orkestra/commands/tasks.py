"""``ask``, ``run``, ``batch``, ``show`` and ``apply`` (düzeltme-fable b, D-106).

``cli._interactive`` is looked up at call time: tests replace it on ``cli``.
"""

from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
from typing import Annotated, Any

import typer

from orkestra import cli, envelope
from orkestra.chief import report as run_report
from orkestra.commands.common import (
    _echo_json,
    _json_option,
    _no_cache_option,
    _State,
)
from orkestra.config import loader
from orkestra.config.schema import Config
from orkestra.errors import ExitCode, OrkestraError, UsageError
from orkestra.i18n import t
from orkestra.notify import notify
from orkestra.providers import display
from orkestra.routing.router import Route, describe_candidates
from orkestra.security.redact import Redactor, configured_secrets
from orkestra.state import db
from orkestra.tasks import batch, runner, spec, templates
from orkestra.workspace import service


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
                + display.score_text(c.score)
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
    notify_on: bool = False,
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
    if notify_on:
        deliveries = notify.send_batch(
            config.notify, len(document.results), document.totals.ok,
            paused=batch.quota_pauses(document), low=batch.quota_low(config),
        )  # fmt: skip
        for line in notify.delivery_lines(deliveries, config.notify):
            typer.echo(line, err=True)
    if code:
        raise typer.Exit(code)


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
    if not cli._interactive():
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


def register(app: typer.Typer) -> None:
    """``ask``, ``run``, ``batch``, ``show``, ``apply``."""

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
        notify_on: Annotated[
            bool, typer.Option("--notify", help=t("cli.batch.option.notify"))
        ] = False,
        no_cache: Annotated[bool, _no_cache_option()] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        options = runner.RunOptions(profile=profile, allow_secrets=allow_secrets, no_cache=no_cache)
        _run_batch(
            batch.load_batch(batch_file), loaded.config, options, parallel=parallel,
            fail_fast=fail_fast, estimate=estimate, yes_cost=yes_cost, as_json=as_json,
            notify_on=notify_on,
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
        report: Annotated[bool, typer.Option("--report", help=t("cli.show.option.report"))] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        if report:
            if diff or only_flagged or output or log:
                raise UsageError(t("show.error.one_part"))
            found = run_report.build(run_id, service.run_dir_for(run_id))
            if as_json:
                _echo_json(found)
            else:
                typer.echo(run_report.render(found))
            return
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
        max_risk: Annotated[
            str | None,
            typer.Option("--max-risk", metavar="RISK", help=t("cli.apply.option.max_risk")),
        ] = None,
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
                    conn, batch_id, only_ok=only_ok, redact=redact, force=force,
                    max_risk=max_risk,
                )  # fmt: skip
            _echo_batch_applied(report, as_json=as_json)
            if report.conflict is not None:
                raise typer.Exit(int(ExitCode.CONFLICT))
            if report.error is not None:
                raise typer.Exit(report.error_code)
            return
        assert run_id is not None
        with closing(db.connect()) as conn:
            done = service.apply_run(conn, run_id, redact=redact, force=force,
                                     max_risk=max_risk)  # fmt: skip
        if as_json:
            _echo_json(
                {"run_id": run_id, "applied": True, "repo": str(done.repo),
                 "files": list(done.files), "merged": list(done.merged)}
            )  # fmt: skip
            return
        typer.echo(t("apply.done", count=len(done.files), run_id=run_id, repo=done.repo))
        if done.merged:
            typer.echo(t("apply.merged", files=", ".join(done.merged)))
