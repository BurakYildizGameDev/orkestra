import pytest
from roman import from_roman, to_roman

CASES = [
    (1, "I"),
    (4, "IV"),
    (9, "IX"),
    (14, "XIV"),
    (40, "XL"),
    (90, "XC"),
    (400, "CD"),
    (1994, "MCMXCIV"),
    (2026, "MMXXVI"),
    (3999, "MMMCMXCIX"),
]


@pytest.mark.parametrize(("number", "text"), CASES)
def test_both_ways(number, text):
    assert to_roman(number) == text
    assert from_roman(text) == number


def test_round_trip_everything():
    assert all(from_roman(to_roman(n)) == n for n in range(1, 4000))


@pytest.mark.parametrize("bad", [0, 4000, -5])
def test_out_of_range(bad):
    with pytest.raises(ValueError):
        to_roman(bad)


@pytest.mark.parametrize("bad", [1.0, "5", True])
def test_not_an_int(bad):
    with pytest.raises(TypeError):
        to_roman(bad)


@pytest.mark.parametrize("bad", ["", "IIII", "VX", "ABC", "iv", "MMMM"])
def test_bad_numerals(bad):
    with pytest.raises(ValueError):
        from_roman(bad)
