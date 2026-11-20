from datetime import date
from decimal import Decimal

import pytest

from ledger.models import LedgerError
from ledger.store import Ledger, daily_balances, merge, months_between

from .conftest import tx


def test_duplicates_are_ignored(ledger: Ledger) -> None:
    before = len(ledger)
    assert ledger.add(tx("2026-10-07", "-130.75", "Migros 0412", "groceries")) is False
    assert len(ledger) == before


def test_unknown_account_is_refused(ledger: Ledger) -> None:
    with pytest.raises(LedgerError):
        ledger.add(tx("2026-10-07", "-1.00", "x", account="nope"))


def test_balance_and_net_worth(ledger: Ledger) -> None:
    assert ledger.balance("main") == Decimal("2864.05")
    assert ledger.balance("card") == Decimal("149.50")
    assert ledger.balance("main", date(2026, 9, 30)) == Decimal("1654.80")
    assert ledger.net_worth() == Decimal("3013.55")


def test_filters(ledger: Ledger) -> None:
    assert [t.description for t in ledger.transactions(month="2026-09", category="rent")] == ["Landlord Ltd"]
    assert len(ledger.transactions(account="card")) == 3
    assert ledger.months() == ["2026-09", "2026-10"]


def test_totals_by_category(ledger: Ledger) -> None:
    totals = ledger.totals_by_category("2026-10")
    assert totals["groceries"] == Decimal("-130.75") and totals["transfer"] == Decimal("0.00")


def test_round_trip(ledger: Ledger, tmp_path) -> None:
    path = tmp_path / "book.json"
    ledger.save(path)
    again = Ledger.load(path)
    assert again.to_dict() == ledger.to_dict()


def test_merge_keeps_one_copy(ledger: Ledger) -> None:
    merged = merge(ledger, ledger)
    assert len(merged) == len(ledger)


def test_months_between() -> None:
    assert months_between("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_daily_balances(ledger: Ledger) -> None:
    days = daily_balances(ledger, "main", date(2026, 10, 1), date(2026, 10, 3))
    assert days[date(2026, 10, 3)] == Decimal("3254.80")


def test_recategorize(ledger: Ledger) -> None:
    changed = ledger.recategorize(lambda t: "Kebab" in t.description, "groceries")
    assert changed == 1
    assert ledger.totals_by_category("2026-10")["groceries"] == Decimal("-169.25")
