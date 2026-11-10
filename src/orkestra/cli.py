"""Command line interface: argument parsing and calls into services only (Mimari §2)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Annotated

import typer

from orkestra import __version__, i18n
from orkestra.errors import ExitCode, OrkestraError, exit_code_for
from orkestra.i18n import t


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


def build_app() -> typer.Typer:
    """Build the typer app. Help texts are translated here, so set the language first."""
    app = typer.Typer(name="orkestra", help=t("cli.help"), no_args_is_help=True)

    @app.callback()
    def main(
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
    ) -> None:
        pass

    return app


def _find_lang_arg(args: Sequence[str]) -> str | None:
    """Read ``--lang`` before typer parses, so help texts are built in that language."""
    for i, arg in enumerate(args):
        if arg == "--":
            break
        if arg == "--lang":
            return args[i + 1] if i + 1 < len(args) else None
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def app(argv: Sequence[str] | None = None) -> None:
    """Console entry point (``orkestra``)."""
    args = list(sys.argv[1:] if argv is None else argv)
    i18n.init_language(cli=_find_lang_arg(args))
    try:
        build_app()(args=args, prog_name="orkestra")
    except OrkestraError as exc:
        typer.echo(t("errors.prefix", message=exc.message), err=True)
        raise SystemExit(exit_code_for(exc)) from None
    except Exception as exc:
        typer.echo(t("errors.internal", detail=f"{type(exc).__name__}: {exc}"), err=True)
        raise SystemExit(int(ExitCode.INTERNAL)) from None
