"""``orkestra read``, ``orkestra find`` and the index hook (Faz 13i-b), with a fake worker.

The chief gets a short answer with ``file:line`` pointers instead of whole files; every
pointer is checked against the file and shown with the line it names.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from orkestra.chief import reader
from orkestra.cli import app

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
CALC = "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n"


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text("version: 1\n", encoding="utf-8")
    folder = tmp_path / "proj"
    (folder / "src").mkdir(parents=True)
    (folder / "src" / "calc.py").write_text(CALC, encoding="utf-8")
    (folder / "src" / "app.py").write_text(
        "from calc import add\n\nprint(add(1, 2))\nprint(add(3, 4))\n", encoding="utf-8"
    )
    (folder / "secret.txt").write_text("API_TOKEN=do-not-send\nadd\n", encoding="utf-8")
    (folder / ".orkestraignore").write_text("secret.txt\n", encoding="utf-8")
    monkeypatch.chdir(folder)
    return folder


class FakeWorker:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, config: object, **kwargs: Any) -> tuple[str, str]:
        self.calls.append(kwargs)
        return self.answer, "ollama/coder"


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> FakeWorker:
    fake = FakeWorker("add subtracts instead of adding: src/calc.py:2. See src/calc.py:99.")
    monkeypatch.setattr(reader, "query_chief_model", fake)
    return fake


# --- read ------------------------------------------------------------------------------


def test_read_answers_with_checked_pointers(
    project: Path, worker: FakeWorker, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run(["read", "src/calc.py", "What does add do?", "--json"], capsys)
    assert code == 0, err
    data = json.loads(out)
    assert data["answer"].startswith("add subtracts")
    assert data["pointers"] == [
        {"pointer": "src/calc.py:2", "valid": True, "line": "return a - b"},
        {"pointer": "src/calc.py:99", "valid": False, "line": None},
    ]
    assert data["model"] == "ollama/coder" and data["cached"] is False
    (call,) = worker.calls
    assert "What does add do?" in call["user"]
    assert "    2| " in call["user"]  # numbered lines, so the worker can point at them
    assert call["agents"] is False and call["tier"] == 1


def test_human_read_shows_each_pointer_with_its_line(
    project: Path, worker: FakeWorker, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(["--lang", "en", "read", "src/calc.py", "What does add do?"], capsys)
    assert code == 0
    assert "src/calc.py:2  return a - b" in out
    assert "src/calc.py:99" in out and "no such line" in out


def test_the_same_question_on_the_same_files_comes_from_the_cache(
    project: Path, worker: FakeWorker, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["read", "src/calc.py", "What does add do?", "--json"]
    _run(argv, capsys)
    code, out, _ = _run(argv, capsys)
    assert code == 0 and json.loads(out)["cached"] is True and len(worker.calls) == 1
    (project / "src" / "calc.py").write_text(CALC + "\n# changed\n", encoding="utf-8")
    _run(argv, capsys)
    assert len(worker.calls) == 2  # a changed file is read again
    _run([*argv, "--no-cache"], capsys)
    assert len(worker.calls) == 3


def test_an_ignored_file_is_never_sent(
    project: Path, worker: FakeWorker, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(["read", "src/calc.py", "secret.txt", "Anything?", "--json"], capsys)
    assert code == 0
    assert "do-not-send" not in worker.calls[0]["user"]
    assert json.loads(out)["ignored"] == ["secret.txt"]
    code, _, _ = _run(["read", "secret.txt", "Anything?"], capsys)
    assert code == 2  # nothing left to read


def test_read_without_a_worker_says_how_to_get_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = _run(["--lang", "en", "read", "src/calc.py", "What does add do?"], capsys)
    assert code == 2 and "orkestra init" in err  # no providers: like every other command


# --- find ------------------------------------------------------------------------------


def test_find_lists_few_hits_with_no_model(
    project: Path, worker: FakeWorker, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(["find", "add(", "--json"], capsys)
    assert code == 0
    data = json.loads(out)
    hits = [(h["pointer"], h["text"]) for h in data["hits"]]
    assert hits == [
        ("src/app.py:3", "print(add(1, 2))"),
        ("src/app.py:4", "print(add(3, 4))"),
        ("src/calc.py:1", "def add(a, b):"),
    ]
    assert data["files"] == 2 and worker.calls == []
    assert all("secret.txt" not in h["pointer"] for h in data["hits"])  # ignored


def test_many_hits_are_grouped_per_file_with_the_index_summary(
    project: Path, worker: FakeWorker, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / "src" / "big.py").write_text("x = 1  # marker\n" * 80, encoding="utf-8")
    index = project / ".orkestra" / "cache" / "map" / "index.json"
    index.parent.mkdir(parents=True)
    summary = {"path": "src/big.py", "summary": "Holds the markers.", "symbols": []}
    index.write_text(json.dumps({"files": [summary]}), encoding="utf-8")
    code, out, _ = _run(["--lang", "en", "find", "marker", "--max-hits", "10"], capsys)
    assert code == 0 and worker.calls == []
    assert "src/big.py: 80" in out and "Holds the markers." in out
    assert "src/big.py:1" in out and "src/big.py:50" not in out
    assert len(out.splitlines()) < 15


def test_find_with_a_question_asks_the_worker_about_the_hits(
    project: Path, worker: FakeWorker, capsys: pytest.CaptureFixture[str]
) -> None:
    worker.answer = "add is called twice, in src/app.py:3 and src/app.py:4."
    code, out, _ = _run(["find", "add(", "--ask", "Where is add used?", "--json"], capsys)
    data = json.loads(out)
    assert code == 0 and data["answer"].startswith("add is called twice")
    assert [p["valid"] for p in data["pointers"]] == [True, True]
    (call,) = worker.calls
    assert "Where is add used?" in call["user"] and "src/app.py:3" in call["user"]


def test_find_globs_regex_and_bad_patterns(
    project: Path, worker: FakeWorker, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(["find", r"def \w+", "--regex", "--glob", "src/calc.py", "--json"], capsys)
    assert [h["pointer"] for h in json.loads(out)["hits"]] == ["src/calc.py:1", "src/calc.py:5"]
    code, _, _ = _run(["find", "(", "--regex"], capsys)
    assert code == 2
    code, out, _ = _run(["find", "nothing-like-this", "--json"], capsys)
    assert code == 1 and json.loads(out)["hits"] == []  # like grep: no match is code 1


# --- the index hook --------------------------------------------------------------------


def test_map_install_hook_refreshes_the_index_after_each_commit(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    code, _, _ = _run(["map", "--install-hook"], capsys)
    assert code == 0
    hook = project / ".git" / "hooks" / "post-commit"
    text = hook.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh") and "orkestra map" in text and "--diff-filter=d" in text
    _run(["map", "--install-hook"], capsys)
    assert hook.read_text(encoding="utf-8").count("orkestra map >>>") == 1  # once
