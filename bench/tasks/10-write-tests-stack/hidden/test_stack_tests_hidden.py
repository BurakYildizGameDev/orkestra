import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run_their_tests(tmp_path, module, source):
    work = tmp_path / "work"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns("_hidden_tests", "__pycache__"))
    (work / module).write_text(source, encoding="utf-8")
    (work / "_m.ini").write_text("[pytest]\n", encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-c",
            "_m.ini",
            "--rootdir",
            ".",
            "tests",
        ],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=120,
    )


# The original stack.py: the worker's tests are scored against it (and against broken
# versions of it), whatever the worker did to stack.py.
CORRECT = 'class EmptyStackError(Exception):\n    """Raised by pop() and peek() on an empty stack."""\n\n\nclass Stack:\n    """Last in, first out, with an optional size limit."""\n\n    def __init__(self, limit=None):\n        """``limit``: the most items it may hold (None: no limit); below 1 is a ValueError."""\n        if limit is not None and limit < 1:\n            raise ValueError("limit must be at least 1")\n        self._items = []\n        self._limit = limit\n\n    def push(self, item):\n        """Add on top; OverflowError when the stack is full."""\n        if self._limit is not None and len(self._items) >= self._limit:\n            raise OverflowError("stack is full")\n        self._items.append(item)\n\n    def pop(self):\n        """Remove and return the top item; EmptyStackError when empty."""\n        if not self._items:\n            raise EmptyStackError("pop from an empty stack")\n        return self._items.pop()\n\n    def peek(self):\n        """Return the top item without removing it; EmptyStackError when empty."""\n        if not self._items:\n            raise EmptyStackError("peek at an empty stack")\n        return self._items[-1]\n\n    def __len__(self):\n        return len(self._items)\n\n    def is_empty(self):\n        return not self._items\n'
MUTANTS = {
    "pop takes the bottom": CORRECT.replace(
        "return self._items.pop()", "return self._items.pop(0)"
    ),
    "peek removes": CORRECT.replace("return self._items[-1]", "return self._items.pop()"),
    "no limit check": CORRECT.replace("len(self._items) >= self._limit", "False"),
    "limit off by one": CORRECT.replace(
        "len(self._items) >= self._limit", "len(self._items) > self._limit"
    ),
    "empty peek returns None": CORRECT.replace(
        'raise EmptyStackError("peek at an empty stack")', "return None"
    ),
    "is_empty inverted": CORRECT.replace("return not self._items", "return bool(self._items)"),
    "bad limit accepted": CORRECT.replace("limit < 1", "limit < 0"),
}


def test_they_wrote_tests():
    assert list((ROOT / "tests").glob("test_*.py")), "no tests/test_*.py"


def test_their_tests_pass_on_the_real_stack(tmp_path):
    done = _run_their_tests(tmp_path, "stack.py", CORRECT)
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.parametrize("name", list(MUTANTS))
def test_their_tests_catch_a_broken_stack(tmp_path, name):
    assert MUTANTS[name] != CORRECT
    done = _run_their_tests(tmp_path, "stack.py", MUTANTS[name])
    assert done.returncode == 1, f"a stack where {name} passed their tests"
