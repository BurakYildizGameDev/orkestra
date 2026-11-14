from inventory import Inventory


def test_add_and_quantity():
    inv = Inventory()
    inv.add("apple", 3, 0.5)
    inv.add("apple", 2, 0.5)
    assert inv.quantity("apple") == 5
    assert inv.quantity("pear") == 0


def test_remove_some():
    inv = Inventory()
    inv.add("apple", 3, 0.5)
    inv.remove("apple", 1)
    assert inv.quantity("apple") == 2
