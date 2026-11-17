"""Pointers in a worker's answer, checked against the files (Faz 13i-b)."""

from __future__ import annotations

from orkestra.chief import pointers

FILES = {
    "src/calc.py": ["def add(a, b):", "    return a - b", ""],
    "src/app.py": ["from calc import add", "print(add(1, 2))"],
}


def test_valid_pointers_come_back_with_their_line() -> None:
    found = pointers.check("see src/calc.py:2 and src/app.py:1-2", FILES)
    assert [(p.pointer, p.valid, p.line) for p in found] == [
        ("src/calc.py:2", True, "return a - b"),
        ("src/app.py:1-2", True, "from calc import add"),
    ]


def test_out_of_range_unknown_and_reversed_pointers_are_invalid() -> None:
    found = pointers.check("src/calc.py:9, other.py:1, src/app.py:2-1, src/calc.py:0", FILES)
    assert [p.valid for p in found] == [False, False, False, False]


def test_a_bare_file_name_works_when_only_one_file_has_it() -> None:
    (found,) = pointers.check("calc.py:1", FILES)
    assert found.valid and found.line == "def add(a, b):"
    two = {"a/x.py": ["1"], "b/x.py": ["2"]}
    (ambiguous,) = pointers.check("x.py:1", two)
    assert not ambiguous.valid


def test_each_pointer_once_and_backslashes_too() -> None:
    found = pointers.check(r"src/calc.py:2 then src\calc.py:2 again src/calc.py:2", FILES)
    assert [p.pointer for p in found] == ["src/calc.py:2"]


def test_versions_and_times_are_not_pointers() -> None:
    found = pointers.check("python 3.12:1 at 10:30 on example.com:8080", FILES)
    assert [(p.pointer, p.valid) for p in found] == [("example.com:8080", False)]
