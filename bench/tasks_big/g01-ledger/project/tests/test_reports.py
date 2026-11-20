from datetime import date
from decimal import Decimal

from ledger import reports
from ledger.store import Ledger


def test_monthly_summary_leaves_transfers_out(ledger: Ledger) -> None:
    summary = reports.monthly_summary(ledger, "2026-10")
    assert summary.income == Decimal("2500.00")
    assert summary.expenses == Decimal("-1129.25")
    assert "transfer" not in summary.by_category
    assert summary.savings_rate == Decimal("54.83")


def test_compare_months(ledger: Ledger) -> None:
    diff = reports.compare_months(ledger, "2026-10")
    assert diff["groceries"] == Decimal("-85.55") and diff["transport"] == Decimal("-60.00")


def test_top_merchants(ledger: Ledger) -> None:
    assert reports.top_merchants(ledger, "2026-10", 2) == [
        ("Landlord Ltd", Decimal("900.00")),
        ("Migros", Decimal("130.75")),
    ]


def test_balance_history_ends_on_the_last_day(ledger: Ledger) -> None:
    history = reports.balance_history(ledger, "main", date(2026, 10, 1), date(2026, 10, 10), 7)
    assert [d for d, _ in history] == [date(2026, 10, 1), date(2026, 10, 8), date(2026, 10, 10)]


def test_render_summary_mentions_every_category(ledger: Ledger) -> None:
    text = reports.render_summary(reports.monthly_summary(ledger, "2026-10"))
    for name in ("groceries", "rent", "transport", "dining", "salary"):
        assert name in text
    assert "net      +1,370.75" in text
