"""``templates``, ``cache``, ``review``, ``map``, ``plan``, ``discard``, ``gc`` and
``doctor`` (düzeltme-fable b, D-106)."""

from __future__ import annotations

import asyncio
import sys
from contextlib import closing
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from orkestra import doctor
from orkestra.cache import responses
from orkestra.chief import execute as executor
from orkestra.commands.common import (
    _echo_json,
    _json_option,
    _State,
)
from orkestra.commands.setup import _echo_doctor
from orkestra.config import loader
from orkestra.errors import ExitCode
from orkestra.i18n import t
from orkestra.state import db, retention
from orkestra.tasks import templates
from orkestra.workspace import service


def _template_json(item: templates.Template) -> dict[str, Any]:
    return {
        "name": item.name, "source": item.source, "description": item.description,
        "path": item.path or None, "overrides_builtin": item.overrides,
        "params": [{"name": p.name, "default": p.default, "required": p.default is None,
                    "description": p.description} for p in item.params],
        "task": dict(item.task),
    }  # fmt: skip


def register(
    app: typer.Typer, templates_app: typer.Typer, cache_app: typer.Typer, plan_app: typer.Typer
) -> None:
    """``templates``, ``cache``, ``review``, ``map``, ``plan``, ``discard``, ``gc``, ``doctor``."""

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
        install_hook: Annotated[
            bool, typer.Option("--install-hook", help=t("cli.map.option.install_hook"))
        ] = False,
        after_commit: Annotated[
            bool, typer.Option("--after-commit", help=t("cli.map.option.after_commit"))
        ] = False,
        as_json: Annotated[bool, _json_option()] = False,
    ) -> None:
        from orkestra.chief import repomap

        if install_hook:
            hooked = repomap.install_index_hook(Path.cwd())
            key = "created" if hooked.created else "updated" if hooked.updated else "exists"
            typer.echo(t(f"map.hook.{key}", path=hooked.path))
            return
        if after_commit:
            config, _ = executor.load(ctx.ensure_object(_State).config_path)
            if config is not None:  # the hook runs quietly; no config, nothing to map with
                repomap.after_commit(repomap.project_root(Path.cwd()), config)
            return
        loaded = loader.load_config(ctx.ensure_object(_State).config_path)
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
            typer.Option(
                "--older-than",
                min=0,
                metavar="DAYS",
                help=t("cli.gc.option.older_than", days=retention.MIN_KEEP.days),
            ),
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
                 "failed": [str(p) for p, _ in report.failed],
                 "rows": asdict(report.rows)}
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
        rows_key = "gc.rows_dry" if report.dry_run else "gc.rows"
        typer.echo(t(rows_key, **asdict(report.rows)))

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
            _echo_doctor(report)
        if not report.ok:
            raise typer.Exit(int(ExitCode.TASK_FAILED))
