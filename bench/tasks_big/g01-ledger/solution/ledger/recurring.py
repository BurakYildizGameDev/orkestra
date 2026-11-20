"""Recurring transactions: rent on the 1st, a subscription every Monday."""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .models import LedgerError, Transaction
from .store import Ledger

EVERY = ("monthly", "weekly")


@dataclass(frozen=True)
class RecurringRule:
    """A transaction that repeats every month (on a day) or every week (on a weekday)."""

    description: str
    account: str
    amount: Decimal
    category: str
    every: str
    day: int

    def __post_init__(self) -> None:
        if self.every not in EVERY:
            raise LedgerError(f"unknown repetition {self.every!r}")
        low, high = (1, 31) if self.every == "monthly" else (0, 6)
        if not low <= self.day <= high:
            raise LedgerError(f"day {self.day} is out of range for {self.every}")


def _monthly(rule: RecurringRule, start: date, end: date) -> list[date]:
    found = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        last = calendar.monthrange(year, month)[1]
        due = date(year, month, min(rule.day, last))
        if start <= due <= end:
            found.append(due)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return found


def _weekly(rule: RecurringRule, start: date, end: date) -> list[date]:
    due = start + timedelta(days=(rule.day - start.weekday()) % 7)
    found = []
    while due <= end:
        found.append(due)
        due += timedelta(days=7)
    return found


def occurrences(rule: RecurringRule, start: date, end: date) -> list[date]:
    """Every due date of ``rule`` in ``[start, end]``."""
    if end < start:
        return []
    return _monthly(rule, start, end) if rule.every == "monthly" else _weekly(rule, start, end)


def apply_rules(ledger: Ledger, rules: Iterable[RecurringRule], start: date, end: date) -> int:
    """Add the due transactions of every rule; returns how many were new."""
    added = 0
    for rule in rules:
        for due in occurrences(rule, start, end):
            added += ledger.add(
                Transaction(due, rule.account, rule.amount, rule.description, rule.category)
            )
    return added
