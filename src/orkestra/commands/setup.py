"""``init``, ``ui`` and ``config`` (düzeltme-fable b, D-106).

``cli._at_terminal`` is looked up at call time: tests replace it on ``cli``.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Annotated

import typer

from orkestra import doctor, i18n
from orkestra.commands.common import (
    _echo_json,
    _echo_sources,
    _json_option,
    _sources_json,
    _State,
)
from orkestra.config import loader
from orkestra.errors import ExitCode, UsageError
from orkestra.i18n import t
from orkestra.security.redact import config_for_display
from orkestra.state import db
from orkestra.tui import detect, wizard


class _TyperPrompter:
    """The wizard's ``Prompter`` for ``init --plain``: plain questions with ``typer.prompt``."""

    def say(self, text: str) -> None:
        typer.echo(text)

    def ask(self, text: str, default: str | None = None) -> str:
        return str(typer.prompt(text, default="" if default is None else default,
                                show_default=bool(default)))  # fmt: skip

    def confirm(self, text: str, default: bool = False) -> bool:
        return wizard.confirm_by_asking(self.ask, self.say, text, default)


def _echo_doctor(report: doctor.DoctorReport) -> None:
    for line in doctor.report_lines(report):
        typer.echo(line)


def _echo_outcome(outcome: wizard.Outcome, notes: list[str]) -> None:
    for line in wizard.outcome_lines(outcome, notes):
        typer.echo(line)


def _echo_consent(granted: list[str], waiting: list[str]) -> None:
    for line in wizard.consent_lines(granted, waiting):
        typer.echo(line)


def _init_defaults(config_flag: Path | None, *, project: bool, force: bool, as_json: bool) -> None:
    target = loader.init_target(config_flag, project=project)
    if target.exists() and not force:
        if as_json:
            _echo_json({"path": str(target), "written": False, "backup": None,
                        "providers": [], "consent": [], "notes": []})  # fmt: skip
        else:
            typer.echo(t("init.exists", path=target))
        return
    answers = wizard.defaults_answers(detect.detect())
    answers.project = project
    outcome = wizard.save_answers(answers, config_flag=config_flag, now=db.local_now(),
                                  fresh=True)  # fmt: skip
    if as_json:
        _echo_json(
            {
                "path": str(outcome.path),
                "written": True,
                "backup": str(outcome.backup) if outcome.backup else None,
                "providers": outcome.providers,
                "consent": [],  # --defaults never grants consent (Mimari §22)
                "notes": answers.notes,
            }
        )
        return
    _echo_outcome(outcome, answers.notes)
    _echo_consent([], outcome.providers)


def _init_plain(config_flag: Path | None, *, project: bool, force: bool) -> None:
    try:
        wizard.run_and_save(
            _TyperPrompter(), detect.detect(), config_flag=config_flag, project=project,
            force=force, set_language=i18n.set_language,
            run_doctor=lambda: doctor.report_lines(
                asyncio.run(doctor.run_doctor(config_flag=config_flag))
            ),
        )  # fmt: skip
    except (typer.Abort, EOFError):
        # No answer to read (closed stdin, or NUL that Windows reports as a terminal).
        raise UsageError(t("wizard.error.no_input")) from None


def _init_interactive(config_flag: Path | None, *, project: bool) -> None:
    """A bare ``init`` at a terminal: the interface's wizard, or plain questions under
    ``TERM=dumb``. Textual is imported only here and for ``ui`` (every other command stays fast)."""
    from orkestra.tui import app as tui_app

    if not tui_app.usable_terminal():
        _init_plain(config_flag, project=project, force=False)
        return
    interface = tui_app.OrkestraApp(config_flag=config_flag, mode="wizard", project=project)
    interface.run()
    for line in interface.summary:  # the interface is gone; the result stays in the terminal
        typer.echo(line)
    if not interface.wizard_done:  # quit while a question was open
        typer.echo(t("wizard.cancelled"))
        raise typer.Exit(int(ExitCode.USAGE))
    if interface.wizard_exit_code:
        raise typer.Exit(interface.wizard_exit_code)  # the error's own code, as --plain gives


def register(app: typer.Typer, config_app: typer.Typer) -> None:
    """``init``, ``ui``, ``config show|validate``."""

    @app.command("init", help=t("cli.init.help"))
    def init_command(
        ctx: typer.Context,
        force: Annotated[bool, typer.Option("--force", help=t("cli.init.option.force"))] = False,
        project: Annotated[
            bool, typer.Option("--project", help=t("cli.init.option.project"))
        ] = False,
        plain: Annotated[bool, typer.Option("--plain", help=t("cli.init.option.plain"))] = False,
        defaults: Annotated[
            bool, typer.Option("--defaults", help=t("cli.init.option.defaults"))
        ] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        state = ctx.ensure_object(_State)
        if plain and defaults:
            raise UsageError(t("wizard.error.plain_and_defaults"))
        if plain and as_json:
            raise UsageError(t("wizard.error.plain_json"))
        if defaults:
            _init_defaults(state.config_path, project=project, force=force, as_json=as_json)
            return
        # A bare ``init`` at a terminal opens the wizard; ``--force`` still means "reset the
        # file to the example", and without a terminal the example is copied as before.
        target = loader.init_target(state.config_path, project=project)
        if plain:
            _init_plain(state.config_path, project=project, force=force)
            return
        from orkestra import cli  # at call time: tests replace the hook on ``cli``

        if not as_json and not force and cli._at_terminal():
            if target.exists():  # editing an existing file is "init --plain", never implicit
                typer.echo(t("init.exists", path=target))
                typer.echo(t("wizard.hint.edit"))
                return
            _init_interactive(state.config_path, project=project)
            return
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

    @app.command("ui", help=t("cli.ui.help"))
    def ui_command(
        ctx: typer.Context,
        tui: Annotated[bool, typer.Option("--tui", help=t("cli.ui.option.tui"))] = False,
        no_browser: Annotated[
            bool, typer.Option("--no-browser", help=t("cli.ui.option.no_browser"))
        ] = False,
        window: Annotated[bool, typer.Option("--window", help=t("cli.ui.option.window"))] = False,
        port: Annotated[
            int, typer.Option("--port", min=0, max=65535, help=t("cli.ui.option.port"))
        ] = 0,
    ) -> None:
        if tui:
            from orkestra.tui import app as tui_app

            if not tui_app.usable_terminal():
                raise UsageError(t("ui.error.no_terminal"))
            tui_app.OrkestraApp(config_flag=ctx.ensure_object(_State).config_path, mode="ui").run()
            return

        import webbrowser

        from orkestra.web import server

        config_path = ctx.ensure_object(_State).config_path
        srv = server.create_server(
            server.ServerConfig(host="127.0.0.1", port=port, config_path=config_path)
        )
        url = f"http://127.0.0.1:{srv.server_port}/?token={srv.token}"

        typer.echo(t("ui.web.started", url=url))
        typer.echo(t("ui.web.press_ctrl_c"))

        if window:
            try:
                import webview  # type: ignore

                server_thread = threading.Thread(target=srv.serve_forever, daemon=True)
                server_thread.start()
                webview.create_window("Orkestra", url, width=1280, height=800)
                webview.start()
                srv.shutdown()
                typer.echo(t("ui.web.stopped"))
                return
            except ImportError:
                typer.echo(t("ui.web.window_fallback"), err=True)
                if not no_browser:
                    webbrowser.open(url)
        elif not no_browser:
            webbrowser.open(url)

        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            srv.server_close()
            typer.echo(t("ui.web.stopped"))

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
