class AccountFrozen(Exception):
    """The account takes no money."""


class InsufficientFunds(ValueError):
    """The balance is lower than the amount."""
