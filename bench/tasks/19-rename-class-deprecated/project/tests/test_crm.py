from crm.export import to_csv
from crm.store import Store


def test_store_and_export():
    s = Store()
    s.add(1, "Ada", "ada@x.org")
    assert s.get(1).display() == "Ada <ada@x.org>"
    assert to_csv([s.get(1)]) == "1,Ada,ada@x.org"
