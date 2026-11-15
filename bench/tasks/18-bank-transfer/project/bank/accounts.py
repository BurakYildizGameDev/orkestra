from bank.errors import AccountFrozen


class Account:
    def __init__(self, number, balance=0, frozen=False):
        self.number = number
        self.balance = balance
        self.frozen = frozen

    def deposit(self, amount):
        if self.frozen:
            raise AccountFrozen(self.number)
        self.balance += amount

    def withdraw(self, amount):
        self.balance -= amount
