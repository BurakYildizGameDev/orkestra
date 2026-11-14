import pytest
from inventory import Inventory


def test_removing_too_much_raises_and_keeps_the_stock():
    inv = Inventory()
    inv.add("apple", 3, 0.5)
    with pytest.raises(ValueError):
        inv.remove("apple", 4)
    assert inv.quantity("apple") == 3


def test_removing_an_unknown_item_raises_key_error():
    inv = Inventory()
    with pytest.raises(KeyError):
        inv.remove("pear", 1)


def test_removing_everything_is_allowed():
    inv = Inventory()
    inv.add("apple", 3, 0.5)
    inv.remove("apple", 3)
    assert inv.quantity("apple") == 0


def test_total_value_is_rounded_to_cents():
    inv = Inventory()
    inv.add("a", 1, 0.1)
    inv.add("b", 1, 0.2)
    assert inv.total_value() == 0.3
    inv.add("c", 3, 1.005)
    assert inv.total_value() == round(0.1 + 0.2 + 3 * 1.005, 2)


def test_add_still_validates():
    inv = Inventory()
    with pytest.raises(ValueError):
        inv.add("apple", 0, 1.0)
