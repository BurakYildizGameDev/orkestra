"""Command line interface: argument parsing and calls into services only (Mimari §2)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer

from orkestra import __version__, i18n
from orkestra.commands.common import (
    _echo_json,
    _State,
)
from orkestra.config import loader
from orkestra.console import safe_streams as _safe_streams
from orkestra.errors import ExitCode, OrkestraError, exit_code_for
from orkestra.i18n import t


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


def _interactive() -> bool:
    """Whether the user can be asked a question (tests replace this)."""
    return sys.stdin.isatty()


def _at_terminal() -> bool:
    """A person at a terminal: bare ``init`` opens the wizard only then (Faz 11a)."""
    return sys.stdin.isatty() and sys.stdout.isatty()


_TYPER_TEXTS = {  # typer's help panel words, in the chosen language (B-23, D-141)
    "ARGUMENTS_PANEL_TITLE": "cli.typer.arguments",
    "OPTIONS_PANEL_TITLE": "cli.typer.options",
    "COMMANDS_PANEL_TITLE": "cli.typer.commands",
    "ERRORS_PANEL_TITLE": "cli.typer.error",
    "ABORTED_TEXT": "cli.typer.aborted",
}


def _translate_typer() -> None:
    """Typer's panel titles are module constants; unknown ones (another typer) are skipped.
    Its parser's messages ("No such option" …) are hard-coded inside typer and stay English."""
    from typer import rich_utils

    for name, key in _TYPER_TEXTS.items():
        if hasattr(rich_utils, name):
            setattr(rich_utils, name, t(key))
    if hasattr(rich_utils, "DEFAULT_STRING"):
        rich_utils.DEFAULT_STRING = "[" + t("cli.typer.default") + ": {}]"
    if hasattr(rich_utils, "REQUIRED_LONG_STRING"):
        rich_utils.REQUIRED_LONG_STRING = "[" + t("cli.typer.required") + "]"
    if hasattr(rich_utils, "RICH_HELP"):
        rich_utils.RICH_HELP = t(
            "cli.typer.try_help",
            command="[blue]'{command_path} {help_option}'[/]",
        )


def build_app() -> typer.Typer:
    """Build the typer app. Help texts are translated here, so set the language first."""
    # Imported here: the command modules look up the hooks above on ``cli`` at call time.
    from orkestra.commands import chief, handoff, providers, queue, setup, tasks, tools

    _translate_typer()
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
    statusline_app = typer.Typer(name="statusline", help=t("cli.statusline.help"))
    app.add_typer(statusline_app)

    providers.register(app, providers_app)

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

    setup.register(app, config_app)
    tasks.register(app)
    chief.register(app)
    handoff.register(handoff_app, statusline_app)
    tools.register(app, templates_app, cache_app, plan_app)
    queue.register(app)
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
