"""``orkestra exec`` end to end (Faz 13i-a): real pytest and ruff, a fake worker model.

What the chief gets must never lose the exit code or a failed test's name, every pointer must
show the real line, and the full output must stay in the log the answer names.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from orkestra.chief import execute
from orkestra.cli import app

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
PY = sys.executable
FAKE_KEY = "sk-or-v1-FAKEKEYVALUE1234567890abcdef"


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "proj"
    (folder / "tests").mkdir(parents=True)
    (folder / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    tests = "from calc import add\n\n\n" + "".join(
        f"def test_{n}():\n    assert add({n}, 1) == {n + 1}\n\n\n" for n in range(1, 4)
    )
    (folder / "tests" / "test_calc.py").write_text(tests, encoding="utf-8")
    (folder / "bad.py").write_text("import os\n\n\ndef f():\n    return nope\n", encoding="utf-8")
    monkeypatch.chdir(folder)
    return folder


def _line(folder: Path, pointer: str) -> str:
    file, line = pointer.split(":")[:2]
    return (folder / file).read_text(encoding="utf-8").splitlines()[int(line) - 1]


def _write_config(tmp_path: Path, text: str = "version: 1\n") -> None:
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(text, encoding="utf-8")


def test_short_output_comes_back_as_it_is_with_the_exit_code(
    work: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = "import sys; print('hello'); sys.exit(3)"
    code, out, _ = _run(["exec", "--", PY, "-c", script], capsys)
    assert code == 3
    assert "hello" in out and "3" in out.splitlines()[0]


def test_failing_pytest_keeps_every_name_and_points_at_the_real_line(
    work: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [PY, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:asyncio", "tests"]
    code, out, _ = _run(["exec", "--max-lines", "5", "--json", "--", *argv], capsys)
    assert code == 1
    data = json.loads(out)
    assert data["exit_code"] == 1 and data["parser"] == "pytest"
    assert data["headline"].startswith("3 failed")
    names = [item["text"] for item in data["items"]]
    assert names == [f"FAILED tests/test_calc.py::test_{n} - assert {n - 1} == {n + 1}"
                     for n in range(1, 4)]  # fmt: skip
    for item in data["items"]:
        assert _line(work, item["pointer"]).strip().startswith("assert add(")
    log = Path(data["log"])
    assert log.is_file() and "short test summary info" in log.read_text(encoding="utf-8")


def test_ruff_findings_point_at_the_real_line(
    work: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [PY, "-m", "ruff", "check", "--no-cache", "--output-format", "full", "bad.py"]
    code, out, _ = _run(["exec", "--max-lines", "3", "--json", "--", *argv], capsys)
    assert code == 1
    data = json.loads(out)
    assert data["parser"] == "ruff"
    by_code = {item["text"].split()[0]: item["pointer"] for item in data["items"]}
    assert "nope" in _line(work, by_code["F821"])
    assert "import os" in _line(work, by_code["F401"])


def test_human_output_is_a_header_and_the_digest(
    work: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [PY, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:asyncio", "tests"]
    code, out, _ = _run(["--lang", "en", "exec", "--max-lines", "5", "--", *argv], capsys)
    assert code == 1
    first, *rest = out.splitlines()
    assert "exit 1" in first and "pytest" in first and "output.log" in first
    assert rest[0].startswith("3 failed")
    assert sum("FAILED tests/test_calc.py::test_" in line for line in rest) == 3
    assert len(out.splitlines()) < 10


def _noisy(lines: int = 200) -> list[str]:
    script = f"import sys\nfor n in range({lines}): print('step', n)\nsys.exit(2)"
    return [PY, "-c", script]


def test_unknown_long_output_is_summarised_by_a_worker(
    work: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    _write_config(tmp_path)
    seen: dict[str, Any] = {}

    async def fake(config: object, **kwargs: Any) -> tuple[str, str]:
        seen.update(kwargs)
        return "It printed 200 steps and stopped with code 2.", "ollama/coder"

    monkeypatch.setattr(execute, "query_chief_model", fake)
    code, out, _ = _run(["exec", "--json", "--", *_noisy()], capsys)
    assert code == 2
    data = json.loads(out)
    assert data["kind"] == "model" and data["model"] == "ollama/coder"
    assert data["summary"] == "It printed 200 steps and stopped with code 2."
    assert "step 199" in seen["user"] and "exit code: 2" in seen["user"]
    assert seen["tier"] == 1


def test_without_a_worker_the_head_and_tail_are_shown(
    work: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(["--lang", "en", "exec", "--", *_noisy()], capsys)
    assert code == 2
    assert "step 0" in out and "step 199" in out and "step 100" not in out
    code, out, _ = _run(["exec", "--no-model", "--json", "--", *_noisy()], capsys)
    data = json.loads(out)
    assert data["kind"] == "head_tail" and "step 199" in data["summary"]


def test_a_failing_worker_falls_back_to_head_and_tail(
    work: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    from orkestra.errors import NoProviderAvailable

    _write_config(tmp_path)

    async def fake(config: object, **kwargs: Any) -> tuple[str, str]:
        raise NoProviderAvailable("no provider")

    monkeypatch.setattr(execute, "query_chief_model", fake)
    code, out, _ = _run(["exec", "--json", "--", *_noisy()], capsys)
    data = json.loads(out)
    assert code == 2 and data["kind"] == "head_tail" and data["note"]


def test_a_missing_program_is_exit_code_127(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(["exec", "--", "no-such-program-xyz"], capsys)
    assert code == 127 and "no-such-program-xyz" in out + err


def test_a_command_that_runs_too_long_is_stopped(
    work: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = "import time; print('started', flush=True); time.sleep(30)"
    code, out, _ = _run(["exec", "--timeout", "1", "--json", "--", PY, "-c", script], capsys)
    data = json.loads(out)
    assert code == 124 and data["timed_out"] and "started" in data["summary"]


def test_keys_never_reach_the_log(
    work: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    _write_config(tmp_path, (
        "version: 1\nproviders:\n  router:\n    type: openai_compat\n"
        "    base_url: https://router.test/v1\n    api_key_env: ROUTER_KEY\n"
        "    models:\n      - id: m\n        tier: 1\n"
    ))  # fmt: skip
    monkeypatch.setenv("ROUTER_KEY", FAKE_KEY)
    code, out, _ = _run(["exec", "--json", "--", PY, "-c", f"print('{FAKE_KEY}')"], capsys)
    assert code == 0
    data = json.loads(out)
    assert FAKE_KEY not in out
    assert FAKE_KEY not in Path(data["log"]).read_text(encoding="utf-8")


def test_a_summary_never_starts_a_code_agent(
    work: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    from contextlib import closing

    from orkestra.config.loader import load_config
    from orkestra.state import consent, db

    fake = Path(__file__).resolve().parents[1] / "fixtures" / "fake_agent.py"
    marker = tmp_path / "agent-ran.txt"
    monkeypatch.setenv("FAKE_AGENT_ESCAPE", str(marker))
    config = {"version": 1, "providers": {"agent": {
        "type": "cli_agent", "command": PY, "kind": "generic", "tier": 1,
        "extra_args": [str(fake), "escape"]}}}  # fmt: skip
    _write_config(tmp_path, json.dumps(config))
    loaded = load_config(cwd=work, environ={}).config
    with closing(db.connect()) as conn:
        consent.grant(conn, "agent", loaded.providers["agent"], db.local_now())
    code, out, _ = _run(["exec", "--json", "--", *_noisy()], capsys)
    data = json.loads(out)
    assert code == 2 and data["kind"] == "head_tail"
    assert not marker.exists()  # the agent was never started
    assert "\n" not in data["note"]


def test_a_long_reason_is_one_short_line(
    work: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    from orkestra.errors import ProviderBadOutput

    _write_config(tmp_path)

    async def fake(config: object, **kwargs: Any) -> tuple[str, str]:
        raise ProviderBadOutput("first line\n" + "x" * 500)

    monkeypatch.setattr(execute, "query_chief_model", fake)
    _, out, _ = _run(["exec", "--json", "--", *_noisy()], capsys)
    note = json.loads(out)["note"]
    assert note.startswith("first line") and "\n" not in note and len(note) <= 160


def test_a_paused_chat_model_is_named_as_the_reason(
    work: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from contextlib import closing

    from orkestra.config.loader import load_config
    from orkestra.errors import ProviderAuthError
    from orkestra.state import consent, db, health

    _write_config(tmp_path, json.dumps({"version": 1, "providers": {"ollama": {
        "type": "ollama", "base_url": "http://ollama.test:11434",
        "models": [{"id": "coder", "tier": 1}]}}}))  # fmt: skip
    loaded = load_config(cwd=work, environ={}).config
    with closing(db.connect()) as conn:
        consent.grant(conn, "ollama", loaded.providers["ollama"], db.local_now())
        health.record_failure(conn, "ollama", ProviderAuthError("down"), db.local_now())
    _, out, _ = _run(["--lang", "en", "exec", "--json", "--", *_noisy()], capsys)
    note = json.loads(out)["note"]
    assert "ollama" in note and "paused" in note
