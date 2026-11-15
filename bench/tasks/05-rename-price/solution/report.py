from pricing import format_price, with_tax


def line(name, amount):
    return f"{name}: {format_price(with_tax(amount))}"


def total(items):
    return format_price(sum(with_tax(a) for _, a in items), currency="EUR")
