from __future__ import annotations

import io
import json
import re
from contextlib import closing
from pathlib import Path

import httpx
import pytest
import respx

from orkestra.cli import app
from orkestra.state import db

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
OLLAMA = "http://ollama.test:11434"
ROUTER = "https://router.test/api/v1"
FAKE_KEY = "sk-or-v1-FAKEKEYFORSTATETESTS000000000000"

CONFIG = f"""\
version: 1
providers:
  router:
    type: openai_compat
    base_url: {ROUTER}
    api_key_env: ROUTER_KEY
    models:
      - id: provider/model
        tier: 1
        priority: 1          # tried before ollama
    budget:
      daily_requests: 5
  ollama:
    type: ollama
    base_url: {OLLAMA}
    models:
      - id: coder
        tier: 1
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
def home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Path:
    path = tmp_path / "orkestra-home"
    path.mkdir()
    (path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("ROUTER_KEY", FAKE_KEY)
    return path


def _enable(capsys: pytest.CaptureFixture[str], *names: str) -> None:
    for name in names:
        code, _, _ = _run(["--lang", "en", "providers", "enable", name, "--yes"], capsys)
        assert code == 0


def _ollama_ok(content: str = "local answer") -> httpx.Response:
    return httpx.Response(
        200,
        json={"message": {"content": content}, "done_reason": "stop",
              "prompt_eval_count": 5, "eval_count": 2},
    )  # fmt: skip


def _router_ok(content: str = "remote answer") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c", "object": "chat.completion", "created": 0, "model": "provider/model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12,
                      "cost": 0.001},
        },
    )  # fmt: skip


def _providers(capsys: pytest.CaptureFixture[str]) -> dict[str, dict[str, object]]:
    code, out, _ = _run(["providers", "list", "--json"], capsys)
    assert code == 0
    return {p["name"]: p for p in json.loads(out)["providers"]}


# --- consent ---------------------------------------------------------------------------


def test_enable_list_disable(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _providers(capsys)["router"]["consent"] == "missing"
    code, out, _ = _run(["--lang", "en", "providers", "enable", "router", "--yes"], capsys)
    assert code == 0
    assert "https://router.test/api/v1" in out
    assert "ROUTER_KEY" in out
    assert FAKE_KEY not in out
    rows = _providers(capsys)
    assert rows["router"]["consent"] == "granted"
    assert rows["router"]["api_key_present"] is True
    assert rows["ollama"]["consent"] == "missing"
    code, out, _ = _run(["--lang", "en", "providers", "disable", "router"], capsys)
    assert "withdrawn" in out
    assert _providers(capsys)["router"]["consent"] == "missing"


def test_enable_agent_shows_warning(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["--lang", "en", "providers", "enable", "codex", "--yes"], capsys)
    assert code == 0
    assert "can write files and run commands" in out


def test_enable_refuses_without_tty(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    code, _, err = _run(["--lang", "en", "providers", "enable", "router"], capsys)
    assert code == 2
    assert "interactive terminal" in err
    assert _providers(capsys)["router"]["consent"] == "missing"


@pytest.mark.parametrize(
    ("answer", "expected_code", "state"), [(True, 0, "granted"), (False, 4, "missing")]
)
def test_enable_interactive(
    answer: bool,
    expected_code: int,
    state: str,
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("sys.stdin", Tty(""))
    monkeypatch.setattr("typer.confirm", lambda *a, **k: answer)
    code, _, _ = _run(["providers", "enable", "router"], capsys)
    assert code == expected_code
    assert _providers(capsys)["router"]["consent"] == state


def test_enable_tty_that_hits_eof_is_not_interactive(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Windows reports NUL as a TTY; the prompt then reads EOF right away."""

    class NulLikeTty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("sys.stdin", NulLikeTty(""))
    code, _, err = _run(["--lang", "en", "providers", "enable", "router"], capsys)
    assert code == 2
    assert "interactive terminal" in err
    assert _providers(capsys)["router"]["consent"] == "missing"


def test_enable_unknown_provider(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, _ = _run(["providers", "enable", "nope", "--yes"], capsys)
    assert code == 2


@respx.mock
def test_ask_without_consent_exits_4(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["--lang", "en", "ask", "hi", "--json"], capsys)
    assert code == 4
    error = json.loads(out)["error"]
    assert error["type"] == "ConsentRequired"
    assert any("orkestra providers enable router" in d for d in error["details"])


@respx.mock
def test_changed_settings_need_consent_again(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _enable(capsys, "router", "ollama")
    config = home / "config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("router.test", "other.test"), encoding="utf-8"
    )
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama_ok())
    code, _out, _ = _run(["--lang", "en", "ask", "hi", "--provider", "router"], capsys)
    assert code == 4
    assert _providers(capsys)["router"]["consent"] == "changed"


# --- budget ----------------------------------------------------------------------------


