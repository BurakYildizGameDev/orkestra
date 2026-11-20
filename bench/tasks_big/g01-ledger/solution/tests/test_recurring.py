from datetime import date
from decimal import Decimal

import pytest

from ledger.models import LedgerError
from ledger.recurring import RecurringRule, apply_rules, occurrences
from ledger.store import Ledger

RENT = RecurringRule("Rent", "main", Decimal("-900"), "rent", "monthly", 31)


def test_month_end_is_clamped() -> None:
    assert occurrences(RENT, date(2026, 2, 1), date(2026, 3, 31)) == [date(2026, 2, 28),
                                                                      date(2026, 3, 31)]


def test_weekly() -> None:
    rule = RecurringRule("Gym", "main", Decimal("-5"), "health", "weekly", 0)
    assert occurrences(rule, date(2026, 11, 1), date(2026, 11, 10)) == [date(2026, 11, 2),
                                                                        date(2026, 11, 9)]


def test_empty_range() -> None:
    assert occurrences(RENT, date(2026, 3, 1), date(2026, 2, 1)) == []


def test_bad_rule() -> None:
    with pytest.raises(LedgerError):
        RecurringRule("x", "main", Decimal("-1"), "other", "yearly", 1)


def test_apply_is_idempotent(ledger: Ledger) -> None:
    assert apply_rules(ledger, [RENT], date(2026, 11, 1), date(2026, 12, 31)) == 2
    assert apply_rules(ledger, [RENT], date(2026, 11, 1), date(2026, 12, 31)) == 0
