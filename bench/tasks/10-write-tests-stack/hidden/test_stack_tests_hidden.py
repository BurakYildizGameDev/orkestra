import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run_their_tests(tmp_path, module, source):
    work = tmp_path / "work"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns("_hidden_tests", "__pycache__"))
    if source is not None:
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


CORRECT = (ROOT / "stack.py").read_text(encoding="utf-8")
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
    done = _run_their_tests(tmp_path, "stack.py", None)
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.parametrize("name", list(MUTANTS))
def test_their_tests_catch_a_broken_stack(tmp_path, name):
    assert MUTANTS[name] != CORRECT
    done = _run_their_tests(tmp_path, "stack.py", MUTANTS[name])
    assert done.returncode == 1, f"a stack where {name} passed their tests"
