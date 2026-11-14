from pricing import fmt, with_tax


def line(name, amount):
    return f"{name}: {fmt(with_tax(amount))}"


def total(items):
    return fmt(sum(with_tax(a) for _, a in items), currency="EUR")
