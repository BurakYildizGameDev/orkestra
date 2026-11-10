"""``orkestra run <task>``: verify, retry with feedback, escalate (Faz 5a).

Real CLI, respx for HTTP, real subprocesses for ``command`` verifiers.
"""

from __future__ import annotations

import json
import re
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.state import consent, db

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
OLLAMA = "http://ollama.test:11434"
ROUTER = "https://router.test/api/v1"

CONFIG = f"""\
version: 1
providers:
  ollama:
    type: ollama
    base_url: {OLLAMA}
    models:
      - id: coder
        tier: 1
  router:
    type: openai_compat
    base_url: {ROUTER}
    api_key_env: ROUTER_KEY
    models:
      - id: smart/model
        tier: 2
      - id: big/model
        tier: 3
"""


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "orkestra-home"
    path.mkdir()
    (path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("ROUTER_KEY", "sk-or-v1-RUNTESTKEY000000000000000000000")
    config = load_config(cwd=work, environ={}).config
    with closing(db.connect()) as conn:
        for name, provider in config.providers.items():
            consent.grant(conn, name, provider, db.local_now())
    return path


def _task(name: str = "task.yaml", **fields: Any) -> str:
    data: dict[str, Any] = {"id": "greet", "kind": "ask", "prompt": "Say OK.", **fields}
    Path(name).write_text(json.dumps(data), encoding="utf-8")  # JSON is valid YAML
    return name


def _ollama(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"message": {"content": content}, "done_reason": "stop",
              "prompt_eval_count": 5, "eval_count": 2},
    )  # fmt: skip


def _chat(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        },
    )  # fmt: skip


def _ollama_user(request: httpx.Request) -> str:
    return json.loads(request.content)["messages"][1]["content"]


MUST_OK = [{"type": "regex", "must_match": ["^OK"]}]


# --- retry with feedback ---------------------------------------------------------------


