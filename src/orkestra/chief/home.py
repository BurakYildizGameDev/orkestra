"""Data layer for the Orkestra web interface home screen (Faz 11c-b).

Provides `home_summary(config, conn, now, environ, doctor_report) -> HomeSummary`.
Does not make network calls.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from orkestra.chief import limits
from orkestra.config.schema import Config, OpenAICompatProvider
from orkestra.doctor import DoctorReport
from orkestra.i18n import t
from orkestra.providers import registry
from orkestra.queue import store as queue_store
from orkestra.state import health, stats
from orkestra.workspace import service

QUEUE_FAILED_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class ProviderHomeRow:
    name: str
    type: str
    status: str  # "ready" | "paused" | "no_consent" | "no_key" | "disabled"
    status_text: str
    is_local: bool
    local_text: str | None
    limits_text: str | None
    doctor_status: str | None = None  # "ok" | "warn" | "fail" | None
    doctor_message: str | None = None


@dataclass(frozen=True)
class TodayStats:
    runs: int
    cost_usd: float
    savings_worker_tokens: int = 0
    savings_envelope_tokens: int = 0


@dataclass(frozen=True)
class ClaudeWindowHome:
    name: str
    label: str
    used: float
    resets_at: str | None
    eta_s: int | None


@dataclass(frozen=True)
class PendingHome:
    unapplied_runs: int
    queue_pending: int
    queue_running: int
    queue_failed: int


@dataclass(frozen=True)
class HomeSummary:
    status: str  # "ok" | "warn" | "fail" (green / yellow / red)
    status_text: str
    providers: list[ProviderHomeRow]
    today: TodayStats
    claude_windows: list[ClaudeWindowHome]
    pending: PendingHome
    next_step: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _format_limits(row: registry.ProviderRow) -> str:
    parts = [
        f"{limit.limit.removeprefix('daily_')} {limit.used:g}/{limit.value:g}"
        for limit in row.limits
    ]
    if not parts:
        cost = f"{row.used.cost_usd:.4f}"
        parts = [t("status.budget.used", requests=row.used.requests, cost=cost)]
    return ", ".join(parts)


def _provider_key_var(cfg: Any) -> str:
    if isinstance(cfg, OpenAICompatProvider) and cfg.api_key_env:
        return cfg.api_key_env
    return "API_KEY"


def home_summary(
    config: Config,
    conn: sqlite3.Connection,
    now: datetime,
    environ: Mapping[str, str] | None = None,
    doctor_report: DoctorReport | None = None,
) -> HomeSummary:
    env = os.environ if environ is None else environ

    # 1. Providers
    doctor_map: dict[str, tuple[str, str]] = {}
    if doctor_report is not None:
        for check in doctor_report.checks:
            if check.name.startswith("provider:"):
                p_name = check.name.removeprefix("provider:")
                doctor_map[p_name] = (check.status, check.message)

    overview = registry.provider_overview(config, conn, now, env)
    provider_rows: list[ProviderHomeRow] = []

    for row in overview:
        if not row.enabled:
            st = "disabled"
            st_text = t("home.provider.disabled")
        elif row.consent != "granted":
            st = "no_consent"
            st_text = t("home.provider.no_consent")
        elif row.key_present is False:
            st = "no_key"
            st_text = t("home.provider.no_key")
        elif row.health.is_open(now):
            st = "paused"
            if row.health.open_until is not None:
                if row.health.reason == "quota":
                    st_text = t(
                        "home.provider.paused_quota",
                        until=health.until_text(row.health.open_until, now),
                    )
                else:
                    st_text = t(
                        "home.provider.paused_until",
                        time=f"{row.health.open_until:%H:%M}",
                    )
            else:
                st_text = t("home.provider.paused")
        else:
            st = "ready"
            st_text = t("home.provider.ready")

        is_local = bool(row.local)
        local_text = t("home.provider.local_free") if is_local else None
        limits_text = _format_limits(row)

        doc_status, doc_msg = doctor_map.get(row.name, (None, None))

        provider_rows.append(
            ProviderHomeRow(
                name=row.name,
                type=row.type,
                status=st,
                status_text=st_text,
                is_local=is_local,
                local_text=local_text,
                limits_text=limits_text,
                doctor_status=doc_status,
                doctor_message=doc_msg,
            )
        )

    # 2. Today's stats
    start_of_today = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
    stats_rep = stats.collect(conn, since=start_of_today, now=now)
    today = TodayStats(
        runs=stats_rep.totals.runs,
        cost_usd=round(stats_rep.totals.cost_usd, 4),
        savings_worker_tokens=stats_rep.savings.worker_output_tokens,
        savings_envelope_tokens=stats_rep.savings.envelope_tokens,
    )

    # 3. Claude usage windows (if available)
    raw_windows = limits.status_windows(now)
    claude_windows = [
        ClaudeWindowHome(
            name=w.name,
            label=w.label,
            used=w.used,
            resets_at=w.resets_at.isoformat() if w.resets_at else None,
            eta_s=round(w.eta_s) if w.eta_s is not None else None,
        )
        for w in raw_windows
    ]

    # 4. Pending items
    unapplied = len(service.unapplied_runs(conn))
    q_counts = queue_store.counts(conn, failed_since=now - QUEUE_FAILED_WINDOW)
    pending = PendingHome(
        unapplied_runs=unapplied,
        queue_pending=q_counts["pending"],
        queue_running=q_counts["running"],
        queue_failed=q_counts["failed"],
    )

    # 5. Overall status and next step
    enabled_providers = [p for p in provider_rows if p.status != "disabled"]
    ready_providers = [p for p in enabled_providers if p.status == "ready"]

    if not config.providers:
        overall_status = "fail"
        overall_text = t("home.status.no_providers")
        next_step = t("home.next_step.no_providers")
    elif not enabled_providers:
        overall_status = "fail"
        overall_text = t("home.status.all_disabled")
        next_step = t("home.next_step.no_providers")
    elif not ready_providers:
        overall_status = "fail"
        overall_text = t("home.status.no_ready_providers")
        # Check specific reason for blocked providers
        first_no_consent = next((p for p in enabled_providers if p.status == "no_consent"), None)
        first_no_key = next((p for p in enabled_providers if p.status == "no_key"), None)
        if first_no_consent is not None:
            next_step = t("home.next_step.grant_consent", provider=first_no_consent.name)
        elif first_no_key is not None:
            cfg = config.providers[first_no_key.name]
            key_var = _provider_key_var(cfg)
            next_step = t("home.next_step.set_key", provider=first_no_key.name, env=key_var)
        else:
            next_step = t("home.next_step.wait_or_reset")
    elif (
        any(p.status in ("no_consent", "no_key", "paused") for p in enabled_providers)
        or pending.unapplied_runs > 0
        or pending.queue_failed > 0
    ):
        overall_status = "warn"
        first_no_consent = next((p for p in enabled_providers if p.status == "no_consent"), None)
        first_no_key = next((p for p in enabled_providers if p.status == "no_key"), None)
        first_paused = next((p for p in enabled_providers if p.status == "paused"), None)

        if first_no_consent is not None:
            overall_text = t("home.status.warn_consent", provider=first_no_consent.name)
            next_step = t("home.next_step.grant_consent", provider=first_no_consent.name)
        elif first_no_key is not None:
            overall_text = t("home.status.warn_key", provider=first_no_key.name)
            cfg = config.providers[first_no_key.name]
            key_var = _provider_key_var(cfg)
            next_step = t("home.next_step.set_key", provider=first_no_key.name, env=key_var)
        elif first_paused is not None:
            overall_text = t("home.status.warn_paused", provider=first_paused.name)
            if pending.unapplied_runs > 0:
                next_step = t("home.next_step.unapplied", count=pending.unapplied_runs)
            elif pending.queue_pending > 0:
                next_step = t("home.next_step.queue", pending=pending.queue_pending)
            else:
                next_step = t("home.next_step.ready")
        elif pending.queue_failed > 0:
            overall_text = t("home.status.warn_queue_failed", count=pending.queue_failed)
            if pending.unapplied_runs > 0:
                next_step = t("home.next_step.unapplied", count=pending.unapplied_runs)
            elif pending.queue_pending > 0:
                next_step = t("home.next_step.queue", pending=pending.queue_pending)
            else:
                next_step = t("home.next_step.ready")
        else:
            overall_text = t("home.status.warn_unapplied", count=pending.unapplied_runs)
            next_step = t("home.next_step.unapplied", count=pending.unapplied_runs)
    else:
        overall_status = "ok"
        overall_text = t("home.status.ok")
        if pending.unapplied_runs > 0:
            next_step = t("home.next_step.unapplied", count=pending.unapplied_runs)
        elif pending.queue_pending > 0:
            next_step = t("home.next_step.queue", pending=pending.queue_pending)
        else:
            next_step = t("home.next_step.ready")

    return HomeSummary(
        status=overall_status,
        status_text=overall_text,
        providers=provider_rows,
        today=today,
        claude_windows=claude_windows,
        pending=pending,
        next_step=next_step,
    )
