"""``orkestra stats``: how the workers did, per provider and per task tag (Faz 7b, Mimari §3).

- Runs come from ``runs`` (started since ``since``); a run counts for the provider that
  gave its final result. A run without one (escalated, failed before an answer) counts for
  the provider its last settled request went to, so its failure lowers that worker's rate;
  ``None`` when it sent nothing. Runs still ``running`` are counted apart and left out of
  every rate and average.
- Tokens and cost come from the ``actual`` rows of ``usage`` (reservations never count), for
  the provider each request went to, so a failover's tokens count where they were spent.
- Per tag: a run with several tags counts for each of them; runs without tags are ``None``.
- Savings (Mimari §19, Faz 8a): what the workers wrote (``worker_output_tokens``) against
  what came back to the chief (``envelope_chars``, as tokens). The chief's own use cannot
  be measured, so this is always labelled an estimate.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from orkestra.errors import UsageError
from orkestra.i18n import t
from orkestra.providers.base import estimate_tokens

DEFAULT_SINCE = "7d"
FINISHED = ("ok", "failed", "escalate", "error")
_SINCE = re.compile(r"(\d+)([dhm])")
_UNITS = {"d": "days", "h": "hours", "m": "minutes"}
MAX_SINCE = timedelta(days=36500)  # far enough back; more would overflow the dates
# UTC offsets of stored times differ by at most a day: SQL narrows with this margin.
_OFFSET_MARGIN = timedelta(days=2)


def parse_since(text: str) -> timedelta:
    """``7d``, ``24h``, ``30m``: a positive whole number of days, hours or minutes (at most
    about a hundred years)."""
    match = _SINCE.fullmatch(text.strip())
    if match is None or int(match[1]) == 0:
        raise UsageError(t("stats.error.since", value=text))
    try:
        window = timedelta(**{_UNITS[match[2]]: int(match[1])})
    except OverflowError:
        window = MAX_SINCE + MAX_SINCE
    if window > MAX_SINCE:
        raise UsageError(t("stats.error.since", value=text))
    return window


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    estimated: bool = False  # some numbers were estimated (no usage report, history price)

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
            self.cost_usd + other.cost_usd,
            self.estimated or other.estimated,
        )


@dataclass(frozen=True)
class Row:
    """One provider, one tag or the total. Rates and averages are ``None`` without runs."""

    name: str | None
    runs: int
    ok: int
    failed: int
    escalate: int
    error: int
    success_rate: float | None
    avg_attempts: float | None
    avg_duration_s: float | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    estimated: bool


@dataclass(frozen=True)
class Savings:
    worker_output_tokens: int
    envelope_chars: int

    @property
    def envelope_tokens(self) -> int:
        return estimate_tokens(self.envelope_chars) if self.envelope_chars else 0


@dataclass(frozen=True)
class Report:
    since: datetime
    until: datetime
    providers: tuple[Row, ...]
    tags: tuple[Row, ...]
    totals: Row
    running: int  # started, not finished (or killed from outside): not in any number above
    savings: Savings = Savings(0, 0)


@dataclass(frozen=True)
class _Run:
    run_id: str
    status: str
    provider: str | None
    attempts: int | None
    duration_s: float | None
    tags: tuple[str, ...]
    worker_output_tokens: int | None = None
    envelope_chars: int | None = None

    @property
    def tag_keys(self) -> tuple[str | None, ...]:
        return self.tags or (None,)


def _tags(raw: str | None) -> tuple[str, ...]:
    try:
        value = json.loads(raw) if raw else []
    except ValueError:
        return ()
    return tuple(str(tag) for tag in value) if isinstance(value, list) else ()


def _started(raw: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _runs(conn: sqlite3.Connection, since: datetime) -> list[_Run]:
    """Runs started since ``since``. Stored times keep the UTC offset of their day, so they
    are compared as instants; SQL only narrows the rows (strings, with a margin)."""
    rows = conn.execute(
        "SELECT run_id, status, provider, attempts, duration_s, tags, started_at, "
        "worker_output_tokens, envelope_chars FROM runs "
        "WHERE started_at >= ?",
        ((since - _OFFSET_MARGIN).isoformat(),),
    ).fetchall()
    chosen = [
        (started, r) for r in rows if (started := _started(r["started_at"])) and started >= since
    ]
    chosen.sort(key=lambda pair: (pair[0], pair[1]["run_id"]))
    return [
        _Run(r["run_id"], r["status"] or "running", r["provider"], r["attempts"],
             r["duration_s"], _tags(r["tags"]), r["worker_output_tokens"],
             r["envelope_chars"])
        for _, r in chosen
    ]  # fmt: skip


def _usage(
    conn: sqlite3.Connection, runs: Sequence[_Run], since: datetime
) -> list[tuple[str | None, str | None, Usage]]:
    """``(run_id, provider, usage)`` of every settled request of ``runs``, in request order:
    tokens and cost belong to the runs in the window, so every row adds up."""
    wanted = {run.run_id for run in runs}
    rows = conn.execute(
        "SELECT run_id, provider, prompt_tokens, completion_tokens, cost_usd, estimated "
        "FROM usage WHERE kind = 'actual' AND run_id IN "
        "(SELECT run_id FROM runs WHERE started_at >= ?) ORDER BY id",
        ((since - _OFFSET_MARGIN).isoformat(),),
    ).fetchall()
    return [
        (r["run_id"], r["provider"],
         Usage(r["prompt_tokens"] or 0, r["completion_tokens"] or 0, r["cost_usd"] or 0.0,
               bool(r["estimated"])))
        for r in rows
        if r["run_id"] in wanted
    ]  # fmt: skip


def _mean(values: Iterable[float | int | None]) -> float | None:
    known = [v for v in values if v is not None]
    return round(sum(known) / len(known), 3) if known else None


def _total(amounts: Iterable[Usage]) -> Usage:
    return sum(amounts, Usage())


def _row(name: str | None, runs: Sequence[_Run], amounts: Iterable[Usage]) -> Row:
    """``runs``: finished runs only."""
    usage = _total(amounts)
    counts = {status: sum(1 for r in runs if r.status == status) for status in FINISHED}
    return Row(
        name=name,
        runs=len(runs),
        ok=counts["ok"],
        failed=counts["failed"],
        escalate=counts["escalate"],
        error=counts["error"],
        success_rate=round(counts["ok"] / len(runs), 3) if runs else None,
        avg_attempts=_mean(r.attempts for r in runs),
        avg_duration_s=_mean(r.duration_s for r in runs),
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cost_usd=round(usage.cost_usd, 6),
        estimated=usage.estimated,
    )


def _group(
    runs: Iterable[_Run], keys: Callable[[_Run], Iterable[str | None]]
) -> dict[str | None, list[_Run]]:
    grouped: dict[str | None, list[_Run]] = defaultdict(list)
    for run in runs:
        for key in keys(run):
            grouped[key].append(run)
    return grouped


def _ordered(keys: Iterable[str | None]) -> list[str | None]:
    """Names in alphabetical order, ``None`` (no provider / no tag) last."""
    return sorted(set(keys), key=lambda key: (key is None, key or ""))


def collect(conn: sqlite3.Connection, *, since: datetime, now: datetime) -> Report:
    runs = _runs(conn, since)
    finished = [r for r in runs if r.status in FINISHED]
    usage = _usage(conn, runs, since)
    last_used = {run_id: provider for run_id, provider, _ in usage}  # in request order

    by_provider = _group(finished, lambda r: (r.provider or last_used.get(r.run_id),))
    provider_usage: dict[str | None, list[Usage]] = defaultdict(list)
    for _, provider, amount in usage:
        provider_usage[provider].append(amount)

    by_tag = _group(finished, lambda r: r.tag_keys)
    tags_of = {r.run_id: r.tag_keys for r in runs}
    tag_usage: dict[str | None, list[Usage]] = defaultdict(list)
    for run_id, _, amount in usage:
        for tag in tags_of.get(run_id or "", ()):
            tag_usage[tag].append(amount)

    return Report(
        since=since,
        until=now,
        providers=tuple(
            _row(name, by_provider.get(name, []), provider_usage.get(name, []))
            for name in _ordered([*by_provider, *provider_usage])
        ),
        tags=tuple(_row(tag, by_tag[tag], tag_usage.get(tag, [])) for tag in _ordered(by_tag)),
        totals=_row(None, finished, (amount for _, _, amount in usage)),
        running=len(runs) - len(finished),
        savings=Savings(
            sum(r.worker_output_tokens or 0 for r in finished),
            sum(r.envelope_chars or 0 for r in finished),
        ),
    )


# --- output ----------------------------------------------------------------------------


def _numbers(row: Row) -> dict[str, Any]:
    data = asdict(row)
    del data["name"]
    return data


def to_dict(report: Report) -> dict[str, Any]:
    """``stats --json``."""
    return {
        "since": report.since.isoformat(),
        "until": report.until.isoformat(),
        "providers": [{"provider": r.name, **_numbers(r)} for r in report.providers],
        "tags": [{"tag": r.name, **_numbers(r)} for r in report.tags],
        "totals": _numbers(report.totals),
        "running": report.running,
        "savings": {
            "worker_output_tokens": report.savings.worker_output_tokens,
            "envelope_chars": report.savings.envelope_chars,
            "envelope_tokens": report.savings.envelope_tokens,
            "estimated": True,
        },
    }


def _fmt(value: float | None, pattern: str) -> str:
    return "-" if value is None else format(value, pattern)


def _line(row: Row, name: str) -> str:
    return t(
        "stats.line", name=name, ok=row.ok, runs=row.runs, rate=_fmt(row.success_rate, ".0%"),
        attempts=_fmt(row.avg_attempts, ".1f"), seconds=_fmt(row.avg_duration_s, ".1f"),
        tokens=row.prompt_tokens + row.completion_tokens, cost=f"${row.cost_usd:.4f}",
        estimated=t("stats.estimated") if row.estimated else "",
    )  # fmt: skip


def render(report: Report) -> str:
    """``stats`` for humans."""
    since = report.since.strftime("%Y-%m-%d %H:%M")
    if not report.totals.runs and not report.running:
        return t("stats.none", since=since)
    lines = [t("stats.title", since=since, runs=report.totals.runs, running=report.running)]
    lines.append(t("stats.section.providers"))
    lines += [_line(r, r.name or t("stats.no_provider")) for r in report.providers]
    if report.tags:
        lines.append(t("stats.section.tags"))
        lines += [_line(r, r.name or t("stats.no_tag")) for r in report.tags]
    saved = report.savings
    if saved.worker_output_tokens:
        ratio = saved.worker_output_tokens / saved.envelope_tokens if saved.envelope_tokens else 0
        lines.append(t("stats.savings", worker=saved.worker_output_tokens,
                       chief=saved.envelope_tokens, ratio=f"{ratio:.1f}"))  # fmt: skip
    return "\n".join(lines)