@respx.mock
def test_failed_check_is_retried_with_feedback(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ollama = respx.post(f"{OLLAMA}/api/chat").mock(
        side_effect=[_ollama("nope"), _ollama("OK, done")]
    )
    code, out, _ = _run(["run", _task(verify=MUST_OK), "--json"], capsys)
    assert code == 0
    env = json.loads(out)
    assert (env["status"], env["task_id"], env["provider"], env["attempts"]) == (
        "ok", "greet", "ollama", 2,
    )  # fmt: skip
    assert env["verification"] == [{"type": "regex", "ok": True, "detail": ""}]
    assert env["failovers"] == []
    first, second = (_ollama_user(c.request) for c in ollama.calls)
    assert "previous answer" not in first.lower()
    assert "did not pass verification" in second
    assert "nope" in second  # the previous answer
    assert "regex: pattern not found: ^OK" in second  # what failed, in English
    run_dir = home / "runs" / env["run_id"]
    assert (run_dir / "attempts" / "1" / "verify.log").is_file()
    assert (run_dir / "output.md").read_text(encoding="utf-8") == "OK, done"


@respx.mock
def test_feedback_is_english_while_the_envelope_follows_the_ui(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ollama = respx.post(f"{OLLAMA}/api/chat").mock(
        side_effect=[_ollama("nope"), _ollama("nope"), _ollama("nope")]
    )
    code, out, _ = _run(
        ["--lang", "tr", "run", _task(verify=MUST_OK), "--json", "--profile", "cheap"], capsys
    )
    assert code == 1
    env = json.loads(out)
    assert "pattern not found" not in env["verification"][0]["detail"]
    assert "pattern not found: ^OK" in _ollama_user(ollama.calls[1].request)


# --- escalation ------------------------------------------------------------------------


@respx.mock
def test_tier_1_fails_twice_then_tier_2_answers(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ollama = respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama("nope"))
    router = respx.post(f"{ROUTER}/chat/completions").mock(return_value=_chat("OK from tier 2"))
    code, out, _ = _run(["run", _task(verify=MUST_OK, limits={"max_retries": 1}), "--json"], capsys)
    assert code == 0
    env = json.loads(out)
    assert (env["status"], env["provider"], env["model"], env["tier"]) == (
        "ok", "router", "smart/model", 2,
    )  # fmt: skip
    assert ollama.call_count == 2  # first try + one retry with feedback
    assert router.call_count == 1
    assert env["attempts"] == 3
    assert [(f["provider"], f["error"], f["attempts"]) for f in env["failovers"]] == [
        ("ollama", "VerificationFailed", 2)
    ]
    assert [(e["provider"], e["model"], e["tier"]) for e in env["escalations"]] == [
        ("ollama", "coder", 1)
    ]


@respx.mock
def test_failing_everywhere_below_tier_3_is_failed(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama("nope"))
    code, out, _ = _run(
        ["run", _task(verify=MUST_OK, limits={"max_retries": 0}), "--json", "--profile", "cheap"],
        capsys,
    )
    assert code == 1
    env = json.loads(out)
    assert env["status"] == "failed"
    assert env["verification"][0]["ok"] is False
    assert env["output_path"] and Path(env["output_path"]).is_file()


@respx.mock
def test_failing_up_to_tier_3_is_escalate(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama("nope"))
    router = respx.post(f"{ROUTER}/chat/completions").mock(return_value=_chat("still nope"))
    code, out, _ = _run(["run", _task(verify=MUST_OK, limits={"max_retries": 0}), "--json"], capsys)
    assert code == 1
    env = json.loads(out)
    assert env["status"] == "escalate"
    assert (env["model"], env["tier"]) == ("big/model", 3)
    assert router.call_count == 2
    assert [e["tier"] for e in env["escalations"]] == [1, 2]


@respx.mock
def test_cannot_do_is_not_retried_on_the_same_candidate(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ollama = respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama("CANNOT_DO: unclear"))
    respx.post(f"{ROUTER}/chat/completions").mock(return_value=_chat("OK"))
    code, out, _ = _run(["run", _task(verify=MUST_OK), "--json"], capsys)
    assert code == 0
    assert ollama.call_count == 1
    assert json.loads(out)["tier"] == 2


# --- verifiers -------------------------------------------------------------------------


@respx.mock
def test_command_verifier_runs_in_the_working_directory(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama("OK"))
    Path("marker.txt").write_text("x", encoding="utf-8")
    check = f"\"{sys.executable}\" -c \"import os; print('found', os.path.exists('marker.txt'))\""
    verify = [{"type": "command", "run": check}, {"type": "files_exist", "paths": ["marker.txt"]}]
    code, out, _ = _run(["run", _task(verify=verify), "--json", "--profile", "cheap"], capsys)
    assert code == 0
    command, exists = json.loads(out)["verification"]
    assert command["ok"] and "found True" in command["detail"]
    assert exists["ok"]


@respx.mock
def test_json_output_with_schema(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    Path("s.json").write_text(
        json.dumps({"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}),
        encoding="utf-8",
    )
    ollama = respx.post(f"{OLLAMA}/api/chat").mock(
        side_effect=[_ollama('{"n": "three"}'), _ollama('{"n": 3}')]
    )
    task = _task(output={"format": "json", "schema": "s.json"})
    code, out, _ = _run(["run", task, "--json", "--profile", "cheap"], capsys)
    assert code == 0
    assert json.loads(out)["attempts"] == 2
    assert json.loads(ollama.calls[0].request.content)["format"] == "json"


@respx.mock
def test_context_globs_respect_gitignore(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    Path("notes").mkdir()
    Path("notes/a.txt").write_text("alpha", encoding="utf-8")
    Path("notes/b.txt").write_text("beta", encoding="utf-8")
    Path("notes/secret.txt").write_text("gamma", encoding="utf-8")
    Path(".gitignore").write_text("notes/secret.txt\n", encoding="utf-8")
    ollama = respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama("OK"))
    task = _task(context={"globs": ["notes/*.txt"]})
    code, _, _ = _run(["run", task, "--profile", "cheap"], capsys)
    assert code == 0
    user = _ollama_user(ollama.calls[0].request)
    assert '<file path="notes/a.txt">' in user and '<file path="notes/b.txt">' in user
    assert "gamma" not in user


# --- dry run and errors ----------------------------------------------------------------


def test_dry_run(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["run", _task(tier=2), "--dry-run", "--json"], capsys)
    assert code == 0
    plan = json.loads(out)
    assert plan["tier_range"] == [2, 3]
    assert [c["model"] for c in plan["candidates"]] == ["smart/model", "big/model"]
    assert not (home / "runs").exists()


def test_invalid_task_file(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    Path("bad.yaml").write_text("id: x\nkind: ask\n", encoding="utf-8")
    code, out, _ = _run(["--lang", "en", "run", "bad.yaml", "--json"], capsys)
    assert code == 2
    error = json.loads(out)["error"]
    assert "prompt: required field is missing" in error["details"]


def test_edit_tasks_are_not_available_yet(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _run(["--lang", "en", "run", _task(kind="edit")], capsys)
    assert code == 2
    assert "edit" in err


# --- code review fixes (PR #6) ---------------------------------------------------------


@respx.mock
def test_command_output_in_the_envelope_is_redacted(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama("OK"))
    leak = (
        f'"{sys.executable}" -c "import os; print(os.environ[\'ROUTER_KEY\']); raise SystemExit(1)"'
    )
    task = _task(verify=[{"type": "command", "run": leak}], limits={"max_retries": 0})
    code, out, err = _run(["run", task, "--json", "--profile", "cheap"], capsys)
    assert code == 1
    assert "RUNTESTKEY" not in out + err
    assert "***" in json.loads(out)["verification"][0]["detail"]


@respx.mock
def test_schema_given_on_a_verifier_reaches_the_prompt(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    Path("s.json").write_text(
        json.dumps({"type": "object", "required": ["answer_field"]}), encoding="utf-8"
    )
    ollama = respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama('{"answer_field": 1}'))
    task = _task(output={"format": "json"}, verify=[{"type": "json_schema", "schema": "s.json"}])
    code, _, _ = _run(["run", task, "--profile", "cheap"], capsys)
    assert code == 0
    assert "answer_field" in _ollama_user(ollama.calls[0].request)


@respx.mock
def test_json_output_without_schema_asks_for_json(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ollama = respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama("[1, 2]"))
    code, _, _ = _run(["run", _task(output={"format": "json"}), "--profile", "cheap"], capsys)
    assert code == 0
    assert "single JSON value" in _ollama_user(ollama.calls[0].request)


@respx.mock
def test_envelope_usage_counts_every_answer(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(side_effect=[_ollama("nope"), _ollama("OK")])
    code, out, _ = _run(["run", _task(verify=MUST_OK), "--json", "--profile", "cheap"], capsys)
    assert code == 0
    usage = json.loads(out)["usage"]
    assert (usage["prompt_tokens"], usage["completion_tokens"]) == (10, 4)  # 2 x (5, 2)
