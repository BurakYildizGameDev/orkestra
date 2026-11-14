"""Text and JSON for the ``queue`` commands, shared by the CLI and (Faz 12b) the interface."""

from __future__ import annotations

from typing import Any

from orkestra.config.schema import Config
from orkestra.i18n import t
from orkestra.notify import notify
from orkestra.queue import store
from orkestra.queue.service import ItemResult, QueueReport


def profile_text(item: store.QueueItem, config: Config | None) -> str:
    if item.profile is not None:
        return item.profile
    default = config.queue.default_profile if config is not None else "-"
    return t("queue.profile.default", profile=default)


def item_json(item: store.QueueItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "path": item.path,
        "kind": item.kind,
        "profile": item.profile,
        "status": item.status,
        "added_at": item.added_at,
        "started_at": item.started_at,
        "finished_at": item.finished_at,
        "result_ref": item.result_ref,
        "workdir": item.workdir,
        "note": item.note,
    }


def _extra(result_ref: str | None, note: str | None) -> str:
    extra = t("queue.list.ref", ref=result_ref) if result_ref else ""
    return extra + (t("queue.list.note", note=note) if note else "")


def added_text(item: store.QueueItem, config: Config) -> str:
    return t(
        "queue.added",
        id=item.id,
        kind=t(f"queue.kind.{item.kind}"),
        profile=profile_text(item, config),
        path=item.path,
    )


def list_lines(items: list[store.QueueItem], config: Config | None) -> list[str]:
    if not items:
        return [t("queue.empty")]
    return [
        t(
            "queue.list.line",
            id=item.id,
            status=t(f"queue.status.{item.status}"),
            kind=t(f"queue.kind.{item.kind}"),
            profile=profile_text(item, config),
            name=item.name,
            extra=_extra(item.result_ref, item.note),
        )
        for item in items
    ]


def result_line(item: store.QueueItem, result: ItemResult) -> str:
    return t(
        "queue.item.line",
        id=item.id,
        status=t(f"queue.status.{result.status}"),
        name=item.name,
        extra=_extra(result.result_ref, result.note),
    )


def summary_lines(
    report: QueueReport, *, until: str | None, max_cost_usd: float | None
) -> list[str]:
    lines: list[str] = []
    if report.recovered:
        lines.append(t("queue.recovered", count=report.recovered))
    lines.append(
        t(
            "queue.summary",
            done=len(report.done),
            failed=len(report.failed),
            skipped=len(report.skipped),
        )
    )
    if report.stopped == "until":
        lines.append(t("queue.stopped.until", until=until or "-"))
    elif report.stopped == "cost":
        lines.append(
            t(
                "queue.stopped.cost",
                spent=f"{report.spent_usd:.4f}",
                limit=f"{max_cost_usd or 0.0:.4f}",
            )
        )
    return lines


def report_json(report: QueueReport, deliveries: list[notify.Delivery]) -> dict[str, Any]:
    return {
        "done": report.done,
        "failed": report.failed,
        "skipped": report.skipped,
        "stopped": report.stopped,
        "spent_usd": round(report.spent_usd, 6),
        "recovered": report.recovered,
        "items": [
            {
                "id": item.id,
                "path": item.path,
                "kind": item.kind,
                "status": result.status,
                "result_ref": result.result_ref,
                "cost_usd": round(result.cost_usd, 6),
                "note": result.note,
                "warnings": list(result.warnings),
            }
            for item, result in report.results
        ],
        "notifications": deliveries_json(deliveries),
    }


def deliveries_json(deliveries: list[notify.Delivery]) -> list[dict[str, Any]]:
    return [{"channel": d.channel, "state": d.state, "reason": d.reason} for d in deliveries]
