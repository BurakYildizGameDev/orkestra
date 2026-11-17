"""Rule-based digests of long command output (Faz 13i-a): real pytest, ruff and pyright output.

The samples in ``fixtures/outputs`` were produced by the real tools (pytest 9.2, ruff, pyright)
and only their paths were replaced by ``/work/proj``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.chief import outparse

OUTPUTS = Path(__file__).resolve().parents[1] / "fixtures" / "outputs"


def _sample(name: str) -> str:
    return (OUTPUTS / f"{name}.txt").read_bytes().decode("utf-8")


def _pointers(digest: outparse.Digest) -> list[str]:
    return [f"{i.file}:{i.line}" for i in digest.items]


@pytest.mark.parametrize("name", ["pytest_default", "pytest_q"])
def test_pytest_keeps_every_failed_test_with_where_it_failed(name: str) -> None:
    digest = outparse.parse(_sample(name))
    assert digest is not None and digest.tool == "pytest"
    assert digest.headline == "4 failed, 1 passed in 0.06s"
    assert [i.text for i in digest.items] == [
        "FAILED tests/test_calc.py::test_add - assert -1 == 5",
        "FAILED tests/test_calc.py::test_param[1] - assert 0 == (2 * 1)",
        "FAILED tests/test_calc.py::test_param[2] - assert 0 == (2 * 2)",
        "FAILED tests/test_calc.py::TestK::test_m - ValueError: boom",
    ]
    assert _pointers(digest) == [
        "tests/test_calc.py:6", "tests/test_calc.py:15", "tests/test_calc.py:15",
        "tests/test_calc.py:20",
    ]  # fmt: skip


def test_a_passing_pytest_run_is_its_summary_line() -> None:
    text = "....\n" + "x\n" * 100 + "============ 4 passed, 1 skipped in 1.20s ============\n"
    digest = outparse.parse(text)
    assert digest is not None and digest.tool == "pytest"
    assert digest.headline == "4 passed, 1 skipped in 1.20s" and digest.items == []


def test_pytest_collection_errors_are_kept() -> None:
    text = (
        "==================================== ERRORS ====================================\n"
        "____________________ ERROR collecting tests/test_x.py ____________________\n"
        "ImportError while importing test module '/work/proj/tests/test_x.py'.\n"
        "E   ModuleNotFoundError: No module named 'foo'\n"
        "=========================== short test summary info ============================\n"
        "ERROR tests/test_x.py\n"
        "!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!\n"
        "=============================== 1 error in 0.12s ===============================\n"
    )
    digest = outparse.parse(text)
    assert digest is not None
    assert [i.text for i in digest.items] == ["ERROR tests/test_x.py"]
    assert digest.headline == "1 error in 0.12s"


def test_no_failed_test_name_is_ever_dropped() -> None:
    failed = [f"FAILED tests/test_many.py::test_{n} - assert False" for n in range(80)]
    text = "\n".join(["short test summary info", *failed, "80 failed in 3.00s"]) + "\n"
    digest = outparse.parse(text)
    assert digest is not None and len(digest.items) == 80
    rendered = outparse.render_items(digest)
    for n in range(80):
        assert f"test_many.py::test_{n} " in rendered


@pytest.mark.parametrize("name", ["ruff_full", "ruff_concise"])
def test_ruff_lists_each_finding_at_its_place(name: str) -> None:
    digest = outparse.parse(_sample(name), cwd="/work/proj")
    assert digest is not None and digest.tool == "ruff"
    assert digest.headline == "Found 3 errors."
    assert _pointers(digest) == ["bad.py:1", "bad.py:1", "bad.py:4"]
    assert [i.text.split()[0] for i in digest.items] == ["I001", "F401", "F821"]
    assert "Undefined name `undefined_name`" in digest.items[2].text


def test_ruff_format_check_lists_the_files() -> None:
    digest = outparse.parse(_sample("ruff_format"), cwd="/work/proj")
    assert digest is not None and digest.tool == "ruff"
    assert digest.headline == "1 file would be reformatted, 2 files already formatted"
    assert _pointers(digest) == ["bad.py:2"]


def test_pyright_lists_each_diagnostic() -> None:
    digest = outparse.parse(_sample("pyright"), cwd="/work/proj")
    assert digest is not None and digest.tool == "pyright"
    assert digest.headline == "1 error, 0 warnings, 0 informations"
    assert _pointers(digest) == ["bad.py:4"]
    assert digest.items[0].text.startswith('error: "undefined_name" is not defined')


def test_compilers_and_type_checkers_by_their_file_line_form() -> None:
    text = "\n".join([
        "Building...",
        "src/a.py:12: error: Incompatible return value type (got \"int\", expected \"str\")",
        "src/b.ts(3,5): error TS2322: Type 'number' is not assignable to type 'string'.",
        "error[E0382]: borrow of moved value: `v`",
        "  --> src/main.rs:5:9",
        "warning: unused variable: `x`",
        " --> src/lib.rs:2:9",
        "Found 2 errors in 2 files (checked 10 source files)",
    ])  # fmt: skip
    digest = outparse.parse(text)
    assert digest is not None and digest.tool == "compiler"
    assert _pointers(digest) == ["src/a.py:12", "src/b.ts:3", "src/main.rs:5", "src/lib.rs:2"]
    assert digest.items[2].text == "error[E0382]: borrow of moved value: `v`"


def test_output_with_nothing_known_is_not_parsed() -> None:
    assert outparse.parse("downloading...\n" * 200 + "done\n") is None
    assert outparse.parse("") is None


def test_many_linter_findings_are_capped_with_a_count() -> None:
    text = "\n".join(f"/work/proj/a.py:{n}:1: E501 Line too long" for n in range(1, 101))
    digest = outparse.parse(text + "\nFound 100 errors.\n", cwd="/work/proj")
    assert digest is not None and len(digest.items) == 100
    rendered = outparse.render_items(digest)
    assert "a.py:30:1" in rendered and "a.py:31:1" not in rendered
    assert "70" in rendered  # "+70 more in the log"


# --- code review fixes (PR #31) --------------------------------------------------------


def test_every_tool_in_one_output_is_kept() -> None:
    text = "\n".join([
        "ruff check .",
        "/work/proj/a.py:1:8: F401 `os` imported but unused",
        "/work/proj/b.py:3:1: E501 Line too long",
        "Found 2 errors.",
        "pyright",
        "0 errors, 0 warnings, 0 informations",
    ])  # fmt: skip
    digest = outparse.parse(text, cwd="/work/proj")
    assert digest is not None and digest.tool == "ruff+pyright"
    assert _pointers(digest) == ["a.py:1", "b.py:3"]
    assert digest.headline == "Found 2 errors. · 0 errors, 0 warnings, 0 informations"


def test_a_warning_alone_does_not_make_a_test_run_a_compiler_digest() -> None:
    text = "\n".join([
        "warning: unused import: `std::fmt`",
        " --> src/lib.rs:1:5",
        "running 2 tests",
        "test tests::it_works ... FAILED",
        "failures:",
        "test result: FAILED. 1 passed; 1 failed",
    ])  # fmt: skip
    assert outparse.parse(text) is None  # left to the worker's summary


def test_same_named_tests_in_two_files_point_at_their_own_file() -> None:
    text = "\n".join([
        "=================================== FAILURES ===================================",
        "__________________________________ test_init ___________________________________",
        "tests/a/test_api.py:7: AssertionError",
        "__________________________________ test_init ___________________________________",
        "tests/b/test_db.py:42: AssertionError",
        "____________________________ ERROR at setup of test_x ____________________________",
        "tests/c/test_x.py:3: ValueError",
        "=========================== short test summary info ============================",
        "FAILED tests/a/test_api.py::test_init - assert 1 == 2",
        "FAILED tests/b/test_db.py::test_init - assert 3 == 4",
        "ERROR tests/c/test_x.py::test_x - ValueError: no db",
        "==================== 2 failed, 1 error in 0.10s ====================",
    ])  # fmt: skip
    digest = outparse.parse(text)
    assert digest is not None
    assert _pointers(digest) == ["tests/a/test_api.py:7", "tests/b/test_db.py:42",
                                 "tests/c/test_x.py:3"]  # fmt: skip
