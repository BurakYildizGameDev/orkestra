from decimal import Decimal

import pytest

from ledger.money import AmountError, format_amount, parse_amount, parse_percent, split_evenly


@pytest.mark.parametrize(
    ("text", "expected"),
    [("-12.50", "-12.50"), ("+3", "3.00"), ("$ 4.10", "4.10"), ("7.00 EUR", "7.00"), ("0.005", "0.01")],
)
def test_parse_amount(text: str, expected: str) -> None:
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["", "abc", "EUR", "nan"])
def test_bad_amounts_raise(text: str) -> None:
    with pytest.raises(AmountError):
        parse_amount(text)


def test_format_amount() -> None:
    assert format_amount(Decimal("-1234.5")) == "-1,234.50"
    assert format_amount(Decimal("3"), sign=True) == "+3.00"


def test_split_evenly_adds_up() -> None:
    shares = split_evenly(Decimal("10.00"), 3)
    assert shares == [Decimal("3.34"), Decimal("3.33"), Decimal("3.33")]
    assert sum(shares) == Decimal("10.00")


def test_parse_percent() -> None:
    assert parse_percent("12.5%") == Decimal("0.125")
