import ast
import json
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ledger import cli, importer, reports
from ledger.models import Account, LedgerError, Transaction
from ledger.money import AmountError, parse_amount
from ledger.store import Ledger

ROOT = Path(__file__).resolve().parents[1]


def _t(day, amount, description, category="other", account="main"):
    return Transaction(date.fromisoformat(day), account, Decimal(amount), description, category)


@pytest.fixture
def book():
    ledger = Ledger()
    ledger.add_account(Account("main", "Main"))
    ledger.add_account(Account("card", "Card", kind="credit"))
    ledger.add_many([
        _t("2026-08-02", "-40.00", "Migros 1", "groceries"),
        _t("2026-09-02", "-100.00", "Migros 2", "groceries"),
        _t("2026-09-10", "-70.00", "Pizza Place", "dining", "card"),
        _t("2026-10-02", "-130.75", "Migros 3", "groceries"),
        _t("2026-10-05", "-30.00", "Bakery", "groceries", "card"),
        _t("2026-10-06", "15.00", "Refund Migros", "groceries"),
        _t("2026-10-09", "-60.00", "Metro", "transport"),
        _t("2026-10-15", "2500.00", "Payroll", "salary"),
    ])
    return ledger


# --- 1. amounts ------------------------------------------------------------------------------

@pytest.mark.parametrize(("text", "value"), [
    ("(45.00)", "-45.00"), ("(1,045.20)", "-1045.20"), ("1,250.00", "1250.00"),
    ("2,300.00 EUR", "2300.00"), ("(7.99)", "-7.99"), ("-1,000,000.50", "-1000000.50"),
    ("-12.50", "-12.50"), ("$ 4.10", "4.10"),
])
def test_bank_amount_formats(text, value):
    assert parse_amount(text) == Decimal(value)


@pytest.mark.parametrize("text", ["abc", "()", "(", "EUR", "", "1.2.3x"])
def test_non_amounts_still_raise(text):
    with pytest.raises(AmountError):
        parse_amount(text)


def test_the_logged_rows_import_and_bad_data_stays_skipped(book):
    text = ("Booking date,Payee,Amount,Category,Account\n"
            "01.11.2026,Migros 9,(45.00),groceries,main\n"
            '02.11.2026,Payroll,"1,250.00",salary,main\n'
            "03.11.2026,Old,-3.00,other,acct-9\n")
    result = importer.import_text(book, text, "northbank")
    assert result.imported == 2 and len(result.skipped) == 1
    assert "acct-9" in result.skipped[0].reason


# --- 2. budgets ------------------------------------------------------------------------------

def test_budget_without_rollover(book):
    from ledger.budget import Budget, check_budgets

    [g] = check_budgets(book, [Budget("groceries", Decimal("150.00"))], "2026-10")
    assert (g.category, g.limit, g.spent, g.remaining, g.over) == (
        "groceries", Decimal("150.00"), Decimal("160.75"), Decimal("-10.75"), True)


def test_budgets_are_sorted_and_untouched_categories_are_zero(book):
    from ledger.budget import Budget, check_budgets

    found = check_budgets(book, [Budget("transport", Decimal("80")), Budget("dining", Decimal("50")),
                                 Budget("health", Decimal("20"))], "2026-10")
    assert [s.category for s in found] == ["dining", "health", "transport"]
    assert found[0].spent == 0 and not found[0].over
    assert found[2].remaining == Decimal("20") and found[2].over is False


def test_rollover_carries_only_what_was_left(book):
    from ledger.budget import Budget, check_budgets

    budget = Budget("groceries", Decimal("120.00"), rollover=True)
    # Aug: 120 - 40 = 80 left; Sep: 200 - 100 = 100 left; Oct: 220
    [oct_] = check_budgets(book, [budget], "2026-10")
    assert oct_.limit == Decimal("220.00") and oct_.spent == Decimal("160.75")
    assert oct_.remaining == Decimal("59.25") and not oct_.over
    [sep] = check_budgets(book, [budget], "2026-09")
    assert sep.limit == Decimal("200.00")
    dining = Budget("dining", Decimal("20.00"), rollover=True)
    # Aug: 20 left -> Sep 40; Sep spent 70 (over): nothing carried -> Oct 20
    [d_oct] = check_budgets(book, [dining], "2026-10")
    assert d_oct.limit == Decimal("20.00")
    [d_aug] = check_budgets(book, [dining], "2026-08")
    assert d_aug.limit == Decimal("20.00")
    [d_sep] = check_budgets(book, [dining], "2026-09")
    assert d_sep.limit == Decimal("40.00") and d_sep.over


def test_budget_dataclasses_are_frozen_and_month_checked(book):
    from dataclasses import FrozenInstanceError

    from ledger.budget import Budget, check_budgets

    budget = Budget("rent", Decimal("900"))
    with pytest.raises(FrozenInstanceError):
        budget.category = "x"
    [status] = check_budgets(book, [budget], "2026-10")
    with pytest.raises(FrozenInstanceError):
        status.spent = Decimal(1)
    with pytest.raises(LedgerError):
        check_budgets(book, [budget], "2026-13")


# --- 3. recurring ----------------------------------------------------------------------------

