from crm.models import Customer


class Store:
    def __init__(self):
        self._rows = {}

    def add(self, id, name, email):
        record = Customer(id, name, email)
        self._rows[id] = record
        return record

    def get(self, id) -> Customer:
        return self._rows[id]
