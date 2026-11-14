from bank.accounts import Account
from bank.ledger import Ledger
from bank.service import transfer


def test_simple_transfer():
    a, b = Account("A", 100), Account("B", 0)
    transfer(a, b, 30, Ledger())
    assert (a.balance, b.balance) == (70, 30)
