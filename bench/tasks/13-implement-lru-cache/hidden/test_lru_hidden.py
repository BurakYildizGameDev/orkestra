import pytest
from lru import LRUCache


def test_eviction_order():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1  # a is now the most recent
    c.put("c", 3)  # drops b
    assert "b" not in c and c.get("b", "gone") == "gone"
    assert c.keys() == ["a", "c"]


def test_replace_refreshes_and_does_not_grow():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("a", 10)
    c.put("c", 3)
    assert c.get("a") == 10 and "b" not in c
    assert len(c) == 2


def test_contains_does_not_refresh():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert "a" in c
    c.put("c", 3)
    assert "a" not in c


def test_capacity_one_and_bad_capacity():
    c = LRUCache(1)
    c.put("a", 1)
    c.put("b", 2)
    assert c.keys() == ["b"]
    with pytest.raises(ValueError):
        LRUCache(0)


def test_none_is_a_value():
    c = LRUCache(2)
    c.put("a", None)
    assert "a" in c and c.get("a", "default") is None
