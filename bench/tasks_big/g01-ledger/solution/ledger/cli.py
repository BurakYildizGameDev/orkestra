"""Command line: ``python -m ledger.cli <command> ...``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path

from . import importer, reports
from .budget import Budget, check_budgets
from .money import format_amount
from .models import Account, LedgerError
from .store import Ledger, current_month

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def _load(path: Path) -> Ledger:
    if not path.exists():
        return Ledger()
    return Ledger.load(path)


def cmd_init(args: argparse.Namespace) -> int:
    if args.ledger.exists() and not args.force:
        print(f"{args.ledger} exists (use --force)", file=sys.stderr)
        return EXIT_ERROR
    Ledger().save(args.ledger)
    print(f"created {args.ledger}")
    return EXIT_OK


def cmd_account(args: argparse.Namespace) -> int:
    ledger = _load(args.ledger)
    ledger.add_account(
        Account(args.id, args.name, args.kind, args.currency, Decimal(args.opening))
    )
    ledger.save(args.ledger)
    print(f"added account {args.id}")
    return EXIT_OK


def cmd_import(args: argparse.Namespace) -> int:
    ledger = _load(args.ledger)
    text = args.csv.read_text(encoding="utf-8-sig")
    profile = args.profile or importer.detect_profile(text)
    result = importer.import_text(ledger, text, profile, default_account=args.account)
    ledger.save(args.ledger)
    print(
        f"{result.imported} imported, {result.duplicates} duplicates, "
        f"{len(result.skipped)} skipped ({profile})"
    )
    for skipped in result.skipped[: args.show_skipped]:
        print(f"  row {skipped.row}: {skipped.reason}")
    return EXIT_OK if not result.skipped else EXIT_ERROR


def cmd_report(args: argparse.Namespace) -> int:
    ledger = _load(args.ledger)
    month = args.month or current_month()
    print(reports.render_summary(reports.monthly_summary(ledger, month, args.account)))
    return EXIT_OK


def cmd_balance(args: argparse.Namespace) -> int:
    ledger = _load(args.ledger)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    print(reports.render_balances(ledger, as_of))
    return EXIT_OK


def cmd_top(args: argparse.Namespace) -> int:
    ledger = _load(args.ledger)
    for merchant, spent in reports.top_merchants(ledger, args.month, args.limit):
        print(f"{merchant}: {spent}")
    return EXIT_OK


def cmd_budget(args: argparse.Namespace) -> int:
    ledger = _load(args.ledger)
    raw = json.loads(args.budgets.read_text(encoding="utf-8"))
    budgets = [Budget(b["category"], Decimal(str(b["monthly_limit"])), bool(b.get("rollover", False)))
               for b in raw]
    over = False
    for status in check_budgets(ledger, budgets, args.month):
        suffix = " OVER" if status.over else ""
        over = over or status.over
        print(f"{status.category}: spent {format_amount(status.spent)} of "
              f"{format_amount(status.limit)}{suffix}")
    return EXIT_ERROR if over else EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ledger")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create an empty ledger file")
    p.add_argument("ledger", type=Path)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("account", help="add an account")
    p.add_argument("ledger", type=Path)
    p.add_argument("id")
    p.add_argument("name")
    p.add_argument("--kind", default="checking")
    p.add_argument("--currency", default="EUR")
    p.add_argument("--opening", default="0.00")
    p.set_defaults(func=cmd_account)

    p = sub.add_parser("import", help="import a bank CSV export")
    p.add_argument("ledger", type=Path)
    p.add_argument("csv", type=Path)
    p.add_argument("--profile", choices=sorted(importer.PROFILES))
    p.add_argument("--account", default="main")
    p.add_argument("--show-skipped", type=int, default=10)
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("report", help="monthly summary")
    p.add_argument("ledger", type=Path)
    p.add_argument("--month")
    p.add_argument("--account")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("balance", help="balances per account")
    p.add_argument("ledger", type=Path)
    p.add_argument("--as-of")
    p.set_defaults(func=cmd_balance)

    p = sub.add_parser("top", help="where the money went")
    p.add_argument("ledger", type=Path)
    p.add_argument("--month")
    p.add_argument("--limit", type=int, default=5)
    p.set_defaults(func=cmd_top)

    p = sub.add_parser("budget", help="budgets for a month")
    p.add_argument("ledger", type=Path)
    p.add_argument("budgets", type=Path)
    p.add_argument("--month", required=True)
    p.set_defaults(func=cmd_budget)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    try:
        return int(args.func(args))
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
