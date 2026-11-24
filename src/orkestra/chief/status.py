"""``orkestra status``: the chief's view at a glance, at most 15 lines (Mimari §19, Faz 8a).

Sections register themselves with ``@section(name, order)``; a later phase adds its own
(Faz 10: the handoff file, Faz 12: the queue) without touching this module. A section gets
a ``StatusContext`` and returns its lines and its data; ``None`` leaves it out (nothing to
say). ``render`` keeps the lines to ``MAX_LINES``, ``--json`` has every section's data.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any

from orkestra import paths
from orkestra.chief import limits
from orkestra.config.schema import Config
from orkestra.errors import UsageError
from orkestra.handoff import brief, model, store
from orkestra.i18n import t
from orkestra.providers import registry
from orkestra.queue import store as queue_store
from orkestra.state import forecast, health
from orkestra.tasks.delegate import is_delegated
from orkestra.workspace import service

MAX_LINES = 15
SHOWN_RUNS = 3  # unapplied runs listed by name
SHOWN_PROVIDERS = 4  # budget lines before "+N more"
QUEUE_FAILED_WINDOW = timedelta(hours=24)  # queue failures older than this are not shown
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


@section("session", order=25)
def _session(ctx: StatusContext) -> Section | None:
    """The chief's own Claude Code session (Faz 13j): past ``handoff.suggest_at_tokens`` one
    line suggests a fresh session. Best effort: nothing when there is no transcript changed
    in the last hours, or it cannot be read (status must never fail for it)."""
    from orkestra.chief import tokens

    try:
        found = _live_transcript(ctx, tokens)
        if found is None:
            return None
        path, folder = found
        session = tokens.request_sizes(path)
        hint = tokens.handoff_hint(
            session, ctx.config.tokens.weights, threshold=ctx.config.handoff.suggest_at_tokens,
            start=tokens.fresh_start(folder),
        )  # fmt: skip
    except (OSError, UsageError):
        return None
    if hint is None:
        return None
    data = {"id": session.id, "context": hint.context, "start": hint.start,
            "saving_per_100": round(hint.saving_per_100), "over": hint.over}  # fmt: skip
    return Section([tokens.hint_line(hint)] if hint.over else [], data)


def _live_transcript(ctx: StatusContext, tokens: Any) -> tuple[Path, Path] | None:
    """The newest transcript of this project, if the session is still going. Claude Code names
    the folder after the directory as it was started (not resolved: a mapped drive stays); the
    git root is asked only when the current directory has none."""
    home = tokens.claude_home(ctx.environ)
    cwd = Path.cwd().absolute()
    for where in (lambda: cwd, lambda: store.project_root(cwd)):
        folder = tokens.project_folder(where(), home)
        if not folder.is_dir():
            continue
        (path,) = tokens.select_sessions(folder)
        return (path, folder) if tokens.active(path, ctx.now) else None
    return None


@section("chief_quota", order=27)
def _chief_quota(ctx: StatusContext) -> Section | None:
    """The chief's usage windows, as the status line last read them (Faz 13k); nothing when
    there is no fresh reading (no status line set up, or the session is over)."""
    found = limits.status_windows(ctx.now)
    if not found:
        return None
    data = {"windows": [
        {"name": w.name, "used": w.used,
         "resets_at": w.resets_at.isoformat() if w.resets_at else None,
         "eta_s": round(w.eta_s) if w.eta_s is not None else None}
        for w in found
    ]}  # fmt: skip
    return Section([t("status.chief_quota.line",
                      windows=" · ".join(limits.window_text(w) for w in found))], data)  # fmt: skip


@section("unapplied", order=30)
def _unapplied(ctx: StatusContext) -> Section:
    runs = service.unapplied_runs(ctx.conn)
    data = {"runs": [{"run_id": r.run_id, "task_id": r.task_id,
                      "status": r.status, "summary": r.summary}
                     for r in runs]}  # fmt: skip
    if not runs:
        return Section([t("status.unapplied.none")], data)
    lines = [t("status.unapplied.title", count=len(runs))]
    for run in runs[:SHOWN_RUNS]:
        summary = " ".join(run.summary.split())[:70]
        state = t(f"status.unapplied.state.{run.status}")
        lines.append(t("status.unapplied.run", run_id=run.run_id, task_id=run.task_id,
                       status=state, summary=summary or "-"))  # fmt: skip
    if len(runs) > SHOWN_RUNS:
        lines.append(t("status.unapplied.more", count=len(runs) - SHOWN_RUNS))
    return Section(lines, data)


@section("queue", order=40)
def _queue(ctx: StatusContext) -> Section | None:
    """Waiting and running queue items and the failures of the last day (Faz 12a); no line
    when there are none, so an old failure does not stay on the screen."""
    found = queue_store.counts(ctx.conn, failed_since=ctx.now - QUEUE_FAILED_WINDOW)
    owner = queue_store.lock_owner(ctx.conn)
    data = {"pending": found["pending"], "running": found["running"], "failed": found["failed"],
            "runner_pid": owner.pid if owner is not None else None}  # fmt: skip
    if not (found["pending"] or found["running"] or found["failed"]):
        return None
    return Section([t("status.queue.line", pending=found["pending"], running=found["running"],
                      failed=found["failed"])], data)  # fmt: skip


@section("delegated", order=45)
def _delegated(ctx: StatusContext) -> Section | None:
    """Delegated milestone tasks in the queue (Faz 13r-a, D-129)."""
    all_items = queue_store.items(ctx.conn)
    delegated_items = [item for item in all_items if is_delegated(item, ctx.conn)]
    if not delegated_items:
        return None

    items_data: list[dict[str, Any]] = []
    lines: list[str] = [t("status.delegated.title")]

    for item in delegated_items:
        task_name = Path(item.path).stem
        run_id = item.result_ref
        worker: str | None = None
        duration_s: float | None = None
        failovers = 0

        if run_id:
            query = "SELECT task_id, provider, model, duration_s FROM runs WHERE run_id = ?"
            row = ctx.conn.execute(query, (run_id,)).fetchone()
            if row:
                if row[0]:
                    task_name = str(row[0])
                prov = str(row[1]) if row[1] else None
                mod = str(row[2]) if row[2] else None
                if prov:
                    worker = prov if prov == mod or not mod else f"{prov}/{mod}"
                if row[3] is not None:
                    duration_s = round(float(row[3]), 1)
            env_file = paths.run_dir(run_id) / "envelope.json"
            try:
                env_doc = json.loads(env_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                env_doc = {}
            # a failover is a change of worker (envelope), not a retry on the same one
            if isinstance(env_doc, dict) and isinstance(env_doc.get("failovers"), list):
                failovers = len(env_doc["failovers"])

        if duration_s is None and item.started_at:
            try:
                start_dt = datetime.fromisoformat(item.started_at)
                end_dt = datetime.fromisoformat(item.finished_at) if item.finished_at else ctx.now
                duration_s = round((end_dt - start_dt).total_seconds(), 1)
            except (ValueError, TypeError):
                pass

        doc = {
            "id": item.id,
            "task": task_name,
            "status": item.status,
            "worker": worker,
            "duration_s": duration_s,
            "failovers": failovers,
            "run_id": run_id,
        }
        items_data.append(doc)

    for doc in items_data[:SHOWN_RUNS]:
        dur_str = f"{doc['duration_s']}s" if doc["duration_s"] is not None else "-"
        lines.append(
            t(
                "status.delegated.item",
                id=doc["id"],
                task=doc["task"],
                status=t(f"queue.status.{doc['status']}"),
                worker=doc["worker"] or "-",
                duration=dur_str,
                failovers=doc["failovers"],
            )
        )
    if len(items_data) > SHOWN_RUNS:
        lines.append(t("status.delegated.more", count=len(items_data) - SHOWN_RUNS))

    return Section(lines, items_data)


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


@section("forecast", order=55)
def _forecast(ctx: StatusContext) -> Section | None:
    """Providers running low on quota (Faz 13k): one line naming them, none when no provider
    is; the JSON has every forecast. Paused providers already say when they come back."""
    paused = {r.name for r in ctx.providers if r.health.is_open(ctx.now)}
    found = forecast.forecasts(ctx.conn, ctx.config, ctx.now, skip=paused)
    if not found:
        return None
    data = {"providers": [forecast.to_dict(f) for f in found]}
    low = [f for f in found if f.low]
    if not low:
        return Section([], data)
    names = ", ".join(forecast.describe(f) for f in low)
    return Section([t("status.forecast.line", providers=names)], data)


@section("health", order=70)
def _health(ctx: StatusContext) -> Section:
    paused = [r for r in ctx.providers if r.health.is_open(ctx.now)]
    data = {"paused": [
        {"name": r.name, "until": r.health.open_until.isoformat() if r.health.open_until else None,
         "error": r.health.last_error, "reason": r.health.reason}
        for r in paused
    ]}  # fmt: skip
    if not paused:
        return Section([t("status.health.ok")], data)
    names = ", ".join(_paused_name(r.name, r.health, ctx.now) for r in paused)
    return Section([t("status.health.paused", providers=names)], data)


def default_context(config: Config, conn: sqlite3.Connection, now: datetime) -> StatusContext:
    return StatusContext(config, conn, now, dict(os.environ))


def _paused_name(name: str, state: health.Health, now: datetime) -> str:
    if state.open_until is None:
        return name
    if state.reason == "quota":
        return t(
            "status.health.quota_item", name=name, until=health.until_text(state.open_until, now)
        )
    return f"{name} ({state.open_until:%H:%M})"
