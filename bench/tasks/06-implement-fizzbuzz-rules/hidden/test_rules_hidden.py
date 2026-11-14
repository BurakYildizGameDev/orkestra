import pytest
from rules import play


def test_classic():
    out = play(15)
    assert out[:5] == ["1", "2", "Fizz", "4", "Buzz"]
    assert out[14] == "FizzBuzz"
    assert len(out) == 15


def test_custom_rules_keep_their_order():
    out = play(21, rules=((7, "Bazz"), (3, "Fizz")))
    assert out[20] == "BazzFizz"
    assert out[6] == "Bazz" and out[2] == "Fizz"


def test_edges():
    assert play(0) == []
    assert play(-3) == []
    assert play(4, rules=()) == ["1", "2", "3", "4"]
    with pytest.raises(ValueError):
        play(5, rules=((0, "Zero"),))
