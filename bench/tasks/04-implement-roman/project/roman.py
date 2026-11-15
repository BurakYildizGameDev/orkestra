def to_roman(number):
    """Write 1..3999 in Roman numerals (subtractive form: 4 -> "IV", 1994 -> "MCMXCIV").

    Raises ValueError outside 1..3999 and TypeError for anything that is not an int (bool
    included).
    """
    raise NotImplementedError


def from_roman(text):
    """Read a Roman numeral (upper case, canonical form only) back into an int.

    Raises ValueError for an empty string, unknown letters or a non-canonical form such as
    "IIII" or "VX" (the result must turn back into the same text with to_roman).
    """
    raise NotImplementedError
