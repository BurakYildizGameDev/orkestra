"""The chief's context tools and reports (düzeltme-fable b, D-106)."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Annotated

import typer

from orkestra.chief import execute as executor
from orkestra.chief import finder as file_finder
from orkestra.chief import reader as file_reader
from orkestra.chief import status
from orkestra.chief import tokens as token_map
from orkestra.commands.common import (
    _echo_json,
    _json_option,
    _State,
)
from orkestra.config import loader
from orkestra.i18n import t
from orkestra.state import db, retention, stats


def register(app: typer.Typer) -> None:
    """``stats``, ``exec``, ``read``, ``find``, ``tokens``, ``status``."""

    @app.command("stats", help=t("cli.stats.help"))
    def stats_command(
        since: Annotated[
            str,
            typer.Option(
                "--since",
                metavar="DURATION",
                help=t("cli.stats.option.since", days=retention.MIN_KEEP.days),
            ),
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

    @app.command(
        "exec", help=t("cli.exec.help"),
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )  # fmt: skip
    def exec_command(
        ctx: typer.Context,
        command: Annotated[list[str], typer.Argument(metavar="-- COMMAND...")],
        max_lines: Annotated[
            int | None, typer.Option("--max-lines", min=1, help=t("cli.exec.option.max_lines"))
        ] = None,
        no_model: Annotated[
            bool, typer.Option("--no-model", help=t("cli.exec.option.no_model"))
        ] = False,
        timeout: Annotated[
            float | None, typer.Option("--timeout", min=1, help=t("cli.exec.option.timeout"))
        ] = None,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        config, problem = executor.load(ctx.ensure_object(_State).config_path)
        result = executor.execute(
            command, cwd=Path.cwd(), config=config, config_problem=problem,
            max_lines=max_lines, use_model=False if no_model else None, timeout_s=timeout,
        )  # fmt: skip
        if as_json:
            _echo_json(executor.to_dict(result))
        else:
            typer.echo(executor.render(result))
        raise typer.Exit(result.exit_code)

    @app.command("read", help=t("cli.read.help"))
    def read_command(
        ctx: typer.Context,
        files: Annotated[
            list[Path], typer.Argument(metavar="FILES...", help=t("cli.read.arg.files"))
        ],
        question: Annotated[
            str, typer.Argument(metavar="QUESTION", help=t("cli.read.arg.question"))
        ],
        no_cache: Annotated[
            bool, typer.Option("--no-cache", help=t("cli.read.option.no_cache"))
        ] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        result = file_reader.read(
            files, question, config=loaded.config, cwd=Path.cwd(), no_cache=no_cache
        )
        if as_json:
            _echo_json(file_reader.to_dict(result))
        else:
            typer.echo(file_reader.render(result))

    @app.command("find", help=t("cli.find.help"))
    def find_command(
        ctx: typer.Context,
        pattern: Annotated[str, typer.Argument(metavar="PATTERN", help=t("cli.find.arg.pattern"))],
        regex: Annotated[bool, typer.Option("--regex", help=t("cli.find.option.regex"))] = False,
        globs: Annotated[
            list[str] | None, typer.Option("--glob", help=t("cli.find.option.glob"))
        ] = None,
        max_hits: Annotated[
            int | None, typer.Option("--max-hits", min=1, help=t("cli.find.option.max_hits"))
        ] = None,
        question: Annotated[
            str | None, typer.Option("--ask", metavar="QUESTION", help=t("cli.find.option.ask"))
        ] = None,
        no_cache: Annotated[
            bool, typer.Option("--no-cache", help=t("cli.read.option.no_cache"))
        ] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        config, problem = executor.load(ctx.ensure_object(_State).config_path)
        result = file_finder.find(
            pattern, cwd=Path.cwd(), config=config, regex=regex, globs=globs or (),
            max_hits=max_hits, question=question, no_cache=no_cache, config_problem=problem,
        )  # fmt: skip
        if as_json:
            _echo_json(file_finder.to_dict(result))
        else:
            typer.echo(file_finder.render(result))
        if not result.hits:
            raise typer.Exit(1)  # like grep

    @app.command("tokens", help=t("cli.tokens.help"))
    def tokens_command(
        ctx: typer.Context,
        session: Annotated[
            str | None, typer.Option("--session", help=t("cli.tokens.option.session"))
        ] = None,
        since: Annotated[
            str | None,
            typer.Option("--since", metavar="DURATION", help=t("cli.tokens.option.since")),
        ] = None,
        project: Annotated[
            Path | None, typer.Option("--project", help=t("cli.tokens.option.project"))
        ] = None,
        top: Annotated[
            int | None, typer.Option("--top", min=1, help=t("cli.tokens.option.top"))
        ] = None,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        start = db.local_now() - stats.parse_since(since) if since else None
        report = token_map.collect(
            project=(project or Path.cwd()).absolute(), session=session, since=start, top=top,
            config_flag=ctx.ensure_object(_State).config_path,
        )  # fmt: skip
        if as_json:
            _echo_json(token_map.to_dict(report))
        else:
            typer.echo(token_map.render(report))

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
