import pytest
from bank.accounts import Account
from bank.errors import AccountFrozen, InsufficientFunds
from bank.ledger import Ledger
from bank.service import transfer


def test_ledger_gets_one_entry():
    a, b, ledger = Account("A", 100), Account("B"), Ledger()
    transfer(a, b, 30, ledger)
    assert ledger.entries == [("A", "B", 30)]


def test_insufficient_funds_changes_nothing():
    a, b, ledger = Account("A", 10), Account("B"), Ledger()
    assert issubclass(InsufficientFunds, ValueError)
    with pytest.raises(InsufficientFunds):
        transfer(a, b, 50, ledger)
    assert (a.balance, b.balance, ledger.entries) == (10, 0, [])


def test_frozen_target_rolls_back():
    a, b, ledger = Account("A", 100), Account("B", frozen=True), Ledger()
    with pytest.raises(AccountFrozen):
        transfer(a, b, 40, ledger)
    assert (a.balance, b.balance, ledger.entries) == (100, 0, [])


@pytest.mark.parametrize("amount", [0, -5])
def test_amount_must_be_positive(amount):
    a, b, ledger = Account("A", 100), Account("B"), Ledger()
    with pytest.raises(ValueError):
        transfer(a, b, amount, ledger)
    assert (a.balance, b.balance, ledger.entries) == (100, 0, [])


def test_withdraw_alone_checks_the_balance():
    a = Account("A", 5)
    with pytest.raises(InsufficientFunds):
        a.withdraw(6)
    assert a.balance == 5
