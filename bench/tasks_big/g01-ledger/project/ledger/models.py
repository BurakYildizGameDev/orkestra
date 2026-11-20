"""The ledger's records: accounts, transactions, categories."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ACCOUNT_KINDS = ("checking", "savings", "credit", "cash")

CATEGORIES = (
    "groceries",
    "rent",
    "utilities",
    "transport",
    "dining",
    "health",
    "entertainment",
    "salary",
    "transfer",
    "other",
)

# Merchant words the importer uses to guess a category when the export has none.
CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "groceries": ("market", "grocer", "bakery", "migros", "carrefour", "bim"),
    "rent": ("rent", "landlord", "property"),
    "utilities": ("electric", "water", "gas co", "internet", "phone"),
    "transport": ("metro", "bus", "taxi", "fuel", "uber", "parking"),
    "dining": ("cafe", "restaurant", "pizza", "burger", "kebab", "coffee"),
    "health": ("pharmacy", "clinic", "dentist", "hospital"),
    "entertainment": ("cinema", "concert", "steam", "netflix", "spotify"),
    "salary": ("salary", "payroll"),
    "transfer": ("transfer", "atm"),
}


class LedgerError(Exception):
    """A record that breaks the ledger's rules."""


@dataclass(frozen=True)
class Account:
    """A bank account, card or cash wallet."""

    id: str
    name: str
    kind: str = "checking"
    currency: str = "EUR"
    opening_balance: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        if not self.id or not self.id.replace("-", "").replace("_", "").isalnum():
            raise LedgerError(f"invalid account id {self.id!r}")
        if self.kind not in ACCOUNT_KINDS:
            raise LedgerError(f"unknown account kind {self.kind!r}")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise LedgerError(f"invalid currency {self.currency!r}")


@dataclass(frozen=True)
class Transaction:
    """One movement of money. Expenses are negative, income positive."""

    date: date
    account: str
    amount: Decimal
    description: str
    category: str = "other"
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise LedgerError(f"unknown category {self.category!r}")
        if not self.description.strip():
            raise LedgerError("a transaction needs a description")

    @property
    def month(self) -> str:
        """``YYYY-MM`` of the transaction's date."""
        return f"{self.date.year:04d}-{self.date.month:02d}"

    @property
    def is_expense(self) -> bool:
        return self.amount < 0

    def key(self) -> str:
        """A stable identity: same date, account, amount and description = same transaction."""
        text = f"{self.date.isoformat()}|{self.account}|{self.amount}|{self.description.strip()}"
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, object]:
        return {
            "date": self.date.isoformat(),
            "account": self.account,
            "amount": str(self.amount),
            "description": self.description,
            "category": self.category,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Transaction:
        tags = data.get("tags") or []
        return cls(
            date=date.fromisoformat(str(data["date"])),
            account=str(data["account"]),
            amount=Decimal(str(data["amount"])),
            description=str(data["description"]),
            category=str(data.get("category", "other")),
            tags=tuple(str(t) for t in tags),  # type: ignore[union-attr]
        )


def guess_category(description: str) -> str:
    """The category whose hint words appear in the description; ``other`` when none does."""
    text = description.lower()
    for category, words in CATEGORY_HINTS.items():
        if any(word in text for word in words):
            return category
    return "other"


def month_of(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def parse_month(text: str) -> tuple[int, int]:
    """``"2026-11"`` -> ``(2026, 11)``."""
    try:
        year_text, month_text = text.split("-")
        year, month = int(year_text), int(month_text)
    except ValueError as exc:
        raise LedgerError(f"invalid month {text!r} (expected YYYY-MM)") from exc
    if not 1 <= month <= 12 or year < 1900:
        raise LedgerError(f"invalid month {text!r} (expected YYYY-MM)")
    return year, month


def next_month(text: str) -> str:
    year, month = parse_month(text)
    year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return f"{year:04d}-{month:02d}"


def previous_month(text: str) -> str:
    year, month = parse_month(text)
    year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return f"{year:04d}-{month:02d}"
