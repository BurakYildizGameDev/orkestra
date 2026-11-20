"""Monthly budgets per category, with optional rollover of what was left."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from .models import next_month, parse_month
from .money import quantize, total
from .store import Ledger


@dataclass(frozen=True)
class Budget:
    """How much a category may spend per month."""

    category: str
    monthly_limit: Decimal
    rollover: bool = False


@dataclass(frozen=True)
class BudgetStatus:
    """One budget in one month."""

    category: str
    limit: Decimal
    spent: Decimal
    remaining: Decimal
    over: bool


def spent_in(ledger: Ledger, category: str, month: str) -> Decimal:
    """Expenses of a category in a month, as a positive number."""
    rows = ledger.transactions(month=month, category=category)
    return -total([t.amount for t in rows if t.amount < 0])


def limit_for(ledger: Ledger, budget: Budget, month: str) -> Decimal:
    """The month's limit, with what earlier months left when the budget rolls over."""
    limit = quantize(Decimal(budget.monthly_limit))
    months = ledger.months()
    if not budget.rollover or not months or months[0] >= month:
        return limit
    current = months[0]
    available = limit
    while current < month:
        left = available - spent_in(ledger, budget.category, current)
        available = quantize(limit + max(Decimal(0), left))
        current = next_month(current)
    return available


def check_budgets(ledger: Ledger, budgets: Iterable[Budget], month: str) -> list[BudgetStatus]:
    """The status of every budget in ``month`` (``YYYY-MM``), sorted by category."""
    parse_month(month)
    found = []
    for budget in budgets:
        limit = limit_for(ledger, budget, month)
        spent = spent_in(ledger, budget.category, month)
        found.append(BudgetStatus(budget.category, limit, spent, quantize(limit - spent),
                                  spent > limit))
    return sorted(found, key=lambda s: s.category)
