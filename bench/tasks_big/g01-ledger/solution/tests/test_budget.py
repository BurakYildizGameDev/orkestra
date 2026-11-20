from decimal import Decimal

import pytest

from ledger.budget import Budget, check_budgets
from ledger.models import LedgerError
from ledger.store import Ledger


def test_spent_counts_expenses_only(ledger: Ledger) -> None:
    [s] = check_budgets(ledger, [Budget("groceries", Decimal("200"))], "2026-10")
    assert s.spent == Decimal("130.75") and s.remaining == Decimal("69.25") and not s.over


def test_overspent(ledger: Ledger) -> None:
    [s] = check_budgets(ledger, [Budget("rent", Decimal("800"))], "2026-10")
    assert s.over and s.remaining == Decimal("-100.00")


def test_sorted_by_category(ledger: Ledger) -> None:
    found = check_budgets(ledger, [Budget("rent", Decimal("1")), Budget("dining", Decimal("1"))],
                          "2026-10")
    assert [s.category for s in found] == ["dining", "rent"]


def test_rollover(ledger: Ledger) -> None:
    [s] = check_budgets(ledger, [Budget("groceries", Decimal("100"), rollover=True)], "2026-10")
    assert s.limit == Decimal("154.80")  # 100 + (100 - 45.20)


def test_bad_month(ledger: Ledger) -> None:
    with pytest.raises(LedgerError):
        check_budgets(ledger, [], "2026-00")
