import pytest
from csvline import parse_line


@pytest.mark.parametrize(
    ("line", "fields"),
    [
        ('a,"b,c",d', ["a", "b,c", "d"]),
        ('"say ""hi""",x', ['say "hi"', "x"]),
        ('"",x,', ["", "x", ""]),
        (" a , b ", [" a ", " b "]),
        ('"multi, comma, field"', ["multi, comma, field"]),
        ("a,,b", ["a", "", "b"]),
    ],
)
def test_quoted_fields(line, fields):
    assert parse_line(line) == fields


def test_unclosed_quote():
    with pytest.raises(ValueError):
        parse_line('a,"broken')
