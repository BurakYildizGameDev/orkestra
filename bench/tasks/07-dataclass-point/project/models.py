class Product:
    def __init__(self, name, price, tags=None):
        if price < 0:
            raise ValueError("price must not be negative")
        self.name = name
        self.price = price
        self.tags = tags if tags is not None else []

    def price_with_vat(self, rate=0.2):
        return round(self.price * (1 + rate), 2)
