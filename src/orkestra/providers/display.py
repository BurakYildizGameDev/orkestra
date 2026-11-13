"""How a provider row reads for a person: ``providers list``, ``budget`` and ``orkestra ui``.

Shared so the command line and the terminal interface say the same thing (Faz 11b).
"""

from __future__ import annotations

from orkestra.i18n import t
from orkestra.providers import registry
from orkestra.state import db


def row_text(row: registry.ProviderRow) -> str:
    parts = [
        row.type,
        t("providers.enabled") if row.enabled else t("providers.disabled"),
        t(f"providers.consent.{row.consent}"),
    ]
    h = row.health
    if h.open_until is not None and h.is_open(db.local_now()):
        parts.append(t("providers.circuit_open", until=h.open_until.strftime("%H:%M")))
    elif h.consecutive_failures:
        parts.append(t("providers.failures", count=h.consecutive_failures))
    if row.key_env:
        key = "providers.key_present" if row.key_present else "providers.key_missing"
        parts.append(t(key, var=row.key_env))
    parts.extend(
        t("providers.budget_left", limit=s.limit, remaining=number(s.remaining)) for s in row.limits
    )
    return f"{row.name}: " + " | ".join(parts)


def number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.4f}"


def budget_text(row: registry.ProviderRow) -> str:
    if not row.limits:
        return t(
            "budget.unlimited", name=row.name, tokens=row.used.tokens, requests=row.used.requests
        )
    limits = ", ".join(
        t("budget.limit", limit=s.limit, used=number(s.used), value=number(s.value))
        for s in row.limits
    )
    return f"{row.name}: {limits}"
