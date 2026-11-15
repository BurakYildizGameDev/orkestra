def transfer(source, target, amount, ledger):
    if amount <= 0:
        raise ValueError("amount must be positive")
    source.withdraw(amount)
    try:
        target.deposit(amount)
    except Exception:
        source.balance += amount  # give it back
        raise
    ledger.record(source.number, target.number, amount)
