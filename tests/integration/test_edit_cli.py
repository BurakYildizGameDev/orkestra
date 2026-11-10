"""Edit tasks end to end (Faz 5c): fake API workers, a real git repository, real pytest.

The worker answers with whole files (Mimari §8.2); the run happens in a worktree, the user's
checkout only changes on ``orkestra apply``.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from orkestra import paths
from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.state import consent, db
from orkestra.tasks import runner, spec
from orkestra.workspace import git_worktree as gw

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
OLLAMA = "http://ollama.test:11434"
ROUTER = "https://router.test/api/v1"
MakeRepo = Callable[..., Path]

# These workers answer with whole files (Faz 5c); SEARCH/REPLACE answers (the default since
# Faz 9c) are tested with ``edit_format: replace`` in the task file.
CONFIG = f"""\
version: 1
providers:
  ollama:
    type: ollama
    base_url: {OLLAMA}
    models:
      - id: coder
        tier: 1
        edit_format: whole
  router:
    type: openai_compat
    base_url: {ROUTER}
    api_key_env: ROUTER_KEY
    models:
      - id: smart/model
        tier: 2
        edit_format: whole
      - id: big/model
        tier: 3
        edit_format: whole
"""

FILES = {
    "calc.py": "def add(a, b):\n    return a - b\n",
    "tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    "README.md": "# calc\n",
}
PYTEST = f'"{sys.executable}" -m pytest -q -p no:cacheprovider tests'
WRONG = "def add(a, b):\n    return a * b\n"
RIGHT = "def add(a, b):\n    return a + b\n"


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


@pytest.fixture
def repo(make_repo: MakeRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(CONFIG, encoding="utf-8")
    path = make_repo(FILES)
    monkeypatch.chdir(path)
    monkeypatch.setenv("ROUTER_KEY", "sk-or-v1-EDITTESTKEY00000000000000000000")
    config = load_config(cwd=path, environ={}).config
    with closing(db.connect()) as conn:
        for name, provider in config.providers.items():
            consent.grant(conn, name, provider, db.local_now())
    return path


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
    path = tmp_path / "task.yaml"  # outside the repository
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _edit(*files: tuple[str, str], note: str = "done", fence: bool = False) -> str:
    text = json.dumps({"files": [{"path": p, "content": c} for p, c in files], "note": note})
    return f"```json\n{text}\n```" if fence else text


def _ollama(content: str, done_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={"message": {"content": content}, "done_reason": done_reason,
              "prompt_eval_count": 50, "eval_count": 20},
    )  # fmt: skip


def _chat(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
        },
    )  # fmt: skip


def _user(request: httpx.Request) -> str:
    return json.loads(request.content)["messages"][-1]["content"]


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


# --- the full loop ---------------------------------------------------------------------


@respx.mock
def test_tests_fail_then_feedback_fixes_it_and_apply_brings_it_home(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The user has uncommitted work of their own.
    (repo / "README.md").write_bytes(b"# calc\nmy uncommitted note\n")
    (repo / "notes.txt").write_bytes(b"untracked\n")
    right = _edit(("calc.py", RIGHT), note="add now adds", fence=True)
    chat = respx.post(f"{OLLAMA}/api/chat").mock(
        side_effect=[_ollama(_edit(("calc.py", WRONG))), _ollama(right)]
    )
    code, out, _ = _run(["run", _task(tmp_path), "--json"], capsys)
    assert code == 0, out
    envelope = json.loads(out)
    assert envelope["status"] == "ok" and envelope["attempts"] == 2
    assert envelope["changes"]["files"] == 1
    assert (envelope["changes"]["insertions"], envelope["changes"]["deletions"]) == (1, 1)
    assert "calc.py" in envelope["summary"] and "add now adds" in envelope["summary"]
    assert {v["type"] for v in envelope["verification"]} >= {"command", "protect_paths"}
    first, second = (_user(c.request) for c in chat.calls)
    assert "Failed checks" not in first and "calc.py" in first
    assert "Failed checks" in second and "command" in second
    # The user's checkout is untouched until apply.
    assert _read(repo / "calc.py") == FILES["calc.py"]
    run_id = envelope["run_id"]
    code, diff, _ = _run(["show", run_id, "--diff"], capsys)
    assert "+    return a + b" in diff
    assert "__pycache__" not in diff and ".pyc" not in diff  # verifier leftovers stay out
    code, _, _ = _run(["apply", run_id], capsys)
    assert code == 0
    assert _read(repo / "calc.py") == RIGHT
    assert _read(repo / "README.md") == "# calc\nmy uncommitted note\n"
    assert _read(repo / "notes.txt") == "untracked\n"
    assert not (repo / "__pycache__").exists()


@respx.mock
def test_changing_a_protected_test_fails_verification(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cheat = "def test_add():\n    assert True\n"
    respx.post(f"{OLLAMA}/api/chat").mock(
        return_value=_ollama(_edit(("tests/test_calc.py", cheat)))
    )
    task = _task(
        tmp_path, context={"files": ["calc.py", "tests/test_calc.py"]}, provider="ollama",
        limits={"max_retries": 0},
    )  # fmt: skip
    code, out, _ = _run(["--lang", "en", "run", task, "--json"], capsys)
    assert code == 1
    envelope = json.loads(out)
    assert envelope["status"] == "failed"
    (check,) = envelope["verification"]  # rejected before anything was written
    assert check["type"] == "edit_format" and check["ok"] is False
    assert "protected" in check["detail"]
    assert _read(repo / "tests" / "test_calc.py") == FILES["tests/test_calc.py"]


@respx.mock
def test_a_path_outside_the_project_is_rejected_and_nothing_is_written(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    escape = _edit(("../outside.txt", "pwned\n"), (str(tmp_path / "abs.txt"), "pwned\n"))
    chat = respx.post(f"{OLLAMA}/api/chat").mock(
        side_effect=[_ollama(escape), _ollama(_edit(("calc.py", RIGHT)))]
    )
    code, out, _ = _run(["run", _task(tmp_path), "--json"], capsys)
    assert code == 0, out
    envelope = json.loads(out)
    assert envelope["attempts"] == 2
    assert "not allowed" in _user(chat.calls[1].request)
    assert not (tmp_path / "abs.txt").exists() and not (tmp_path / "outside.txt").exists()
    worktrees = paths.worktrees_dir()
    assert not list(worktrees.rglob("outside.txt"))


@respx.mock
def test_broken_json_gets_feedback(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chat = respx.post(f"{OLLAMA}/api/chat").mock(
        side_effect=[_ollama('{"files": [{"path": "calc.py", '), _ollama(_edit(("calc.py", RIGHT)))]
    )
    code, out, _ = _run(["run", _task(tmp_path), "--json"], capsys)
    assert code == 0, out
    assert "not valid JSON" in _user(chat.calls[1].request)


@respx.mock
def test_tier_1_fails_twice_then_tier_2_fixes_it(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama(_edit(("calc.py", WRONG))))
    respx.post(f"{ROUTER}/chat/completions").mock(return_value=_chat(_edit(("calc.py", RIGHT))))
    code, out, _ = _run(["run", _task(tmp_path, limits={"max_retries": 1}), "--json"], capsys)
    assert code == 0, out
    envelope = json.loads(out)
    assert envelope["provider"] == "router" and envelope["tier"] == 2
    assert envelope["attempts"] == 3
    assert [e["provider"] for e in envelope["escalations"]] == ["ollama"]


@respx.mock
def test_a_cut_off_answer_goes_straight_to_tier_3(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(
        return_value=_ollama('{"files": [{"path": "calc.py", "content": "def', "length")
    )

    def by_model(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        assert model == "big/model", "tier 2 must be skipped"
        return _chat(_edit(("calc.py", RIGHT)))

    respx.post(f"{ROUTER}/chat/completions").mock(side_effect=by_model)
    code, out, _ = _run(["run", _task(tmp_path), "--json"], capsys)
    assert code == 0, out
    envelope = json.loads(out)
    assert envelope["model"] == "big/model" and envelope["attempts"] == 2
    assert envelope["failovers"][0]["error"] == "OutputTruncated"


def test_a_file_too_large_for_an_api_edit_leaves_no_chat_candidate(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "big.py").write_bytes(b"x = 1\n" * 401)  # security.max_api_edit_lines: 400
    task = _task(tmp_path, context={"files": ["big.py"]})
    code, out, _ = _run(["run", task, "--dry-run", "--json"], capsys)
    assert code == 3
    route = json.loads(out)
    assert route["candidates"] == []
    assert "edit_too_large" in {e["code"] for e in route["eliminated"]}


# --- interruption ----------------------------------------------------------------------


@respx.mock
def test_ctrl_c_releases_the_reservation_and_keeps_the_worktree(repo: Path, tmp_path: Path) -> None:
    def interrupt(_request: httpx.Request) -> httpx.Response:
        raise KeyboardInterrupt

    respx.post(f"{OLLAMA}/api/chat").mock(side_effect=interrupt)
    task = spec.load_task(Path(_task(tmp_path)))
    config = load_config(cwd=repo).config
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(runner.run_task(task, config, cwd=repo))
    (run_dir,) = paths.runs_dir().iterdir()
    envelope = json.loads((run_dir / "envelope.json").read_bytes())
    assert envelope["status"] == "error" and envelope["error"] == "interrupted"
    record = gw.load_record(run_dir)
    assert record is not None and record.state == "active" and record.worktree.path.is_dir()
    with closing(db.connect()) as conn:
        left = conn.execute("SELECT COUNT(*) FROM usage WHERE kind = 'reservation'").fetchone()
    assert left[0] == 0


# --- code review fixes (PR #8) -----------------------------------------------------------


@respx.mock
def test_a_non_utf8_context_file_is_read_only(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    legacy = "# yorum: \u015fe\u011fil\nx = 1\n".encode("cp1254")
    (repo / "legacy.py").write_bytes(legacy)
    chat = respx.post(f"{OLLAMA}/api/chat").mock(
        side_effect=[
            _ollama(_edit(("legacy.py", "# yorum: ?\nx = 2\n"))),
            _ollama(_edit(("calc.py", RIGHT))),
        ]
    )
    task = _task(tmp_path, context={"files": ["calc.py", "legacy.py"]})
    code, out, err = _run(["--lang", "en", "run", task, "--json"], capsys)
    assert code == 0, out
    assert "legacy.py" in err and "UTF-8" in err
    assert "You may change these files: calc.py\n" in _user(chat.calls[0].request)
    assert "not given in the context" in _user(chat.calls[1].request)
    assert (repo / "legacy.py").read_bytes() == legacy


@respx.mock
def test_gitignored_paths_are_rejected(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / ".gitignore").write_bytes(b"local/\n")
    chat = respx.post(f"{OLLAMA}/api/chat").mock(
        side_effect=[
            _ollama(_edit(("calc.py", RIGHT), ("local/sitecustomize.py", "x = 1\n"))),
            _ollama(_edit(("calc.py", RIGHT))),
        ]
    )
    code, out, _ = _run(["run", _task(tmp_path), "--json"], capsys)
    assert code == 0, out
    assert json.loads(out)["attempts"] == 2
    assert "ignored by git" in _user(chat.calls[1].request)


@respx.mock
def test_a_path_that_cannot_be_written_is_feedback_not_a_crash(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chat = respx.post(f"{OLLAMA}/api/chat").mock(
        side_effect=[
            _ollama(_edit(("calc.py/fix.py", "x = 1\n"))),
            _ollama(_edit(("calc.py", RIGHT))),
        ]
    )
    code, out, _ = _run(["run", _task(tmp_path), "--json"], capsys)
    assert code == 0, out
    assert "calc.py/fix.py" in _user(chat.calls[1].request)


@respx.mock
def test_cannot_do_in_json_escalates_at_once(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ollama = respx.post(f"{OLLAMA}/api/chat").mock(
        return_value=_ollama('{"cannot_do": "needs the database schema"}')
    )
    respx.post(f"{ROUTER}/chat/completions").mock(return_value=_chat(_edit(("calc.py", RIGHT))))
    code, out, _ = _run(["run", _task(tmp_path), "--json"], capsys)
    assert code == 0, out
    assert ollama.call_count == 1
    assert "cannot_do" in _user(ollama.calls[0].request)  # the worker is told how
    assert json.loads(out)["escalations"][0]["provider"] == "ollama"


@respx.mock
def test_a_failed_run_is_applied_only_with_force(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama(_edit(("calc.py", WRONG))))
    task = _task(tmp_path, provider="ollama", limits={"max_retries": 0})
    code, _, err = _run(["--lang", "en", "run", task], capsys)
    assert code == 1
    assert "orkestra apply" not in err and "--diff" in err
    run_id = next(paths.runs_dir().iterdir()).name
    code, _, err = _run(["--lang", "en", "apply", run_id], capsys)
    assert code == 2 and "--force" in err
    assert _read(repo / "calc.py") == FILES["calc.py"]
    code, _, _ = _run(["apply", run_id, "--force"], capsys)
    assert code == 0 and _read(repo / "calc.py") == WRONG


@respx.mock
def test_protected_context_files_are_not_offered_and_do_not_count_as_large(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    long_test = "def test_add():\n    assert True\n" + "# filler\n" * 600
    (repo / "tests" / "test_big.py").write_bytes(long_test.encode())
    chat = respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama(_edit(("calc.py", RIGHT))))
    task = _task(tmp_path, context={"files": ["calc.py", "tests/test_big.py"]})
    code, out, _ = _run(["run", task, "--json"], capsys)
    assert code == 0, out
    assert "You may change these files: calc.py\n" in _user(chat.calls[0].request)


@respx.mock
def test_a_run_without_a_change_removes_its_worktree(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama("CANNOT_DO: no idea"))
    task = _task(tmp_path, provider="ollama")
    code, out, _ = _run(["run", task, "--json"], capsys)
    assert code == 1
    envelope = json.loads(out)
    assert envelope["status"] == "escalate" and "tier 3" not in envelope["summary"]
    record = gw.load_record(paths.run_dir(envelope["run_id"]))
    assert record is not None and record.state == "discarded"
    assert not record.worktree.path.exists()


def test_a_repository_without_commits_is_a_usage_error_before_the_run(
    make_repo: MakeRepo, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    empty = tmp_path / "empty"
    empty.mkdir()
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=empty, check=True)
    (empty / "calc.py").write_bytes(FILES["calc.py"].encode())
    monkeypatch.chdir(empty)
    code, _, err = _run(["--lang", "en", "run", _task(tmp_path)], capsys)
    assert code == 2 and "no commits" in err
    assert not paths.runs_dir().exists() or not any(paths.runs_dir().iterdir())


# --- SEARCH/REPLACE (Faz 9c) -------------------------------------------------------------


def _blocks(*blocks: tuple[str, str, str], note: str = "fixed it") -> str:
    body = "".join(
        f"{path}\n<<<<<<< SEARCH\n{search}=======\n{replace}>>>>>>> REPLACE\n"
        for path, search, replace in blocks
    )
    return f"```\n{body}```\n{note}\n"


@respx.mock
def test_search_replace_feedback_then_apply(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wrong = _blocks(("calc.py", "    return a -b\n", "    return a + b\n"))  # not in the file
    right = _blocks(("calc.py", "    return a - b\n", "    return a + b\n"), note="add adds")
    chat = respx.post(f"{OLLAMA}/api/chat").mock(side_effect=[_ollama(wrong), _ollama(right)])
    code, out, _ = _run(["run", _task(tmp_path, edit_format="replace"), "--json"], capsys)
    assert code == 0, out
    envelope = json.loads(out)
    assert envelope["status"] == "ok" and envelope["attempts"] == 2
    assert envelope["edit_format"] == "replace"
    assert "add adds" in envelope["summary"]
    first, second = (json.loads(c.request.content) for c in chat.calls)
    assert "format" not in first  # plain text, not Ollama's JSON mode
    assert "SEARCH/REPLACE" in first["messages"][-1]["content"]
    feedback = second["messages"][-1]["content"]
    assert "SEARCH lines are not in calc.py" in feedback and "return a - b" in feedback
    code, _, _ = _run(["apply", envelope["run_id"]], capsys)
    assert code == 0 and _read(repo / "calc.py") == RIGHT


@respx.mock
def test_search_replace_keeps_every_line_it_does_not_touch(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = [f"VALUE_{n} = {n}\n" for n in range(500)]  # larger than max_api_edit_lines
    (repo / "big.py").write_bytes("".join(lines).encode())
    answer = _blocks(("big.py", "VALUE_250 = 250\n", "VALUE_250 = 2500\n"))
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama(answer))
    task = _task(tmp_path, context={"files": ["big.py"]}, verify=[], edit_format="replace")
    code, out, _ = _run(["run", task, "--json"], capsys)
    assert code == 0, out
    envelope = json.loads(out)
    assert envelope["provider"] == "ollama"  # no code agent needed for a large file
    assert (envelope["changes"]["insertions"], envelope["changes"]["deletions"]) == (1, 1)
    _run(["apply", envelope["run_id"]], capsys)
    expected = [*lines[:250], "VALUE_250 = 2500\n", *lines[251:]]
    assert _read(repo / "big.py") == "".join(expected)


def test_dry_run_shows_the_edit_format(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(["run", _task(tmp_path), "--dry-run", "--json"], capsys)
    assert code == 0
    assert {c["edit_format"] for c in json.loads(out)["candidates"]} == {"whole"}  # config
    task = _task(tmp_path, edit_format="replace")
    code, out, _ = _run(["--lang", "en", "run", task, "--dry-run"], capsys)
    assert code == 0 and "edit format replace" in out


def test_auto_uses_whole_files_for_small_files_and_blocks_for_large_ones(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(["run", _task(tmp_path, edit_format="auto"), "--dry-run", "--json"],
                        capsys)  # fmt: skip
    assert code == 0
    assert {c["edit_format"] for c in json.loads(out)["candidates"]} == {"whole"}
    (repo / "big.py").write_bytes(b"x = 1\n" * 401)  # security.max_api_edit_lines: 400
    task = _task(tmp_path, context={"files": ["big.py"]}, edit_format="auto")
    code, out, _ = _run(["run", task, "--dry-run", "--json"], capsys)
    assert code == 0
    route = json.loads(out)
    assert {c["edit_format"] for c in route["candidates"]} == {"replace"}
    assert "edit_too_large" not in {e["code"] for e in route["eliminated"]}
