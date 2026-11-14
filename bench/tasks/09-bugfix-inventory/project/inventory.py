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
        self._stock[name] = self._stock.get(name, 0) - quantity

    def quantity(self, name):
        return self._stock.get(name, 0)

    def total_value(self):
        return sum(self._stock[name] * self._prices[name] for name in self._stock)
