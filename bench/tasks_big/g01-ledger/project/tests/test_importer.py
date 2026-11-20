from decimal import Decimal

import pytest

from ledger import importer
from ledger.store import Ledger

NORTHBANK = """Booking date,Payee,Amount,Category,Account
01.11.2026,Migros 0412,-23.40,groceries,main
02.11.2026,Payroll ACME,2500.00,salary,main
02.11.2026,Cafe Nero 22,-4.50,Food,card
"""

CARDCO = """Posted,Merchant,Charge
11/03/2026,Netflix.com,12.99
11/04/2026,Uber Trip 77,8.20
"""


def test_northbank_rows_are_imported(ledger: Ledger) -> None:
    result = importer.import_text(ledger, NORTHBANK, "northbank")
    assert (result.imported, result.duplicates, len(result.skipped)) == (3, 0, 0)
    cafe = ledger.transactions(month="2026-11", account="card")[0]
    assert cafe.category == "dining"  # "Food" is unknown: guessed from the payee


def test_importing_twice_counts_duplicates(ledger: Ledger) -> None:
    importer.import_text(ledger, NORTHBANK, "northbank")
    again = importer.import_text(ledger, NORTHBANK, "northbank")
    assert again.imported == 0 and again.duplicates == 3


def test_cardco_charges_are_expenses(ledger: Ledger) -> None:
    importer.import_text(ledger, CARDCO, "cardco", default_account="card")
    amounts = [t.amount for t in ledger.transactions(month="2026-11")]
    assert amounts == [Decimal("-12.99"), Decimal("-8.20")]


def test_unknown_account_is_skipped_not_fatal(ledger: Ledger) -> None:
    text = NORTHBANK.replace(",main\n02.11", ",acct-9\n02.11", 1)
    result = importer.import_text(ledger, text, "northbank")
    assert result.imported == 2 and result.skipped[0].reason == "unknown account 'acct-9'"


def test_missing_columns_are_an_error(ledger: Ledger) -> None:
    with pytest.raises(importer.ImportError_):
        importer.import_text(ledger, "Date,Amount\n2026-11-01,1\n", "generic")


def test_detect_profile() -> None:
    assert importer.detect_profile(NORTHBANK) == "northbank"
    assert importer.detect_profile(CARDCO) == "cardco"
    assert importer.detect_profile("Date,Amount,Description\n") == "generic"
