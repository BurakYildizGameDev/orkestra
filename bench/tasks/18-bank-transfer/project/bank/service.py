def transfer(source, target, amount, ledger):
    source.withdraw(amount)
    target.deposit(amount)
