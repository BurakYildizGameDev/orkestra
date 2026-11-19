"""``queue`` and ``notify`` (düzeltme-fable b, D-106)."""

from __future__ import annotations

import contextlib
from contextlib import closing
from pathlib import Path
from typing import Annotated

import typer

from orkestra.commands.common import (
    _echo_json,
    _json_option,
    _State,
)
from orkestra.config import loader
from orkestra.config.schema import Config
from orkestra.errors import ExitCode, OrkestraError, UsageError
from orkestra.i18n import t
from orkestra.notify import notify
from orkestra.queue import display as queue_display
from orkestra.queue import service as queue_service
from orkestra.queue import store as queue_store
from orkestra.routing.router import resolve_profile
from orkestra.state import db


def register(app: typer.Typer) -> None:
    """``queue add|list|remove|run`` and ``notify test`` (Faz 12a, Mimari §21)."""
    queue_app = typer.Typer(name="queue", help=t("cli.queue.help"), no_args_is_help=True)
    app.add_typer(queue_app)
    notify_app = typer.Typer(name="notify", help=t("cli.notify.help"), no_args_is_help=True)
    app.add_typer(notify_app)

    @queue_app.command("add", help=t("cli.queue.add.help"))
    def queue_add(
        ctx: typer.Context,
        file: Annotated[Path, typer.Argument(metavar="FILE", help=t("cli.queue.add.arg.file"))],
        profile: Annotated[
            str | None,
            typer.Option("--profile", metavar="NAME", help=t("cli.queue.add.option.profile")),
        ] = None,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        config = loader.load_config(ctx.ensure_object(_State).config_path).config
        if profile is not None:
            resolve_profile(config, profile)
        with closing(db.connect()) as conn:
            item = queue_store.add(conn, file, now=db.local_now(), profile=profile)
        if as_json:
            _echo_json(queue_display.item_json(item))
        else:
            typer.echo(queue_display.added_text(item, config))

    @queue_app.command("list", help=t("cli.queue.list.help"))
    def queue_list(ctx: typer.Context, as_json: Annotated[bool, _json_option()] = False) -> None:
        with closing(db.connect()) as conn:
            items = queue_store.items(conn)
        if as_json:
            _echo_json({"items": [queue_display.item_json(item) for item in items]})
            return
        config: Config | None = None
        with contextlib.suppress(OrkestraError):  # the list shows even with a broken config
            config = loader.load_config(ctx.ensure_object(_State).config_path).config
        for line in queue_display.list_lines(items, config):
            typer.echo(line)

    @queue_app.command("remove", help=t("cli.queue.remove.help"))
    def queue_remove(
        item_id: Annotated[
            int | None, typer.Argument(metavar="ID", help=t("cli.queue.remove.arg.id"))
        ] = None,
        finished: Annotated[
            bool, typer.Option("--finished", help=t("cli.queue.remove.option.finished"))
        ] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        if (item_id is None) == (not finished):
            raise UsageError(t("queue.error.remove_target"))
        with closing(db.connect()) as conn:
            if item_id is None:
                removed = queue_store.remove_finished(conn)
            else:
                item = queue_store.remove(conn, item_id)
        if item_id is None:
            if as_json:
                _echo_json({"removed": [queue_display.item_json(i) for i in removed]})
            else:
                typer.echo(t("queue.removed_finished", count=len(removed)))
            return
        if as_json:
            _echo_json(queue_display.item_json(item))
        else:
            typer.echo(t("queue.removed", id=item.id))

    @queue_app.command("run", help=t("cli.queue.run.help"))
    def queue_run(
        ctx: typer.Context,
        until: Annotated[
            str | None,
            typer.Option("--until", metavar="HH:MM", help=t("cli.queue.run.option.until")),
        ] = None,
        max_cost_usd: Annotated[
            float | None,
            typer.Option(
                "--max-cost-usd", metavar="USD", min=0.0, help=t("cli.queue.run.option.max_cost")
            ),
        ] = None,
        notify_on: Annotated[
            bool, typer.Option("--notify", help=t("cli.queue.run.option.notify"))
        ] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        config = loader.load_config(ctx.ensure_object(_State).config_path).config
        config_path = queue_service.absolute_config_flag(ctx.ensure_object(_State).config_path)

        def execute(
            item: queue_store.QueueItem, remaining: float | None
        ) -> queue_service.ItemResult:
            return queue_service.execute_item(item, remaining, config_path=config_path)

        def progress(item: queue_store.QueueItem, result: queue_service.ItemResult) -> None:
            for warning in result.warnings:
                typer.echo(warning, err=True)
            typer.echo(queue_display.result_line(item, result), err=True)

        with closing(db.connect()) as conn:
            report, deliveries = queue_service.run_with_notify(
                conn, config, notify_on=notify_on, execute=execute, until=until,
                max_cost_usd=max_cost_usd, on_item=None if as_json else progress,
            )  # fmt: skip
        if as_json:
            _echo_json(queue_display.report_json(report, deliveries))
        else:
            for line in queue_display.summary_lines(report, until=until, max_cost_usd=max_cost_usd):
                typer.echo(line)
            for line in notify.delivery_lines(deliveries, config.notify):
                typer.echo(line, err=True)
        if report.exit_code:
            raise typer.Exit(report.exit_code)

    @notify_app.command("test", help=t("cli.notify.test.help"))
    def notify_test(ctx: typer.Context, as_json: Annotated[bool, _json_option()] = False) -> None:
        config = loader.load_config(ctx.ensure_object(_State).config_path).config
        deliveries = notify.send(config.notify, t("notify.title.test"), t("notify.test.message"))
        if as_json:
            _echo_json({"deliveries": queue_display.deliveries_json(deliveries)})
        elif not deliveries:
            typer.echo(t("notify.test.none"))
        else:
            for line in notify.delivery_lines(deliveries, config.notify):
                typer.echo(line)
        if not notify.any_sent(deliveries):
            raise typer.Exit(int(ExitCode.TASK_FAILED))
