_VALUES = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
]
_LETTERS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def to_roman(number):
    """Write 1..3999 in Roman numerals (subtractive form: 4 -> "IV", 1994 -> "MCMXCIV").

    Raises ValueError outside 1..3999 and TypeError for anything that is not an int (bool
    included).
    """
    if isinstance(number, bool) or not isinstance(number, int):
        raise TypeError("an int is needed")
    if not 1 <= number <= 3999:
        raise ValueError("1..3999 only")
    parts = []
    for value, letters in _VALUES:
        count, number = divmod(number, value)
        parts.append(letters * count)
    return "".join(parts)


def from_roman(text):
    """Read a Roman numeral (upper case, canonical form only) back into an int.

    Raises ValueError for an empty string, unknown letters or a non-canonical form such as
    "IIII" or "VX" (the result must turn back into the same text with to_roman).
    """
    if not text or any(ch not in _LETTERS for ch in text):
        raise ValueError(f"not a Roman numeral: {text!r}")
    total = 0
    for index, ch in enumerate(text):
        value = _LETTERS[ch]
        following = _LETTERS[text[index + 1]] if index + 1 < len(text) else 0
        total += -value if value < following else value
    if not 1 <= total <= 3999 or to_roman(total) != text:
        raise ValueError(f"not a canonical Roman numeral: {text!r}")
    return total