def test_monthly_rule_clamps_to_month_end():
    from ledger.recurring import RecurringRule, occurrences

    rule = RecurringRule("Rent", "main", Decimal("-900"), "rent", "monthly", 31)
    assert occurrences(rule, date(2026, 1, 1), date(2026, 4, 30)) == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]
    assert occurrences(rule, date(2028, 2, 1), date(2028, 2, 29)) == [date(2028, 2, 29)]
    assert occurrences(rule, date(2026, 2, 1), date(2026, 1, 1)) == []


def test_monthly_rule_window_is_inclusive():
    from ledger.recurring import RecurringRule, occurrences

    rule = RecurringRule("Gym", "main", Decimal("-30"), "health", "monthly", 15)
    assert occurrences(rule, date(2026, 3, 15), date(2026, 5, 15)) == [
        date(2026, 3, 15), date(2026, 4, 15), date(2026, 5, 15)]
    assert occurrences(rule, date(2026, 3, 16), date(2026, 4, 14)) == []


def test_weekly_rule():
    from ledger.recurring import RecurringRule, occurrences

    rule = RecurringRule("Market", "main", Decimal("-20"), "groceries", "weekly", 4)  # Friday
    assert occurrences(rule, date(2026, 11, 1), date(2026, 11, 20)) == [
        date(2026, 11, 6), date(2026, 11, 13), date(2026, 11, 20)]


@pytest.mark.parametrize(("every", "day"), [("daily", 1), ("monthly", 0), ("monthly", 32),
                                            ("weekly", 7), ("weekly", -1)])
def test_bad_rules_are_refused(every, day):
    from ledger.recurring import RecurringRule

    with pytest.raises(LedgerError):
        RecurringRule("x", "main", Decimal("-1"), "other", every, day)


def test_apply_rules_adds_once(book):
    from ledger.recurring import RecurringRule, apply_rules

    rules = [RecurringRule("Rent", "main", Decimal("-900.00"), "rent", "monthly", 1),
             RecurringRule("Coffee", "card", Decimal("-3.50"), "dining", "weekly", 0)]
    added = apply_rules(book, rules, date(2026, 11, 1), date(2026, 11, 30))
    assert added == 1 + 5  # rent on the 1st; coffee on Mondays 2, 9, 16, 23, 30
    rent = book.transactions(month="2026-11", category="rent")
    assert [(t.date, t.amount, t.account) for t in rent] == [(date(2026, 11, 1), Decimal("-900.00"), "main")]
    assert apply_rules(book, rules, date(2026, 11, 1), date(2026, 11, 30)) == 0


# --- 4. CSV export ---------------------------------------------------------------------------

def test_export_summary_csv(book, tmp_path):
    book.add(_t("2026-10-20", "-1200.00", "Landlord", "rent"))
    path = tmp_path / "oct.csv"
    reports.export_summary_csv(book, "2026-10", path)
    assert path.read_bytes().decode("utf-8") == (
        "category,total\n"
        "groceries,-145.75\n"
        "rent,-1200.00\n"
        "salary,2500.00\n"
        "transport,-60.00\n"
    )


# --- 5. command line -------------------------------------------------------------------------

def test_cli_budget(book, tmp_path, capsys):
    ledger_file = tmp_path / "book.json"
    book.save(ledger_file)
    budgets = tmp_path / "budgets.json"
    budgets.write_text(json.dumps([
        {"category": "transport", "monthly_limit": "100.00"},
        {"category": "groceries", "monthly_limit": "120.00", "rollover": True},
    ]), encoding="utf-8")
    code = cli.main(["budget", str(ledger_file), str(budgets), "--month", "2026-10"])
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["groceries: spent 160.75 of 220.00", "transport: spent 60.00 of 100.00"]
    assert code == 0
    budgets.write_text(json.dumps([{"category": "groceries", "monthly_limit": "1000.00"},
                                   {"category": "dining", "monthly_limit": "10"}]),
                       encoding="utf-8")
    code = cli.main(["budget", str(ledger_file), str(budgets), "--month", "2026-09"])
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["dining: spent 70.00 of 10.00 OVER", "groceries: spent 100.00 of 1,000.00"]
    assert code == 1


# --- 6. docstrings ---------------------------------------------------------------------------

def _public_without_docstring(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    missing = []

    def visit(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                if not child.name.startswith("_") and not ast.get_docstring(child):
                    missing.append(name)
                if isinstance(child, ast.ClassDef):
                    visit(child, name + ".")

    visit(tree)
    return missing


@pytest.mark.parametrize("module", ["store.py", "reports.py"])
def test_public_names_have_docstrings(module):
    assert _public_without_docstring(ROOT / "ledger" / module) == []


def test_the_original_public_names_are_still_there():
    from ledger import store

    for name in ("Ledger", "merge", "months_between", "daily_balances", "current_month"):
        assert hasattr(store, name)
    for name in ("monthly_summary", "summaries", "compare_months", "top_merchants",
                 "balance_history", "render_summary", "render_balances", "MonthSummary"):
        assert hasattr(reports, name)


# --- 7. tests ---------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["test_budget.py", "test_recurring.py"])
def test_new_test_files_have_five_tests(name):
    path = ROOT / "tests" / name
    assert path.is_file(), name
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tests = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")]
    assert len(tests) >= 5


def test_the_whole_test_suite_passes():
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                          cwd=ROOT, capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stdout[-2000:]
    passed = int(done.stdout.strip().splitlines()[-1].split(" passed")[0].split()[-1])
    assert passed >= 33 + 10
