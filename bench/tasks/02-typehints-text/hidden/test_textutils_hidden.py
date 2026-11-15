import inspect
import typing

import textutils

NAMES = ["shout", "initials", "word_lengths", "first_long_word", "join_lines"]


def test_every_parameter_and_return_is_annotated():
    for name in NAMES:
        fn = getattr(textutils, name)
        hints = typing.get_type_hints(fn)
        for param in inspect.signature(fn).parameters:
            assert param in hints, f"{name}: {param} has no type hint"
        assert "return" in hints, f"{name} has no return type"


def test_the_hints_say_the_right_types():
    hints = typing.get_type_hints(textutils.word_lengths)
    assert hints["return"] == dict[str, int]
    optional = typing.get_type_hints(textutils.first_long_word)["return"]
    assert type(None) in typing.get_args(optional) and str in typing.get_args(optional)
    assert typing.get_type_hints(textutils.first_long_word)["minimum"] is int


def test_behaviour_is_unchanged():
    assert textutils.shout("hi") == "HI!"
    assert textutils.initials("ada  lovelace") == "AL"
    assert textutils.word_lengths(["a", "abc"]) == {"a": 1, "abc": 3}
    assert textutils.first_long_word(["a", "abcd"], 3) == "abcd"
    assert textutils.first_long_word(["a"], 3) is None
    assert textutils.join_lines(["a", "b"]) == "a\nb"
