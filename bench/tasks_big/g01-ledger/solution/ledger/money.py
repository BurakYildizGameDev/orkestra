"""Amounts: parsing bank exports and formatting for reports.

All money is kept as ``Decimal`` with two places. Expenses are negative, income positive.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
CURRENCY_SYMBOLS = ("$", "€", "£", "₺")
CURRENCY_CODES = ("USD", "EUR", "GBP", "TRY")


class AmountError(ValueError):
    """An amount that cannot be read."""


def quantize(value: Decimal) -> Decimal:
    """Round to cents, half up (the bank's rule)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _strip_currency(text: str) -> str:
    cleaned = text.strip()
    for symbol in CURRENCY_SYMBOLS:
        cleaned = cleaned.replace(symbol, "")
    for code in CURRENCY_CODES:
        if cleaned.upper().endswith(code):
            cleaned = cleaned[: -len(code)]
        if cleaned.upper().startswith(code):
            cleaned = cleaned[len(code) :]
    return cleaned.strip()


def parse_amount(text: str) -> Decimal:
    """Read an amount as the bank exports it: ``-12.50``, ``+3``, ``$ 4.10``, ``7.00 EUR``."""
    if text is None:
        raise AmountError("missing amount")
    cleaned = _strip_currency(str(text))
    if not cleaned:
        raise AmountError(f"empty amount {text!r}")
    cleaned = cleaned.replace(" ", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    if not _NUMBER.match(cleaned):
        raise AmountError(f"invalid amount {text!r}")
    cleaned = cleaned.replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise AmountError(f"invalid amount {text!r}") from exc
    if not value.is_finite():
        raise AmountError(f"invalid amount {text!r}")
    return quantize(-value if negative else value)


_NUMBER = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$|^[+-]?\.\d+$")


def format_amount(value: Decimal, *, sign: bool = False, symbol: str = "") -> str:
    """``-1234.5`` -> ``-1,234.50``; with ``sign`` positive amounts get a ``+``."""
    value = quantize(value)
    body = f"{abs(value):,.2f}"
    prefix = "-" if value < 0 else ("+" if sign and value > 0 else "")
    return f"{prefix}{symbol}{body}"


def total(values: list[Decimal]) -> Decimal:
    """Sum of amounts, rounded to cents."""
    return quantize(sum(values, Decimal("0")))


def split_evenly(value: Decimal, parts: int) -> list[Decimal]:
    """Split an amount into ``parts`` shares that add up exactly (the first ones get the extra
    cents)."""
    if parts <= 0:
        raise ValueError("parts must be positive")
    cents = int((quantize(value) * 100).to_integral_value())
    base, extra = divmod(abs(cents), parts)
    sign = -1 if cents < 0 else 1
    shares = [base + (1 if i < extra else 0) for i in range(parts)]
    return [Decimal(sign * share) / 100 for share in shares]


_PERCENT = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*%\s*$")


def parse_percent(text: str) -> Decimal:
    """``"12.5%"`` -> ``Decimal("0.125")``."""
    match = _PERCENT.match(text)
    if not match:
        raise AmountError(f"invalid percent {text!r}")
    return Decimal(match.group(1)) / 100


def apply_percent(value: Decimal, percent: Decimal) -> Decimal:
    """The share of ``value`` given by ``percent`` (0.1 = 10 %), rounded to cents."""
    return quantize(value * percent)
