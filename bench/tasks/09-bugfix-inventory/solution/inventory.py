class Inventory:
    def __init__(self):
        self._stock = {}
        self._prices = {}

    def add(self, name, quantity, price):
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self._stock[name] = self._stock.get(name, 0) + quantity
        self._prices[name] = price

    def remove(self, name, quantity):
        if name not in self._stock:
            raise KeyError(name)
        if quantity > self._stock[name]:
            raise ValueError("not enough stock")
        self._stock[name] -= quantity

    def quantity(self, name):
        return self._stock.get(name, 0)

    def total_value(self):
        return round(sum(self._stock[name] * self._prices[name] for name in self._stock), 2)
