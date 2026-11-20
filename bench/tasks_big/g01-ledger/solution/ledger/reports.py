"""Reports over a ledger."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import parse_month, previous_month
from .money import format_amount, quantize, total
from .store import Ledger, daily_balances, months_between


@dataclass(frozen=True)
class MonthSummary:
    """Monthsummary."""
    month: str
    income: Decimal
    expenses: Decimal
    by_category: dict[str, Decimal]

    @property
    def net(self) -> Decimal:
        """Net."""
        return quantize(self.income + self.expenses)

    @property
    def savings_rate(self) -> Decimal | None:
        """Savings rate."""
        if self.income <= 0:
            return None
        return quantize(self.net / self.income * 100)


def monthly_summary(ledger: Ledger, month: str, account: str | None = None) -> MonthSummary:
    """Monthly summary."""
    parse_month(month)
    rows = ledger.transactions(month=month, account=account)
    income = total([t.amount for t in rows if t.amount > 0 and t.category != "transfer"])
    expenses = total([t.amount for t in rows if t.amount < 0 and t.category != "transfer"])
    by_category: dict[str, list[Decimal]] = defaultdict(list)
    for t in rows:
        if t.category != "transfer":
            by_category[t.category].append(t.amount)
    return MonthSummary(
        month=month,
        income=income,
        expenses=expenses,
        by_category={c: total(v) for c, v in sorted(by_category.items())},
    )


def summaries(ledger: Ledger, start: str, end: str) -> list[MonthSummary]:
    """Summaries."""
    return [monthly_summary(ledger, m) for m in months_between(start, end)]


def compare_months(ledger: Ledger, month: str) -> dict[str, Decimal]:
    """Compare months."""
    now = monthly_summary(ledger, month).by_category
    before = monthly_summary(ledger, previous_month(month)).by_category
    categories = sorted(set(now) | set(before))
    return {c: quantize(now.get(c, Decimal(0)) - before.get(c, Decimal(0))) for c in categories}


def top_merchants(ledger: Ledger, month: str | None = None, limit: int = 5) -> list[tuple[str, Decimal]]:
    """Top merchants."""
    spent: dict[str, list[Decimal]] = defaultdict(list)
    for t in ledger.transactions(month=month):
        if t.amount < 0 and t.category != "transfer":
            spent[_merchant(t.description)].append(-t.amount)
    ranked = sorted(((m, total(v)) for m, v in spent.items()), key=lambda p: (-p[1], p[0]))
    return ranked[:limit]


def _merchant(description: str) -> str:
    words = description.split()
    kept = [w for w in words if not any(ch.isdigit() for ch in w)]
    return " ".join(kept[:3]).title() or description.strip().title()


def frequent_descriptions(ledger: Ledger, minimum: int = 3) -> list[tuple[str, int]]:
    """Frequent descriptions."""
    counts = Counter(_merchant(t.description) for t in ledger.transactions())
    return sorted(((d, n) for d, n in counts.items() if n >= minimum), key=lambda p: (-p[1], p[0]))


def largest_expenses(ledger: Ledger, month: str | None = None, limit: int = 10) -> list[tuple[date, str, Decimal]]:
    """Largest expenses."""
    rows = [t for t in ledger.transactions(month=month) if t.amount < 0]
    rows.sort(key=lambda t: (t.amount, t.date))
    return [(t.date, t.description, t.amount) for t in rows[:limit]]


def balance_history(ledger: Ledger, account_id: str, start: date, end: date, step_days: int = 7) -> list[tuple[date, Decimal]]:
    """Balance history."""
    if step_days <= 0:
        raise ValueError("step_days must be positive")
    days = daily_balances(ledger, account_id, start, end)
    picked = [d for i, d in enumerate(sorted(days)) if i % step_days == 0]
    if end not in picked:
        picked.append(end)
    return [(d, days[d]) for d in picked]


def average_monthly_spend(ledger: Ledger, category: str, months: list[str]) -> Decimal:
    """Average monthly spend."""
    if not months:
        return Decimal("0.00")
    sums = [
        -total([t.amount for t in ledger.transactions(month=m, category=category) if t.amount < 0])
        for m in months
    ]
    return quantize(total(sums) / len(months))


def render_table(rows: list[tuple[str, ...]], headers: tuple[str, ...]) -> str:
    """Render table."""
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(cell)) for w, cell in zip(widths, row, strict=True)]
    def line(cells: tuple[str, ...]) -> str:
        """Line."""
        return "  ".join(
            cell.rjust(w) if i else cell.ljust(w) for i, (cell, w) in enumerate(zip(cells, widths, strict=True))
        ).rstrip()
    out = [line(headers), "  ".join("-" * w for w in widths)]
    out += [line(row) for row in rows]
    return "\n".join(out)


def render_summary(summary: MonthSummary) -> str:
    """Render summary."""
    rows = [(c, format_amount(v)) for c, v in summary.by_category.items()]
    table = render_table(rows, ("category", "total"))
    rate = "-" if summary.savings_rate is None else f"{summary.savings_rate}%"
    lines = [
        f"Month {summary.month}",
        table,
        "",
        f"income   {format_amount(summary.income)}",
        f"expenses {format_amount(summary.expenses)}",
        f"net      {format_amount(summary.net, sign=True)}",
        f"savings  {rate}",
    ]
    return "\n".join(lines)


def render_balances(ledger: Ledger, as_of: date | None = None) -> str:
    """Render balances."""
    rows = [(a.id, a.name, format_amount(ledger.balance(a.id, as_of))) for a in ledger.accounts()]
    rows.append(("", "net worth", format_amount(ledger.net_worth(as_of))))
    return render_table(rows, ("account", "name", "balance"))


def export_summary_csv(ledger: Ledger, month: str, path: Path) -> None:
    """Write the month's totals per category as ``category,total`` CSV."""
    summary = monthly_summary(ledger, month)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["category", "total"])
        for category in sorted(summary.by_category):
            writer.writerow([category, f"{summary.by_category[category]:.2f}"])
