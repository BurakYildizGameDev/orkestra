"""Router and retry through the real CLI (respx for HTTP, no real waiting)."""

from __future__ import annotations

import json
import re
from contextlib import closing
from pathlib import Path

import httpx
import pytest
import respx

from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.state import consent, db

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
OLLAMA = "http://ollama.test:11434"
ROUTER = "https://router.test/api/v1"
BACKUP = "https://backup.test/v1"

CONFIG = f"""\
version: 1
providers:
  router:
    type: openai_compat
    base_url: {ROUTER}
    api_key_env: ROUTER_KEY
    models:
      - id: fast/model
        tier: 1
        priority: 2
        context_window: 4096
      - id: wide/model
        tier: 1
        priority: 1
        context_window: 200000
      - id: smart/model
        tier: 2
  backup:
    type: openai_compat
    base_url: {BACKUP}
    models:
      - id: backup/model
        tier: 1
  ollama:
    type: ollama
    base_url: {OLLAMA}
    models:
      - id: coder
        tier: 1
        priority: -1          # last resort within tier 1
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
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "orkestra-home"
    path.mkdir()
    (path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("ROUTER_KEY", "sk-or-v1-ROUTERTESTKEY00000000000000000")
    config = load_config(cwd=work, environ={}).config
    with closing(db.connect()) as conn:
        for name, provider in config.providers.items():
            consent.grant(conn, name, provider, db.local_now())
    return path


def _chat(content: str = "answer", model: str = "m") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        },
    )  # fmt: skip


def _ollama(content: str = "local answer") -> httpx.Response:
    return httpx.Response(
        200, json={"message": {"content": content}, "prompt_eval_count": 1, "eval_count": 1}
    )


def _model_of(request: httpx.Request) -> str:
    return json.loads(request.content)["model"]


# --- dry run ---------------------------------------------------------------------------


def test_dry_run_lists_order_and_reasons(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["--lang", "en", "ask", "hi", "--dry-run"], capsys)
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith("Profile balanced (tiers 1-3)")
    order = [line.split()[1] for line in lines if re.match(r"\s+\d+\. ", line)]
    assert order == [
        "router/fast/model", "router/wide/model", "backup/backup/model", "ollama/coder",
        "router/smart/model",
    ]  # fmt: skip
    assert "codex: code agents cannot answer 'ask' yet" in out


def test_dry_run_json_sends_nothing(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with respx.mock(assert_all_called=False) as mock:
        chat = mock.post(f"{ROUTER}/chat/completions").mock(return_value=_chat())
        code, out, _ = _run(["ask", "hi", "--dry-run", "--json", "--profile", "cheap"], capsys)
    assert code == 0
    assert chat.call_count == 0
    plan = json.loads(out)
    assert plan["profile"] == "cheap"
    assert plan["tier_range"] == [1, 1]
    assert "router/smart/model" not in [f"{c['provider']}/{c['model']}" for c in plan["candidates"]]
    tier = [e for e in plan["eliminated"] if e["code"] == "tier_out_of_range"]
    assert tier and tier[0]["reason"].endswith("(profile cheap)")
    assert not (home / "runs").exists()  # no run directory for a dry run


def test_dry_run_without_candidates_exits_3(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["--lang", "en", "ask", "hi", "--dry-run", "--provider", "codex"], capsys)
    assert code == 3
    assert "No candidates." in out


def test_unknown_profile(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _run(["--lang", "en", "ask", "hi", "--profile", "turbo"], capsys)
    assert code == 2
    assert "Unknown profile 'turbo'" in err


def test_local_only(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["ask", "hi", "--local-only", "--dry-run", "--json"], capsys)
    assert code == 0
    assert [c["provider"] for c in json.loads(out)["candidates"]] == ["ollama"]


# --- retries ---------------------------------------------------------------------------


@respx.mock
def test_transient_error_is_retried_on_the_same_candidate(
    home: Path, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    route = respx.post(f"{ROUTER}/chat/completions").mock(
        side_effect=[httpx.Response(503, json={"error": {"message": "busy"}}), _chat("second try")]
    )
    code, out, _ = _run(["ask", "hi", "--json"], capsys)
    assert code == 0
    env = json.loads(out)
    assert (env["provider"], env["model"], env["attempts"]) == ("router", "fast/model", 2)
    assert env["failovers"] == []
    assert route.call_count == 2
    assert len(sleeps) == 1 and 1.0 <= sleeps[0] <= 1.25


@respx.mock
def test_429_waits_retry_after(
    home: Path, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    respx.post(f"{ROUTER}/chat/completions").mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "7"}, json={"error": {}}),
            _chat(),
        ]
    )
    code, _, _ = _run(["ask", "hi"], capsys)
    assert code == 0
    assert sleeps == [7.0]


@respx.mock
def test_failing_api_falls_over_to_next_provider(
    home: Path, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    """500s on the router: retried, the circuit opens after 3, the next provider answers."""
    router = respx.post(f"{ROUTER}/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": {"message": "down"}})
    )
    backup = respx.post(f"{BACKUP}/chat/completions").mock(return_value=_chat("from backup"))
    code, out, _err = _run(["--lang", "en", "ask", "hi", "--json"], capsys)
    assert code == 0
    env = json.loads(out)
    assert env["provider"] == "backup"
    assert router.call_count == 3  # third failure opens the circuit: no 4th retry
    assert len(sleeps) == 2
    assert [(f["provider"], f["model"], f["error"], f["attempts"]) for f in env["failovers"]] == [
        ("router", "fast/model", "ProviderTransient", 3),
    ]
    # the other router model was not tried: the provider is paused now
    assert all(_model_of(call.request) == "fast/model" for call in router.calls)
    assert backup.call_count == 1
    assert env["attempts"] == 4


@respx.mock
def test_whole_chain_down_lists_every_failover(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.post(f"{ROUTER}/chat/completions").mock(side_effect=httpx.ConnectError("offline"))
    respx.post(f"{BACKUP}/chat/completions").mock(side_effect=httpx.ConnectError("offline"))
    respx.post(f"{OLLAMA}/api/chat").mock(side_effect=httpx.ConnectError("not running"))
    code, out, err = _run(["--lang", "en", "ask", "hi", "--json"], capsys)
    assert code == 3
    env = json.loads(out)
    assert env["status"] == "error"
    assert env["error"].startswith("All 3 candidate(s) failed")
    assert [f["provider"] for f in env["failovers"]] == ["router", "backup", "ollama"]
    assert all(f["error"] == "ProviderConnectionError" for f in env["failovers"])
    assert all(f["attempts"] == 2 for f in env["failovers"])  # one quick retry each

    code, _, err = _run(["--lang", "en", "ask", "hi"], capsys)
    assert "skipped router/fast/model" in err
    assert "skipped ollama/coder" in err


@respx.mock
def test_context_too_long_moves_to_a_bigger_window(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def router(request: httpx.Request) -> httpx.Response:
        if _model_of(request) == "fast/model":
            return httpx.Response(
                400, json={"error": {"message": "maximum context length is 4096 tokens"}}
            )
        return _chat("wide answer")

    route = respx.post(f"{ROUTER}/chat/completions").mock(side_effect=router)
    code, out, _ = _run(["ask", "hi", "--json"], capsys)
    assert code == 0
    env = json.loads(out)
    assert (env["provider"], env["model"]) == ("router", "wide/model")
    assert env["failovers"][0]["error"] == "ContextTooLong"
    assert [_model_of(c.request) for c in route.calls] == ["fast/model", "wide/model"]


@respx.mock
def test_escalation_to_higher_tier_is_recorded(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def router(request: httpx.Request) -> httpx.Response:
        if _model_of(request) == "smart/model":
            return _chat("tier 2 answer")
        return httpx.Response(200, json={"id": "c", "object": "chat.completion", "created": 0,
                                         "model": "x", "choices": []})  # fmt: skip

    respx.post(f"{ROUTER}/chat/completions").mock(side_effect=router)
    respx.post(f"{BACKUP}/chat/completions").mock(
        return_value=httpx.Response(200, json={"id": "c", "object": "chat.completion",
                                               "created": 0, "model": "x", "choices": []})
    )  # fmt: skip
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=httpx.Response(200, json={"message": {}}))
    code, out, _ = _run(["ask", "hi", "--json"], capsys)
    assert code == 0
    env = json.loads(out)
    assert (env["model"], env["tier"]) == ("smart/model", 2)
    assert [f["error"] for f in env["failovers"]] == ["ProviderBadOutput"] * 4
    assert [(e["provider"], e["model"], e["tier"]) for e in env["escalations"]] == [
        ("ollama", "coder", 1)
    ]


@respx.mock
def test_attempt_records_per_try(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    respx.post(f"{ROUTER}/chat/completions").mock(
        side_effect=[httpx.Response(502, json={"error": {}}), _chat()]
    )
    _, out, _ = _run(["ask", "hi", "--json"], capsys)
    run_dir = home / "runs" / json.loads(out)["run_id"]
    assert (run_dir / "attempts" / "1" / "request.json").is_file()
    assert (run_dir / "attempts" / "2" / "response.txt").is_file()
    assert not (run_dir / "attempts" / "1" / "response.txt").exists()
    log = (run_dir / "orkestra.log").read_text(encoding="utf-8")
    assert "retrying router/fast/model" in log
