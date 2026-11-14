from crm.models import UserRecord


class Store:
    def __init__(self):
        self._rows = {}

    def add(self, id, name, email):
        record = UserRecord(id, name, email)
        self._rows[id] = record
        return record

    def get(self, id) -> UserRecord:
        return self._rows[id]
