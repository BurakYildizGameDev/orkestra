"""``orkestra status``: the chief's view at a glance, at most 15 lines (Mimari §19, Faz 8a).

Sections register themselves with ``@section(name, order)``; a later phase adds its own
(Faz 10: the handoff file, Faz 12: the queue) without touching this module. A section gets
a ``StatusContext`` and returns its lines and its data; ``None`` leaves it out (nothing to
say). ``render`` keeps the lines to ``MAX_LINES``, ``--json`` has every section's data.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Any

from orkestra.config.schema import Config
from orkestra.handoff import brief, model, store
from orkestra.i18n import t
from orkestra.providers import registry
from orkestra.workspace import service

MAX_LINES = 15
SHOWN_RUNS = 3  # unapplied runs listed by name
SHOWN_PROVIDERS = 4  # budget lines before "+N more"
CHIEF_ENV = "ORKESTRA_CHIEF"
STATUS_WARNING_KEYS: dict[str, str] = {
    "no_git": "status.handoff.no_git",
    "unknown_commit": "status.handoff.unknown_commit",
    "stale": "status.handoff.stale",
}


@dataclass
class StatusContext:
    config: Config
    conn: sqlite3.Connection
    now: datetime
    environ: Mapping[str, str] = field(default_factory=dict)

    @cached_property
    def providers(self) -> list[registry.ProviderRow]:
        """Budget, consent and health of every provider, read once for all sections."""
        return registry.provider_overview(self.config, self.conn, self.now)


@dataclass(frozen=True)
class Section:
    lines: list[str]
    data: Any


SectionFn = Callable[[StatusContext], "Section | None"]
_SECTIONS: dict[str, tuple[int, SectionFn]] = {}


def section(name: str, *, order: int) -> Callable[[SectionFn], SectionFn]:
    """Register a status section; lower ``order`` comes first."""

    def register(fn: SectionFn) -> SectionFn:
        _SECTIONS[name] = (order, fn)
        return fn

    return register


def unregister(name: str) -> None:
    _SECTIONS.pop(name, None)


def registered() -> list[tuple[str, int, SectionFn]]:
    return sorted(((n, o, f) for n, (o, f) in _SECTIONS.items()), key=lambda s: (s[1], s[0]))


@dataclass(frozen=True)
class Status:
    sections: dict[str, Any]  # name -> data (JSON)
    lines: list[str]  # every line, before the limit


def collect(ctx: StatusContext) -> Status:
    sections: dict[str, Any] = {}
    lines: list[str] = []
    for name, _, fn in registered():
        result = fn(ctx)
        if result is None:
            continue
        sections[name] = result.data
        lines.extend(result.lines)
    return Status(sections, lines)


def render(status: Status, limit: int = MAX_LINES) -> str:
    """At most ``limit`` lines; a cut ends with a pointer to ``status --json``."""
    lines = status.lines
    if len(lines) > limit:
        cut = len(lines) - (limit - 1)
        lines = [*lines[: limit - 1], t("status.more", count=cut)]
    return "\n".join(lines)


# --- built-in sections -------------------------------------------------------------------


@section("profile", order=10)
def _profile(ctx: StatusContext) -> Section:
    chief = ctx.environ.get(CHIEF_ENV) or ctx.config.defaults.chief
    profile = ctx.config.defaults.profile
    return Section([t("status.profile", chief=chief, profile=profile)],
                   {"chief": chief, "profile": profile})  # fmt: skip


@section("handoff", order=20)
def _handoff(ctx: StatusContext) -> Section | None:
    """The handoff file's goal and, when it is old, one warning line; none without the file."""
    path = store.handoff_path(ctx.config, Path.cwd())
    if not path.exists():
        return None
    document = model.parse(store.read(path))
    goal_text = model.section_text(document, "goal") or ""
    first = next((line.strip() for line in goal_text.splitlines() if line.strip()), "")
    state = brief.staleness(document, ctx.config, Path.cwd(), brief.default_git)
    data = {
        "path": str(path),
        "goal": first,
        "stale": bool(state is not None and state.stale),
        "commit": state.commit if state is not None else None,
        "commits_after": state.count if state is not None else None,
    }
    lines = [t("status.handoff.line", goal=" ".join(first.split())[:70] or "-")]
    lines.extend(brief.warning_lines(state, STATUS_WARNING_KEYS))
    return Section(lines, data)


@section("unapplied", order=30)
def _unapplied(ctx: StatusContext) -> Section:
    runs = service.unapplied_runs(ctx.conn)
    data = {"runs": [{"run_id": r.run_id, "task_id": r.task_id, "summary": r.summary}
                     for r in runs]}  # fmt: skip
    if not runs:
        return Section([t("status.unapplied.none")], data)
    lines = [t("status.unapplied.title", count=len(runs))]
    for run in runs[:SHOWN_RUNS]:
        summary = " ".join(run.summary.split())[:70]
        lines.append(t("status.unapplied.run", run_id=run.run_id, task_id=run.task_id,
                       summary=summary or "-"))  # fmt: skip
    if len(runs) > SHOWN_RUNS:
        lines.append(t("status.unapplied.more", count=len(runs) - SHOWN_RUNS))
    return Section(lines, data)


def _limits_text(row: registry.ProviderRow) -> str:
    parts = [f"{limit.limit.removeprefix('daily_')} {limit.used:g}/{limit.value:g}"
             for limit in row.limits]  # fmt: skip
    if not parts:
        cost = f"{row.used.cost_usd:.4f}"
        parts = [t("status.budget.used", requests=row.used.requests, cost=cost)]
    return ", ".join(parts)


@section("budget", order=50)
def _budget(ctx: StatusContext) -> Section:
    rows = [r for r in ctx.providers if r.enabled]
    data = {
        "day": ctx.now.date().isoformat(),
        "providers": [
            {"name": r.name, "requests": r.used.requests, "tokens": r.used.tokens,
             "cost_usd": round(r.used.cost_usd, 6),
             "limits": [{"limit": x.limit, "value": x.value, "used": x.used} for x in r.limits]}
            for r in rows
        ],
    }  # fmt: skip
    lines = [t("status.budget.title", day=data["day"])]
    lines += [t("status.budget.line", name=r.name, text=_limits_text(r))
              for r in rows[:SHOWN_PROVIDERS]]  # fmt: skip
    if len(rows) > SHOWN_PROVIDERS:
        lines.append(t("status.budget.more", count=len(rows) - SHOWN_PROVIDERS))
    return Section(lines, data)


@section("health", order=70)
def _health(ctx: StatusContext) -> Section:
    paused = [r for r in ctx.providers if r.health.is_open(ctx.now)]
    data = {"paused": [
        {"name": r.name, "until": r.health.open_until.isoformat() if r.health.open_until else None,
         "error": r.health.last_error}
        for r in paused
    ]}  # fmt: skip
    if not paused:
        return Section([t("status.health.ok")], data)
    names = ", ".join(
        f"{r.name} ({r.health.open_until:%H:%M})" if r.health.open_until else r.name for r in paused
    )
    return Section([t("status.health.paused", providers=names)], data)


def default_context(config: Config, conn: sqlite3.Connection, now: datetime) -> StatusContext:
    return StatusContext(config, conn, now, dict(os.environ))
