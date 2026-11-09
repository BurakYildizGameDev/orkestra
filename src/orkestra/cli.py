"""Command line interface: argument parsing and calls into services only (Mimari §2)."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Any

import typer

from orkestra import __version__, doctor, envelope, i18n
from orkestra.config import loader
from orkestra.errors import ExitCode, OrkestraError, exit_code_for
from orkestra.i18n import t
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


def build_app() -> typer.Typer:
    """Build the typer app. Help texts are translated here, so set the language first."""
    app = typer.Typer(name="orkestra", help=t("cli.help"), no_args_is_help=True)
    config_app = typer.Typer(name="config", help=t("cli.config.help"), no_args_is_help=True)
    app.add_typer(config_app)

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
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
        request = runner.AskRequest(
            prompt=prompt,
            provider=provider,
            model=model,
            tier=tier,
            context=tuple(context or ()),
            schema=schema,
        )
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
