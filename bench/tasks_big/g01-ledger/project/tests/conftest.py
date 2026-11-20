from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ledger.models import Account, Transaction
from ledger.store import Ledger


def tx(day: str, amount: str, description: str, category: str = "other", account: str = "main") -> Transaction:
    return Transaction(date.fromisoformat(day), account, Decimal(amount), description, category)


@pytest.fixture
def ledger() -> Ledger:
    book = Ledger()
    book.add_account(Account("main", "Main checking", opening_balance=Decimal("100.00")))
    book.add_account(Account("card", "Credit card", kind="credit"))
    book.add_many(
        [
            tx("2026-09-01", "2500.00", "Payroll ACME", "salary"),
            tx("2026-09-03", "-900.00", "Landlord Ltd", "rent"),
            tx("2026-09-05", "-45.20", "Migros 0412", "groceries"),
            tx("2026-09-18", "-12.00", "Cafe Nero", "dining", "card"),
            tx("2026-10-01", "2500.00", "Payroll ACME", "salary"),
            tx("2026-10-03", "-900.00", "Landlord Ltd", "rent"),
            tx("2026-10-07", "-130.75", "Migros 0412", "groceries"),
            tx("2026-10-09", "-60.00", "Metro Card Topup", "transport"),
            tx("2026-10-20", "-200.00", "Transfer to card", "transfer"),
            tx("2026-10-20", "200.00", "Transfer from main", "transfer", "card"),
            tx("2026-10-22", "-38.50", "Kebab House", "dining", "card"),
        ]
    )
    return book
