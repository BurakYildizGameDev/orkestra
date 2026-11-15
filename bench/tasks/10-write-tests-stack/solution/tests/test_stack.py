import pytest
from stack import EmptyStackError, Stack


def test_push_pop_is_lifo():
    s = Stack()
    s.push(1)
    s.push(2)
    assert s.pop() == 2
    assert s.pop() == 1


def test_peek_does_not_remove():
    s = Stack()
    s.push("a")
    assert s.peek() == "a"
    assert len(s) == 1


def test_empty_errors():
    s = Stack()
    with pytest.raises(EmptyStackError):
        s.pop()
    with pytest.raises(EmptyStackError):
        s.peek()


def test_len_and_is_empty():
    s = Stack()
    assert s.is_empty() and len(s) == 0
    s.push(1)
    assert not s.is_empty() and len(s) == 1


def test_limit():
    s = Stack(limit=2)
    s.push(1)
    s.push(2)
    with pytest.raises(OverflowError):
        s.push(3)


def test_limit_one_and_bad_limits():
    s = Stack(limit=1)
    s.push(1)
    with pytest.raises(OverflowError):
        s.push(2)
    with pytest.raises(ValueError):
        Stack(limit=0)
