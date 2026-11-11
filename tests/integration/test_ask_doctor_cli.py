from __future__ import annotations

import json
import re
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from orkestra import doctor
from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.state import consent, db


@pytest.fixture(autouse=True)
def no_answer_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests send the same question again on purpose (failover, budget, health):
    every request must reach a provider. The answer cache has its own tests (Faz 8a)."""
    from orkestra.cache import responses

    monkeypatch.setattr(responses, "load", lambda *args, **kwargs: None)


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
OLLAMA = "http://ollama.test:11434"
ROUTER = "https://router.test/api/v1"
FAKE_KEY = "sk-or-v1-THISISAFAKEKEYVALUE000000000000"

CONFIG = f"""\
version: 1
providers:
  ollama:
    type: ollama
    base_url: {OLLAMA}
    models:
      - id: coder
        tier: 1
        context_window: 16384
  router:
    type: openai_compat
    base_url: {ROUTER}
    api_key_env: ROUTER_KEY
    models:
      - id: provider/model
        tier: 2
  codex:
    type: cli_agent
    command: codex
"""


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Config with every provider already consented (consent itself: test_state_cli.py)."""
    path = tmp_path / "orkestra-home"
    path.mkdir()
    (path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    config = load_config(cwd=tmp_path, environ={}).config
    with closing(db.connect()) as conn:
        for name, provider in config.providers.items():
            consent.grant(conn, name, provider, db.local_now())
    return path


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    monkeypatch.chdir(path)
    return path


def _ollama_ok(content: str = "Hello from Ollama", reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "message": {"role": "assistant", "content": content},
            "done_reason": reason,
            "prompt_eval_count": 20,
            "eval_count": 4,
        },
    )


def _router_ok(content: str = "Hello from router", cost: float = 0.0021) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c",
            "object": "chat.completion",
            "created": 0,
            "model": "provider/model",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content},
                 "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 30, "completion_tokens": 6, "total_tokens": 36,
                      "cost": cost},
        },
    )  # fmt: skip


# --- ask -------------------------------------------------------------------------------


