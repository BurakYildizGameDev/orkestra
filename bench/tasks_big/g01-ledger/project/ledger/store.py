from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import Account, LedgerError, Transaction, month_of, parse_month
from .money import quantize, total

FORMAT_VERSION = 2


class Ledger:
    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._transactions: list[Transaction] = []
        self._keys: set[str] = set()
        self._listeners: list[Callable[[Transaction], None]] = []

    # --- accounts ------------------------------------------------------------------------

    def add_account(self, account: Account) -> None:
        if account.id in self._accounts:
            raise LedgerError(f"account {account.id!r} already exists")
        self._accounts[account.id] = account

    def account(self, account_id: str) -> Account:
        try:
            return self._accounts[account_id]
        except KeyError:
            raise LedgerError(f"unknown account {account_id!r}") from None

    def has_account(self, account_id: str) -> bool:
        return account_id in self._accounts

    def accounts(self) -> list[Account]:
        return sorted(self._accounts.values(), key=lambda a: a.id)

    def remove_account(self, account_id: str) -> None:
        self.account(account_id)
        if any(t.account == account_id for t in self._transactions):
            raise LedgerError(f"account {account_id!r} still has transactions")
        del self._accounts[account_id]

    # --- transactions --------------------------------------------------------------------

    def subscribe(self, listener: Callable[[Transaction], None]) -> None:
        self._listeners.append(listener)

    def add(self, transaction: Transaction) -> bool:
        self.account(transaction.account)
        key = transaction.key()
        if key in self._keys:
            return False
        self._keys.add(key)
        self._transactions.append(transaction)
        for listener in self._listeners:
            listener(transaction)
        return True

    def add_many(self, transactions: Iterable[Transaction]) -> int:
        return sum(1 for t in transactions if self.add(t))

    def contains(self, transaction: Transaction) -> bool:
        return transaction.key() in self._keys

    def remove(self, transaction: Transaction) -> None:
        key = transaction.key()
        if key not in self._keys:
            raise LedgerError("no such transaction")
        self._keys.discard(key)
        self._transactions = [t for t in self._transactions if t.key() != key]

    def __len__(self) -> int:
        return len(self._transactions)

    def __iter__(self) -> Iterator[Transaction]:
        return iter(self.transactions())

    def transactions(
        self,
        *,
        account: str | None = None,
        month: str | None = None,
        category: str | None = None,
        start: date | None = None,
        end: date | None = None,
        tag: str | None = None,
    ) -> list[Transaction]:
        if month is not None:
            parse_month(month)
        found = [
            t
            for t in self._transactions
            if (account is None or t.account == account)
            and (month is None or t.month == month)
            and (category is None or t.category == category)
            and (start is None or t.date >= start)
            and (end is None or t.date <= end)
            and (tag is None or tag in t.tags)
        ]
        return sorted(found, key=lambda t: (t.date, t.account, t.description, t.amount))

    def months(self) -> list[str]:
        return sorted({t.month for t in self._transactions})

    def first_date(self) -> date | None:
        return min((t.date for t in self._transactions), default=None)

    def last_date(self) -> date | None:
        return max((t.date for t in self._transactions), default=None)

    # --- balances ------------------------------------------------------------------------

    def balance(self, account_id: str, as_of: date | None = None) -> Decimal:
        account = self.account(account_id)
        moves = [t.amount for t in self.transactions(account=account_id, end=as_of)]
        return quantize(account.opening_balance + total(moves))

    def balances(self, as_of: date | None = None) -> dict[str, Decimal]:
        return {a.id: self.balance(a.id, as_of) for a in self.accounts()}

    def net_worth(self, as_of: date | None = None) -> Decimal:
        return total(list(self.balances(as_of).values()))

    def totals_by_category(self, month: str | None = None) -> dict[str, Decimal]:
        sums: dict[str, list[Decimal]] = defaultdict(list)
        for t in self.transactions(month=month):
            sums[t.category].append(t.amount)
        return {category: total(values) for category, values in sorted(sums.items())}

    def totals_by_month(self, account: str | None = None) -> dict[str, Decimal]:
        sums: dict[str, list[Decimal]] = defaultdict(list)
        for t in self.transactions(account=account):
            sums[t.month].append(t.amount)
        return {month: total(values) for month, values in sorted(sums.items())}

    # --- editing -------------------------------------------------------------------------

    def recategorize(self, predicate: Callable[[Transaction], bool], category: str) -> int:
        changed = 0
        updated: list[Transaction] = []
        for t in self._transactions:
            if predicate(t) and t.category != category:
                t = Transaction(t.date, t.account, t.amount, t.description, category, t.tags)
                changed += 1
            updated.append(t)
        self._transactions = updated
        return changed

    def tag(self, predicate: Callable[[Transaction], bool], tag: str) -> int:
        changed = 0
        updated: list[Transaction] = []
        for t in self._transactions:
            if predicate(t) and tag not in t.tags:
                t = Transaction(t.date, t.account, t.amount, t.description, t.category,
                                (*t.tags, tag))
                changed += 1
            updated.append(t)
        self._transactions = updated
        return changed

    # --- files ---------------------------------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        return {
            "version": FORMAT_VERSION,
            "accounts": [
                {
                    "id": a.id,
                    "name": a.name,
                    "kind": a.kind,
                    "currency": a.currency,
                    "opening_balance": str(a.opening_balance),
                }
                for a in self.accounts()
            ],
            "transactions": [t.to_dict() for t in self.transactions()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Ledger:
        version = data.get("version", 1)
        if version not in (1, FORMAT_VERSION):
            raise LedgerError(f"unsupported ledger file version {version!r}")
        ledger = cls()
        for raw in data.get("accounts", []):  # type: ignore[union-attr]
            ledger.add_account(
                Account(
                    id=raw["id"],
                    name=raw["name"],
                    kind=raw.get("kind", "checking"),
                    currency=raw.get("currency", "EUR"),
                    opening_balance=Decimal(raw.get("opening_balance", "0.00")),
                )
            )
        for raw in data.get("transactions", []):  # type: ignore[union-attr]
            if version == 1 and "category" not in raw:
                raw = {**raw, "category": "other"}
            ledger.add(Transaction.from_dict(raw))
        return ledger

    def save(self, path: Path) -> None:
        text = json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text + "\n", encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Ledger:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def merge(first: Ledger, second: Ledger) -> Ledger:
    merged = Ledger()
    for account in [*first.accounts(), *second.accounts()]:
        if not merged.has_account(account.id):
            merged.add_account(account)
    merged.add_many(first.transactions())
    merged.add_many(second.transactions())
    return merged


def months_between(start: str, end: str) -> list[str]:
    year, month = parse_month(start)
    end_year, end_month = parse_month(end)
    months: list[str] = []
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def daily_balances(ledger: Ledger, account_id: str, start: date, end: date) -> dict[date, Decimal]:
    balances: dict[date, Decimal] = {}
    running = ledger.balance(account_id, date.fromordinal(start.toordinal() - 1))
    moves: dict[date, list[Decimal]] = defaultdict(list)
    for t in ledger.transactions(account=account_id, start=start, end=end):
        moves[t.date].append(t.amount)
    for ordinal in range(start.toordinal(), end.toordinal() + 1):
        day = date.fromordinal(ordinal)
        running = quantize(running + total(moves.get(day, [])))
        balances[day] = running
    return balances


def current_month(today: date | None = None) -> str:
    return month_of(today or date.today())
