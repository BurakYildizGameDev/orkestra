"""Importing bank CSV exports into a ledger.

Every bank names its columns differently; a ``Profile`` maps them. Rows that cannot be read
are skipped and logged (the nightly job's log is ``logs/import-<date>.log``), never fatal.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .models import CATEGORIES, LedgerError, Transaction, guess_category
from .money import AmountError, parse_amount
from .store import Ledger

log = logging.getLogger("ledger.importer")

DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y")


@dataclass(frozen=True)
class Profile:
    """How one bank's export looks."""

    name: str
    date_column: str = "Date"
    amount_column: str = "Amount"
    description_column: str = "Description"
    category_column: str | None = None
    account_column: str | None = None
    delimiter: str = ","
    date_format: str | None = None
    negate: bool = False  # some cards export expenses as positive numbers


PROFILES: dict[str, Profile] = {
    "generic": Profile("generic"),
    "northbank": Profile(
        "northbank",
        date_column="Booking date",
        amount_column="Amount",
        description_column="Payee",
        category_column="Category",
        account_column="Account",
        date_format="%d.%m.%Y",
    ),
    "cardco": Profile(
        "cardco",
        date_column="Posted",
        amount_column="Charge",
        description_column="Merchant",
        date_format="%m/%d/%Y",
        negate=True,
    ),
    "eurosave": Profile(
        "eurosave",
        date_column="Datum",
        amount_column="Betrag",
        description_column="Verwendungszweck",
        delimiter=";",
        date_format="%d.%m.%Y",
    ),
}


@dataclass
class Skipped:
    row: int
    reason: str
    raw: dict[str, str]


@dataclass
class ImportResult:
    imported: int = 0
    duplicates: int = 0
    skipped: list[Skipped] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return self.imported + self.duplicates + len(self.skipped)


class ImportError_(LedgerError):
    """The file itself cannot be read (missing columns, wrong profile)."""


def parse_date(text: str, date_format: str | None = None) -> date:
    text = text.strip()
    formats = (date_format,) if date_format else DATE_FORMATS
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"invalid date {text!r}")


def _required_columns(profile: Profile) -> list[str]:
    columns = [profile.date_column, profile.amount_column, profile.description_column]
    if profile.account_column:
        columns.append(profile.account_column)
    return columns


def _row_to_transaction(raw: dict[str, str], profile: Profile, default_account: str) -> Transaction:
    when = parse_date(raw[profile.date_column], profile.date_format)
    amount = parse_amount(raw[profile.amount_column])
    if profile.negate:
        amount = -amount
    description = " ".join(raw[profile.description_column].split())
    category = "other"
    if profile.category_column and raw.get(profile.category_column):
        category = raw[profile.category_column].strip().lower()
        if category not in CATEGORIES:
            category = guess_category(description)
    else:
        category = guess_category(description)
    account = default_account
    if profile.account_column:
        account = raw[profile.account_column].strip()
    return Transaction(when, account, amount, description, category)


def read_rows(text: str, profile: Profile) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text), delimiter=profile.delimiter)
    missing = [c for c in _required_columns(profile) if c not in (reader.fieldnames or [])]
    if missing:
        raise ImportError_(f"{profile.name}: missing column(s) {', '.join(missing)}")
    return [dict(row) for row in reader]


def import_rows(
    ledger: Ledger,
    rows: Iterable[dict[str, str]],
    profile: Profile,
    *,
    default_account: str = "main",
    first_row: int = 2,
) -> ImportResult:
    result = ImportResult()
    for number, raw in enumerate(rows, start=first_row):
        try:
            transaction = _row_to_transaction(raw, profile, default_account)
        except AmountError as exc:
            reason = str(exc)
        except (ValueError, KeyError, LedgerError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
        else:
            if not ledger.has_account(transaction.account):
                reason = f"unknown account {transaction.account!r}"
            elif ledger.add(transaction):
                result.imported += 1
                continue
            else:
                result.duplicates += 1
                log.debug("row %d: duplicate of an earlier transaction", number)
                continue
        result.skipped.append(Skipped(number, reason, raw))
        log.error("row %d skipped (%s): %s", number, profile.name, reason)
    log.info(
        "import done (%s): %d imported, %d duplicates, %d skipped",
        profile.name,
        result.imported,
        result.duplicates,
        len(result.skipped),
    )
    return result


def import_text(
    ledger: Ledger, text: str, profile: str | Profile = "generic", *, default_account: str = "main"
) -> ImportResult:
    chosen = PROFILES[profile] if isinstance(profile, str) else profile
    return import_rows(ledger, read_rows(text, chosen), chosen, default_account=default_account)


def import_file(
    ledger: Ledger, path: Path, profile: str | Profile = "generic", *, default_account: str = "main"
) -> ImportResult:
    text = path.read_text(encoding="utf-8-sig")
    log.info("importing %s", path.name)
    return import_text(ledger, text, profile, default_account=default_account)


def detect_profile(text: str) -> str:
    """The profile whose columns all appear in the header line; ``generic`` otherwise."""
    header = text.splitlines()[0] if text else ""
    for name, profile in PROFILES.items():
        if name == "generic":
            continue
        columns = header.split(profile.delimiter)
        if all(c in columns for c in _required_columns(profile)):
            return name
    return "generic"
