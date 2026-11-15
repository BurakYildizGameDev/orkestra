class Ledger:
    def __init__(self):
        self.entries = []

    def record(self, source, target, amount):
        self.entries.append((source, target, amount))
