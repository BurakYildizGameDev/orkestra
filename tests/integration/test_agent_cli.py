"""Code agents in the task lifecycle (Faz 6): ``fixtures/fake_agent.py`` as the agent, a real
git repository and real pytest as the check.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from orkestra import paths
from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.state import consent, db

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_agent.py"
MakeRepo = Callable[..., Path]

FILES = {
    "calc.py": "def add(a, b):\n    return a - b\n",
    "tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    "README.md": "# calc\n",
}
PYTEST = f'"{sys.executable}" -m pytest -q -p no:cacheprovider tests'
RIGHT = "def add(a, b):\n    return a + b\n"


def _agent(mode: str, **fields: Any) -> dict[str, Any]:
    return {"type": "cli_agent", "command": sys.executable, "kind": "generic",
            "extra_args": [str(FAKE), mode], **fields}  # fmt: skip


def _setup(home: Path, cwd: Path, providers: dict[str, Any]) -> None:
    config = {"version": 1, "providers": providers}
    (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")  # JSON is YAML
    loaded = load_config(cwd=cwd, environ={}).config
    with closing(db.connect()) as conn:
        for name, provider in loaded.providers.items():
            consent.grant(conn, name, provider, db.local_now())


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


@pytest.fixture
def repo(make_repo: MakeRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = make_repo(FILES)
    monkeypatch.chdir(path)
    (tmp_path / "orkestra-home").mkdir(exist_ok=True)
    return path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "orkestra-home"


def _task(tmp_path: Path, **fields: Any) -> str:
    data: dict[str, Any] = {
        "id": "fix-add",
        "kind": "edit",
        "prompt": "Fix add() so that the tests pass.",
        "context": {"files": ["calc.py"]},
        "verify": [
            {"type": "command", "run": PYTEST},
            {"type": "protect_paths", "paths": ["tests/**"]},
        ],
        **fields,
    }
    path = tmp_path / "task.yaml"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


# --- edit ------------------------------------------------------------------------------


def test_agent_fixes_it_after_feedback_and_apply_brings_it_home(
    repo: Path, home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(home, repo, {"agent": _agent("flaky")})
    (repo / "notes.txt").write_bytes(b"mine\n")  # the user's untracked work
    code, out, _ = _run(["run", _task(tmp_path), "--json"], capsys)
    assert code == 0, out
    envelope = json.loads(out)
    assert envelope["status"] == "ok" and envelope["attempts"] == 2
    assert envelope["provider"] == "agent" and envelope["tier"] == 3
    assert envelope["changes"]["files"] == 1 and "fixed add()" in envelope["summary"]
    run_dir = paths.run_dir(envelope["run_id"])
    second = json.loads((run_dir / "attempts" / "2" / "request.json").read_bytes())
    assert "Failed checks" in second["prompt"]
    assert _read(repo / "calc.py") == FILES["calc.py"]
    code, diff, _ = _run(["show", envelope["run_id"], "--diff"], capsys)
    assert "+    return a + b" in diff and "__pycache__" not in diff
    code, _, _ = _run(["apply", envelope["run_id"]], capsys)
    assert code == 0 and _read(repo / "calc.py") == RIGHT
    assert _read(repo / "notes.txt") == "mine\n"


def test_an_agent_commit_is_still_diffed_against_the_baseline(
    repo: Path, home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(home, repo, {"agent": _agent("commit")})
    code, out, _ = _run(["run", _task(tmp_path), "--json"], capsys)
    assert code == 0, out
    run_id = json.loads(out)["run_id"]
    code, _, _ = _run(["apply", run_id], capsys)
    assert code == 0 and _read(repo / "calc.py") == RIGHT


def test_empty_output_moves_on_to_the_next_agent(
    repo: Path, home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(home, repo, {"mute": _agent("empty"), "agent": _agent("right")})
    code, out, _ = _run(["run", _task(tmp_path), "--json"], capsys)
    assert code == 0, out
    envelope = json.loads(out)
    assert envelope["provider"] == "agent"
    assert envelope["failovers"][0]["provider"] == "mute"
    assert envelope["failovers"][0]["error"] == "ProviderBadOutput"


def test_writing_outside_the_worktree_is_caught(
    repo: Path, home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    monkeypatch.setenv("FAKE_AGENT_ESCAPE", str(repo / "README.md"))
    _setup(home, repo, {"agent": _agent("escape")})
    task = _task(tmp_path, limits={"max_retries": 0})
    code, out, err = _run(["--lang", "en", "run", task, "--json"], capsys)
    assert code == 1
    envelope = json.loads(out)
    checks = {v["type"]: v for v in envelope["verification"]}
    assert checks["workspace_scope"]["ok"] is False
    assert "README.md" in checks["workspace_scope"]["detail"]
    assert "README.md" in err  # the user is warned: their checkout was touched
    assert _read(repo / "calc.py") == FILES["calc.py"]  # nothing was applied


def test_cannot_do_from_an_agent_escalates(
    repo: Path, home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(home, repo, {"agent": _agent("cannot")})
    code, out, _ = _run(["run", _task(tmp_path), "--json"], capsys)
    assert code == 1
    envelope = json.loads(out)
    assert envelope["status"] == "escalate" and "database" in envelope["summary"]


# --- routing ---------------------------------------------------------------------------


def test_a_large_file_goes_to_the_agent(
    repo: Path, home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(home, repo, {
        "ollama": {"type": "ollama", "base_url": "http://ollama.test:11434",
                   "models": [{"id": "coder", "tier": 1}]},
        "agent": _agent("right"),
    })  # fmt: skip
    (repo / "big.py").write_bytes(b"x = 1\n" * 401)
    code, out, _ = _run(["run", _task(tmp_path, context={"files": ["big.py"]}), "--dry-run",
                         "--json"], capsys)  # fmt: skip
    assert code == 0, out
    route = json.loads(out)
    assert [c["provider"] for c in route["candidates"]] == ["agent"]
    assert "edit_too_large" in {e["code"] for e in route["eliminated"]}


def test_agents_that_cannot_take_the_task_are_left_out(
    repo: Path, home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(home, repo, {
        "agy": {"type": "cli_agent", "command": "agy"},  # experimental, not acknowledged
        "viewer": _agent("right", sandbox="read-only"),
    })  # fmt: skip
    code, out, _ = _run(["run", _task(tmp_path), "--dry-run", "--json"], capsys)
    assert code == 3
    codes = {e["provider"]: e["code"] for e in json.loads(out)["eliminated"]}
    assert codes == {"agy": "agent_experimental", "viewer": "agent_read_only"}


# --- ask -------------------------------------------------------------------------------


def test_an_ask_task_for_an_agent(
    repo: Path, home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(home, repo, {"agent": _agent("echo")})
    task = tmp_path / "ask.yaml"
    task.write_text(json.dumps({"id": "q", "kind": "ask", "prompt": "What is this?"}),
                    encoding="utf-8")  # fmt: skip
    code, out, _ = _run(["run", str(task), "--json"], capsys)
    assert code == 0, out
    envelope = json.loads(out)
    assert envelope["status"] == "ok" and envelope["changes"] is None
    output = Path(envelope["output_path"]).read_bytes().decode()
    assert re.match(r"received \d+ chars", output)