@respx.mock
def test_ask_json_stdout_is_only_the_envelope(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    route = respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama_ok())
    (workdir / "util.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    code, out, _ = _run(["ask", "What does f do?", "--context", "util.py", "--json"], capsys)
    assert code == 0
    env = json.loads(out)  # stdout is exactly one JSON document
    assert env["status"] == "ok"
    assert env["provider"] == "ollama"
    assert env["model"] == "coder"
    assert env["tier"] == 1
    assert env["attempts"] == 1
    assert env["usage"] == {"prompt_tokens": 20, "completion_tokens": 4, "cost_usd": 0.0}
    assert env["summary"] == "Hello from Ollama"
    body = json.loads(route.calls.last.request.content)
    assert body["options"]["num_ctx"] == 16384
    assert '<file path="util.py">' in body["messages"][1]["content"]

    run_dir = home / "runs" / env["run_id"]
    for name in ("envelope.json", "task.yaml", "output.md", "attempts/1/request.json",
                 "attempts/1/response.txt"):  # fmt: skip
        assert (run_dir / name).is_file(), name
    assert json.loads((run_dir / "envelope.json").read_text(encoding="utf-8")) == env
    assert (run_dir / "output.md").read_text(encoding="utf-8") == "Hello from Ollama"


@respx.mock
def test_ask_human_prints_answer_and_summary(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama_ok())
    code, out, err = _run(["ask", "hi"], capsys)
    assert code == 0
    assert out.strip() == "Hello from Ollama"
    assert "ollama/coder" in err


@respx.mock
def test_ask_router_with_tier_and_cost(
    home: Path, workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ROUTER_KEY", FAKE_KEY)
    respx.post(f"{ROUTER}/chat/completions").mock(return_value=_router_ok())
    code, out, err = _run(["ask", "hi", "--tier", "2", "--json"], capsys)
    assert code == 0
    env = json.loads(out)
    assert (env["provider"], env["model"], env["tier"]) == ("router", "provider/model", 2)
    assert env["usage"]["cost_usd"] == pytest.approx(0.0021)
    assert FAKE_KEY not in out + err


@respx.mock
def test_ask_auth_error_envelope_and_exit_3(
    home: Path, workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ROUTER_KEY", FAKE_KEY)
    respx.post(f"{ROUTER}/chat/completions").mock(
        return_value=httpx.Response(
            401, json={"error": {"message": f"Incorrect API key provided: {FAKE_KEY}"}}
        )
    )
    code, out, err = _run(["ask", "hi", "--provider", "router", "--json"], capsys)
    assert code == 3
    env = json.loads(out)
    assert env["status"] == "error"
    assert env["error"].startswith("All 1 candidate(s) failed")
    assert env["failovers"][0]["provider"] == "router"
    assert env["failovers"][0]["error"] == "ProviderAuthError"
    assert "authentication failed" in env["failovers"][0]["reason"]
    assert FAKE_KEY not in out + err
    run_dir = Path(env["output_path"] or (Path(home) / "runs" / env["run_id"] / "x")).parent
    assert FAKE_KEY not in (run_dir / "envelope.json").read_text(encoding="utf-8")


@respx.mock
def test_ask_length_warning(home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama_ok(reason="length"))
    code, out, err = _run(["ask", "hi", "--json"], capsys)
    assert code == 0
    json.loads(out)
    assert "output limit" in err


@respx.mock
def test_ask_schema_ok_and_failed(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    schema = workdir / "s.json"
    schema.write_text(
        json.dumps({"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}),
        encoding="utf-8",
    )
    bad = _ollama_ok('{"n": "three"}')
    route = respx.post(f"{OLLAMA}/api/chat").mock(
        side_effect=[_ollama_ok('```json\n{"n": 3}\n```'), bad, bad, bad]
    )
    code, out, _ = _run(["ask", "count", "--schema", str(schema), "--json"], capsys)
    assert code == 0
    env = json.loads(out)
    assert env["verification"] == [{"type": "json_schema", "ok": True, "detail": ""}]
    assert json.loads(route.calls[0].request.content)["format"] == "json"

    code, out, _ = _run(["ask", "count", "--schema", str(schema), "--json"], capsys)
    assert code == 1
    env = json.loads(out)
    assert env["status"] == "failed"
    assert env["attempts"] == 3  # first answer + defaults.max_retries (2) with feedback
    assert env["verification"][0]["ok"] is False
    assert env["verification"][0]["detail"].startswith("n:")


def test_ask_invalid_schema_file(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (workdir / "s.json").write_text("{not json", encoding="utf-8")
    code, out, _ = _run(["ask", "x", "--schema", "s.json", "--json"], capsys)
    assert code == 2
    assert json.loads(out)["error"]["type"] == "UsageError"


def test_ask_without_providers(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _run(["ask", "hi"], capsys)
    assert code == 2
    assert "orkestra init" in err


def test_ask_no_suitable_provider(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = _run(["ask", "hi", "--tier", "3"], capsys)
    assert code == 3
    assert "tier 1 is outside 3-3" in err


@respx.mock
def test_ask_ollama_down(home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(side_effect=httpx.ConnectError("refused"))
    code, _, err = _run(["ask", "hi"], capsys)
    assert code == 3
    assert "cannot connect" in err


# --- doctor ----------------------------------------------------------------------------


def _fake_which(found: dict[str, str]) -> Any:
    return lambda name: found.get(name)


@pytest.fixture
def tools(monkeypatch: pytest.MonkeyPatch) -> None:
    found = {"git": "/usr/bin/git", "codex": "/usr/bin/codex"}
    versions = {"/usr/bin/git": "git version 2.50.0", "/usr/bin/codex": "codex-cli 1.0.0"}

    async def fake_run_doctor(**kwargs: Any) -> doctor.DoctorReport:
        return await original(**kwargs, which=_fake_which(found), probe=versions.get,
                              login=lambda _: True)  # fmt: skip

    original = doctor.run_doctor
    monkeypatch.setattr(doctor, "run_doctor", fake_run_doctor)


def _mock_healthy(router_status: int = 200) -> None:
    respx.get(f"{OLLAMA}/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "other:7b"}]})
    )
    respx.get(f"{ROUTER}/models").mock(
        return_value=httpx.Response(
            router_status,
            json={"object": "list", "data": [{"id": "provider/model", "object": "model",
                                              "created": 0, "owned_by": "x"}]}
            if router_status == 200
            else {"error": {"message": f"Incorrect API key provided: {FAKE_KEY}"}},
        )
    )  # fmt: skip


@respx.mock
def test_doctor_json_report(
    home: Path,
    workdir: Path,
    tools: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ROUTER_KEY", FAKE_KEY)
    _mock_healthy()
    code, out, _ = _run(["doctor", "--json"], capsys)
    report = json.loads(out)
    checks = report["checks"]
    by_status = {(c["name"], c["status"]) for c in checks}
    assert ("config", "ok") in by_status
    assert ("provider:ollama", "ok") in by_status
    missing = [c for c in checks if c["data"].get("hint")]
    assert missing[0]["data"]["hint"] == "ollama pull coder"
    assert ("provider:router", "ok") in by_status
    key_check = next(c for c in checks if "api_key_env" in c["data"])
    assert key_check["data"] == {"api_key_env": "ROUTER_KEY", "present": True}
    codex = next(c for c in checks if c["name"] == "provider:codex")
    assert codex["data"]["version"] == "codex-cli 1.0.0"
    assert ("tool:git", "ok") in by_status
    assert ("tool:agy", "info") in by_status  # not installed: info only
    assert report["ok"] is True
    assert code == 0


@respx.mock
@pytest.mark.parametrize("as_json", [True, False])
def test_doctor_never_prints_key_value(
    as_json: bool,
    home: Path,
    workdir: Path,
    tools: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ROUTER_KEY", FAKE_KEY)
    _mock_healthy(router_status=401)  # error body echoes the key
    code, out, err = _run(["doctor", *(["--json"] if as_json else [])], capsys)
    assert FAKE_KEY not in out + err
    assert "ROUTER_KEY" in out
    assert code == 1  # auth failure is a FAIL line


@respx.mock
def test_doctor_missing_key_is_warning(
    home: Path, workdir: Path, tools: None, capsys: pytest.CaptureFixture[str]
) -> None:
    _mock_healthy()
    code, out, _ = _run(["--lang", "en", "doctor"], capsys)
    assert "[WARN] provider:router: environment variable ROUTER_KEY is not set" in out
    assert code == 0


def test_doctor_invalid_config(
    workdir: Path, tmp_path: Path, tools: None, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text("version: 2\n", encoding="utf-8")
    code, out, _ = _run(["doctor"], capsys)
    assert code == 1
    assert "[FAIL] config" in out
    assert "version: must be 1" in out


@respx.mock
def test_doctor_warm(
    home: Path, workdir: Path, tools: None, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.get(f"{OLLAMA}/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "coder:latest"}]})
    )
    chat = respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama_ok("OK"))
    _, out, _ = _run(["doctor", "--warm", "--json"], capsys)
    assert chat.called
    assert json.loads(chat.calls.last.request.content)["options"]["num_predict"] == 1
    warm = [c for c in json.loads(out)["checks"] if c["data"].get("warm")]
    assert warm and warm[0]["data"]["model"] == "coder"


# --- code review fixes (Faz 2, PR #3) ---------------------------------------------------


@respx.mock
def test_ollama_gets_the_cold_start_timeout(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama_ok())
    code, _, _ = _run(["ask", "hi", "--provider", "ollama", "--json"], capsys)
    assert code == 0
    run_dir = next((home / "runs").iterdir())
    request = json.loads((run_dir / "attempts" / "1" / "request.json").read_text("utf-8"))
    assert request["timeout_s"] == 600


@respx.mock
def test_doctor_warm_accepts_an_empty_first_token(
    home: Path, workdir: Path, tools: None, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.get(f"{OLLAMA}/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "coder:latest"}]})
    )
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama_ok("\n"))
    _, out, _ = _run(["doctor", "--warm", "--json"], capsys)
    warm = [c for c in json.loads(out)["checks"] if c["data"].get("model") == "coder"]
    assert warm and warm[0]["status"] == "ok" and warm[0]["data"]["warm"] is True


def test_schema_that_is_not_an_object_is_translated(
    home: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (workdir / "s.json").write_text("true", encoding="utf-8")  # valid schema, not an object
    code, _, err = _run(["--lang", "tr", "ask", "hi", "--schema", "s.json"], capsys)
    assert code == 2
    assert "not an object" not in err
    assert "nesne" in err


# --- Faz 5b ----------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "warned"), [(None, True), ("false", True), ("true", False)])
async def test_doctor_suggests_longpaths_on_windows(
    workdir: Path, value: str | None, warned: bool
) -> None:
    report = await doctor.run_doctor(
        which=lambda tool: f"/usr/bin/{tool}" if tool == "git" else None,
        probe=lambda path: "git version 2.50.0",
        git_config=lambda key: value,
        platform="win32",
    )
    hints = [c.data.get("hint") for c in report.checks if c.name == "tool:git"]
    assert ("git config --global core.longpaths true" in hints) is warned
    linux = await doctor.run_doctor(
        which=lambda tool: "/usr/bin/git" if tool == "git" else None,
        probe=lambda path: "git version 2.50.0",
        git_config=lambda key: None,
        platform="linux",
    )
    assert not any(c.data.get("hint", "").startswith("git config") for c in linux.checks)
