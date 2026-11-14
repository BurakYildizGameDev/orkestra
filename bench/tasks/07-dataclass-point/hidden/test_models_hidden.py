import dataclasses
import typing

import pytest
from models import Product


def test_it_is_a_frozen_dataclass_with_hints():
    assert dataclasses.is_dataclass(Product)
    assert Product.__dataclass_params__.frozen
    hints = typing.get_type_hints(Product)
    assert hints["name"] is str and hints["price"] is float
    assert hints["tags"] == list[str]


def test_behaviour():
    a = Product("tea", 2.5)
    assert a == Product("tea", 2.5)
    assert a.tags == [] and a.tags is not Product("x", 1).tags
    assert a.price_with_vat() == 3.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.price = 3
    with pytest.raises(ValueError):
        Product("bad", -1)