@respx.mock
def test_budget_exhausted_moves_to_next_provider(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _enable(capsys, "router", "ollama")
    router = respx.post(f"{ROUTER}/chat/completions").mock(return_value=_router_ok())
    ollama = respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama_ok())
    for _ in range(5):  # daily_requests: 5
        code, out, _ = _run(["ask", "hi", "--json"], capsys)
        assert code == 0
        assert json.loads(out)["provider"] == "router"
    code, out, _ = _run(["ask", "hi", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["provider"] == "ollama"
    assert router.call_count == 5
    assert ollama.call_count == 1

    code, out, _ = _run(["budget", "--json"], capsys)
    data = {p["name"]: p for p in json.loads(out)["providers"]}
    assert data["router"]["used"]["requests"] == 5
    assert data["router"]["limits"] == [
        {"limit": "daily_requests", "value": 5, "used": 5, "remaining": 0}
    ]
    assert data["ollama"]["limits"] == []
    assert data["ollama"]["used"]["requests"] == 1

    code, _, err = _run(["--lang", "en", "ask", "hi", "--provider", "router"], capsys)
    assert code == 3
    assert "daily budget would be exceeded (daily_requests)" in err


@respx.mock
def test_fetched_price_stops_request_before_it_overspends(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No price_per_mtok in config: the OpenRouter price list is used for the estimate."""
    config = home / "config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("daily_requests: 5", "daily_usd: 0.01"),
        encoding="utf-8",
    )
    _enable(capsys, "router", "ollama")
    respx.get(f"{ROUTER}/models").mock(
        return_value=httpx.Response(
            200,  # 10 / 30 USD per 1M tokens; 4096 output tokens alone cost ~0.12 USD
            json={"data": [{"id": "provider/model",
                            "pricing": {"prompt": "0.00001", "completion": "0.00003"}}]},
        )
    )  # fmt: skip
    router = respx.post(f"{ROUTER}/chat/completions").mock(return_value=_router_ok())
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama_ok())
    code, out, _ = _run(["ask", "hi", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["provider"] == "ollama"
    assert router.call_count == 0  # never sent: the estimate was over the limit

    code, _, err = _run(["--lang", "en", "ask", "hi", "--provider", "router"], capsys)
    assert code == 3
    assert "daily budget would be exceeded (daily_usd)" in err


@respx.mock
def test_unknown_price_warns(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = home / "config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("daily_requests: 5", "daily_usd: 1.0"),
        encoding="utf-8",
    )
    _enable(capsys, "router")
    respx.get(f"{ROUTER}/models").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.post(f"{ROUTER}/chat/completions").mock(return_value=_router_ok())
    code, _, err = _run(["--lang", "en", "ask", "hi", "--provider", "router"], capsys)
    assert code == 0
    assert "no price known for router/provider/model" in err

    respx.get(f"{OLLAMA}/api/tags").mock(return_value=httpx.Response(200, json={"models": []}))
    _, out, _ = _run(["--lang", "en", "doctor"], capsys)
    # After one real request the cost per token is known from history.
    assert "estimated from past usage" in out


@respx.mock
def test_disabling_and_reenabling_keeps_consent(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _enable(capsys, "router")
    config = home / "config.yaml"
    original = config.read_text(encoding="utf-8")
    config.write_text(
        original.replace(
            "    api_key_env: ROUTER_KEY\n",
            "    api_key_env: ROUTER_KEY\n    enabled: false\n    timeout_s: 30\n",
        ),
        encoding="utf-8",
    )
    assert _providers(capsys)["router"]["consent"] == "granted"
    config.write_text(original, encoding="utf-8")
    assert _providers(capsys)["router"]["consent"] == "granted"


def test_budget_human(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["--lang", "en", "budget"], capsys)
    assert code == 0
    assert "router: daily_requests 0/5" in out
    assert "ollama: no limit" in out


# --- circuit breaker and offline failover ----------------------------------------------


@respx.mock
def test_offline_remote_is_paused_and_ollama_takes_over(
    home: Path, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    """No internet: every ask still answers (from Ollama, in the same command, without
    waiting); after 3 failed commands the remote API is paused and not even tried."""
    _enable(capsys, "router", "ollama")
    router = respx.post(f"{ROUTER}/chat/completions").mock(
        side_effect=httpx.ConnectError("network is unreachable")
    )
    ollama = respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama_ok())
    for _ in range(3):
        code, out, _ = _run(["ask", "hi", "--json"], capsys)
        assert code == 0
        env = json.loads(out)
        assert (env["provider"], env["status"], env["attempts"]) == ("ollama", "ok", 2)
        assert [(f["provider"], f["error"]) for f in env["failovers"]] == [
            ("router", "ProviderUnavailable")
        ]
    assert sleeps == []  # no backoff for "no connection at all"
    code, out, _err = _run(["ask", "hi", "--json"], capsys)
    assert code == 0
    env = json.loads(out)
    assert (env["provider"], env["failovers"]) == ("ollama", [])
    assert router.call_count == 3  # paused: not even tried the 4th time
    assert ollama.call_count == 4
    rows = _providers(capsys)
    assert rows["router"]["health"]["open_until"] is not None  # type: ignore[index]
    assert rows["router"]["health"]["consecutive_failures"] == 3  # type: ignore[index]


@respx.mock
def test_success_resets_failures(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _enable(capsys, "router")
    respx.post(f"{ROUTER}/chat/completions").mock(
        side_effect=[httpx.ConnectError("down"), httpx.ConnectError("down"), _router_ok()]
    )
    for _ in range(3):
        _run(["ask", "hi", "--provider", "router"], capsys)
    health = _providers(capsys)["router"]["health"]
    assert health == {"open_until": None, "consecutive_failures": 0, "last_error": None}


@respx.mock
def test_auth_error_pauses_provider(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _enable(capsys, "router", "ollama")
    respx.post(f"{ROUTER}/chat/completions").mock(return_value=httpx.Response(401, json={}))
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama_ok())
    code, out, _ = _run(["ask", "hi", "--json"], capsys)
    assert code == 0
    env = json.loads(out)
    assert env["provider"] == "ollama"
    assert env["failovers"][0]["error"] == "ProviderAuthError"
    code, out, _ = _run(["ask", "hi", "--json"], capsys)
    assert json.loads(out)["failovers"] == []  # paused for an hour: not tried again


# --- secrets ---------------------------------------------------------------------------


@respx.mock
def test_secret_context_stays_local(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _enable(capsys, "router", "ollama")
    router = respx.post(f"{ROUTER}/chat/completions").mock(return_value=_router_ok())
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama_ok())
    Path(".env").write_text("AWS_KEY=AKIAABCDEFGHIJKLMNOP\n", encoding="utf-8")
    code, out, err = _run(["--lang", "en", "ask", "explain", "--context", ".env", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["provider"] == "ollama"
    assert router.call_count == 0
    assert "Possible secret in .env, line 1 (aws_access_key)" in err

    code, _, err = _run(
        ["--lang", "en", "ask", "explain", "--context", ".env", "--provider", "router"], capsys
    )
    assert code == 3
    assert "remote, and the context contains secrets" in err

    code, out, _ = _run(
        [
            "ask",
            "explain",
            "--context",
            ".env",
            "--provider",
            "router",
            "--allow-secrets",
            "--json",
        ],
        capsys,
    )
    assert code == 0
    assert router.call_count == 1


# --- redaction in run records ----------------------------------------------------------


@respx.mock
def test_key_value_never_reaches_run_records(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _enable(capsys, "ollama")
    Path("notes.txt").write_text(f"the key is {FAKE_KEY}\n", encoding="utf-8")
    responses = iter([_ollama_ok(f"You pasted {FAKE_KEY}")])
    respx.post(f"{OLLAMA}/api/chat").mock(
        side_effect=lambda request: next(
            responses, httpx.Response(500, json={"error": f"crash while reading {FAKE_KEY}"})
        )
    )
    code, out, _ = _run(
        ["ask", "x", "--context", "notes.txt", "--provider", "ollama", "--json"], capsys
    )
    assert code == 0
    code, out2, err = _run(
        ["ask", "x", "--context", "notes.txt", "--provider", "ollama", "--json"], capsys
    )
    assert code == 3
    assert FAKE_KEY not in out + out2 + err
    files = [p for p in (home / "runs").rglob("*") if p.is_file()]
    assert any(p.name == "orkestra.log" for p in files)
    for path in files:
        assert FAKE_KEY not in path.read_text(encoding="utf-8"), path


# --- runs table ------------------------------------------------------------------------


@respx.mock
def test_run_is_recorded(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _enable(capsys, "ollama")
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama_ok())
    _, out, _ = _run(["ask", "hi", "--provider", "ollama", "--json"], capsys)
    env = json.loads(out)
    with closing(db.connect()) as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (env["run_id"],)).fetchone()
    assert (row["status"], row["provider"], row["kind"]) == ("ok", "ollama", "ask")
    assert row["worker_output_tokens"] == 2
    assert row["envelope_chars"] > 100
    assert row["finished_at"] is not None


@respx.mock
def test_doctor_shows_consent_and_pause(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _enable(capsys, "router")
    respx.post(f"{ROUTER}/chat/completions").mock(return_value=httpx.Response(401, json={}))
    _run(["ask", "hi", "--provider", "router"], capsys)
    respx.get(f"{ROUTER}/models").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(f"{OLLAMA}/api/tags").mock(return_value=httpx.Response(200, json={"models": []}))
    _, out, _ = _run(["--lang", "en", "doctor"], capsys)
    assert "[WARN] provider:ollama: no consent yet" in out
    assert "orkestra providers enable ollama" in out
    assert "[WARN] provider:router: paused until" in out
