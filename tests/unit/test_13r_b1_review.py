"""Code-review fixes for Faz 13r-b1 (D-132): the feedback budget and the digested detail."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from orkestra.tasks.prompts import FEEDBACK_CHARS, format_failures
from orkestra.verify.base import DETAIL_CHARS, VerifyContext
from orkestra.verify.command import CommandCheck

MARK = "[... truncated]"


def _long(prefix: str, count: int) -> str:
    lines = (f"src/{prefix}{i}.py:{i}:1: F401 something unused here {i}" for i in range(count))
    return "command: exited with code 1\n" + "\n".join(lines)


def test_two_long_verifiers_stay_under_the_limit_and_the_last_one_is_not_cut_again() -> None:
    out = format_failures([_long("a", 60), _long("b", 60)])
    assert len(out) <= FEEDBACK_CHARS
    # Each verifier was cut once, by its own share; nothing cut the joined text afterwards.
    assert out.count(MARK) == 2
    assert out.endswith(MARK)


def test_many_verifiers_stay_under_the_limit() -> None:
    out = format_failures([_long(f"m{n}_", 40) for n in range(7)])
    assert len(out) <= FEEDBACK_CHARS
    assert out.count(MARK) == 7


def _pytest_output(failures: int) -> str:
    lines = ["=========================== short test summary info ============================"]
    lines += [f"FAILED tests/test_f.py::test_case_{i} - AssertionError" for i in range(failures)]
    lines.append(f"============================== {failures} failed in 0.25s ==============")
    return "\n".join(lines) + "\n"


async def _detail(tmp_path: Path, text: str) -> str:
    (tmp_path / "out.txt").write_text(text, encoding="utf-8")
    script = "import sys; sys.stdout.write(open('out.txt').read()); sys.exit(1)"
    check = CommandCheck(run=f'"{sys.executable}" -c "{script}"', timeout_s=30)
    result = await check.check(VerifyContext(workdir=tmp_path, output=""))
    assert not result.result.ok
    return result.result.detail


@pytest.mark.asyncio
async def test_the_digested_detail_keeps_the_summary_line(tmp_path: Path) -> None:
    detail = await _detail(tmp_path, _pytest_output(3))
    assert "3 failed" in detail
    assert "tests/test_f.py::test_case_2" in detail


@pytest.mark.asyncio
async def test_the_digested_detail_is_capped_like_the_raw_one(tmp_path: Path) -> None:
    detail = await _detail(tmp_path, _pytest_output(400))
    message, body = detail.split("\n", 1)  # "exit code 1", then the output
    assert "1" in message
    assert len(body) <= DETAIL_CHARS
    assert body.startswith("400 failed")
