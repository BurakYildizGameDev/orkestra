"""``handoff`` and ``statusline`` (düzeltme-fable b, D-106)."""

from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
from typing import Annotated

import typer

from orkestra.chief import limits as chief_limits
from orkestra.commands.common import (
    _echo_json,
    _json_option,
    _State,
)
from orkestra.config import loader
from orkestra.config.schema import Config
from orkestra.console import read_stdin
from orkestra.errors import ExitCode, UsageError
from orkestra.handoff import brief as handoff_brief
from orkestra.handoff import check as handoff_check_service
from orkestra.handoff import launch as handoff_launch
from orkestra.handoff import model as handoff_model
from orkestra.handoff import store as handoff_store
from orkestra.i18n import t
from orkestra.state import db


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


def register(handoff_app: typer.Typer, statusline_app: typer.Typer) -> None:
    """``handoff init|update|check|show|to|install-hook`` and ``statusline [hook|config]``."""

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
        guide: Annotated[bool, typer.Option("--guide", help=t("cli.handoff.option.guide"))] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        if guide:
            if brief:
                raise UsageError(t("handoff.error.guide_and_brief"))
            lines = handoff_brief.guide_lines()  # needs no handoff file (Faz 13n)
            if as_json:
                _echo_json({"guide": "\n".join(lines), "lines": len(lines)})
            else:
                typer.echo("\n".join(lines))
            return
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

    @statusline_app.callback(invoke_without_command=True)
    def statusline_command(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is not None:
            return
        config_path = ctx.ensure_object(_State).config_path
        typer.echo(chief_limits.run_statusline(
            read_stdin(), load_config=lambda: loader.load_config(config_path).config,
            connect=db.connect, now=db.local_now(),
        ))  # fmt: skip

    @statusline_app.command("hook", help=t("cli.statusline.hook.help"))
    def statusline_hook(ctx: typer.Context) -> None:
        config_path = ctx.ensure_object(_State).config_path
        output = chief_limits.run_hook(
            read_stdin(), load_config=lambda: loader.load_config(config_path).config,
            now=db.local_now(),
        )  # fmt: skip
        if output is not None:
            typer.echo(output)

    @statusline_app.command("config", help=t("cli.statusline.config.help"))
    def statusline_config() -> None:
        typer.echo(t("statusline.config.where"), err=True)
        typer.echo(chief_limits.settings_snippet())

    @handoff_app.command("install-hook", help=t("cli.handoff.install_hook.help"))
    def handoff_install_hook() -> None:
        result = handoff_launch.install_hook(Path.cwd())
        if result.created:
            typer.echo(t("handoff.hook.created", path=result.path))
        elif result.updated:
            typer.echo(t("handoff.hook.updated", path=result.path))
        else:
            typer.echo(t("handoff.hook.exists", path=result.path))
