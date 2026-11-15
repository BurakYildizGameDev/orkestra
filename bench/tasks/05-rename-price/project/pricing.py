def fmt(amount, currency="EUR"):
    return f"{amount:,.2f} {currency}"


def with_tax(amount, rate=0.2):
    return round(amount * (1 + rate), 2)
