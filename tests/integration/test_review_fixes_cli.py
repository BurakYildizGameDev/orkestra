"""Budget, routing and run-record fixes from the Faz 2-4 code reviews (PR #3, #4, #5).

Real CLI, respx for HTTP, no real waiting (``conftest.sleeps``).
"""

from __future__ import annotations

import json
import re
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from orkestra.cli import app
from orkestra.state import db, health

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
OLLAMA = "http://ollama.test:11434"
ROUTER = "https://router.test/api/v1"
FAKE_KEY = "sk-or-v1-FAKEKEYFORREVIEWFIXES0000000000"

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
      - id: second/model
        tier: 1
      - id: smart/model
        tier: 2
    budget: {{}}
  ollama:
    type: ollama
    base_url: {OLLAMA}
    models:
      - id: coder
        tier: 1
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
    monkeypatch.setenv("ROUTER_KEY", FAKE_KEY)
    return path


def _budget(home: Path, budget: str) -> None:
    config = home / "config.yaml"
    text = config.read_text(encoding="utf-8").replace("budget: {}", f"budget: {{{budget}}}")
    config.write_text(text, encoding="utf-8")


def _enable(capsys: pytest.CaptureFixture[str], *names: str) -> None:
    for name in names:
        code, _, _ = _run(["--lang", "en", "providers", "enable", name, "--yes"], capsys)
        assert code == 0


def _chat(content: str = "remote answer", usage: dict[str, Any] | None = None) -> httpx.Response:
    body: dict[str, Any] = {
        "id": "c", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
    }  # fmt: skip
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


USAGE = {"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12}


def _ollama(content: str = "local answer") -> httpx.Response:
    return httpx.Response(
        200,
        json={"message": {"content": content}, "done_reason": "stop",
              "prompt_eval_count": 5, "eval_count": 2},
    )  # fmt: skip


def _model_of(request: httpx.Request) -> str:
    return json.loads(request.content)["model"]


def _used(capsys: pytest.CaptureFixture[str], name: str = "router") -> dict[str, Any]:
    code, out, _ = _run(["budget", "--json"], capsys)
    assert code == 0
    return {p["name"]: p["used"] for p in json.loads(out)["providers"]}[name]


def _price_list(model: str = "provider/model") -> httpx.Response:
    return httpx.Response(  # 10 / 30 USD per 1M tokens
        200,
        json={"data": [{"id": model, "pricing": {"prompt": "0.00001", "completion": "0.00003"}}]},
    )


# --- Faz 2 -----------------------------------------------------------------------------


@respx.mock
def test_cannot_do_escalates_to_a_higher_tier(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _enable(capsys, "router", "ollama")

    def router(request: httpx.Request) -> httpx.Response:
        if _model_of(request) == "provider/model":
            return _chat("CANNOT_DO: the task is ambiguous", USAGE)
        return _chat("tier 2 answer", USAGE)

    route = respx.post(f"{ROUTER}/chat/completions").mock(side_effect=router)
    ollama = respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama())
    code, out, _ = _run(["ask", "hi", "--json"], capsys)
    assert code == 0
    env = json.loads(out)
    assert (env["model"], env["tier"], env["status"]) == ("smart/model", 2, "ok")
    assert [_model_of(c.request) for c in route.calls] == ["provider/model", "smart/model"]
    assert not ollama.called  # same tier: not asked again
    assert env["failovers"][0]["error"] == "CannotDo"
    assert "ambiguous" in env["failovers"][0]["reason"]
    assert [e["model"] for e in env["escalations"]] == ["provider/model"]


@respx.mock
def test_cannot_do_without_a_higher_tier_is_escalate(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _enable(capsys, "router", "ollama")
    respx.post(f"{ROUTER}/chat/completions").mock(
        return_value=_chat("CANNOT_DO: needs more context", USAGE)
    )
    code, out, _ = _run(["ask", "hi", "--json", "--profile", "cheap"], capsys)
    assert code == 1
    env = json.loads(out)
    assert env["status"] == "escalate"
    assert "needs more context" in env["summary"]


# --- Faz 3 -----------------------------------------------------------------------------


@respx.mock
def test_cost_from_price_list_is_recorded(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _budget(home, "daily_usd: 1.0")
    _enable(capsys, "router")
    respx.get(f"{ROUTER}/models").mock(return_value=_price_list())
    respx.post(f"{ROUTER}/chat/completions").mock(return_value=_chat(usage=USAGE))  # no cost
    code, out, _ = _run(["ask", "hi", "--provider", "router", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["usage"]["cost_usd"] == pytest.approx(0.00018)
    assert _used(capsys)["cost_usd"] == pytest.approx(0.00018)


@respx.mock
def test_missing_usage_counts_the_estimate(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _budget(home, "daily_tokens: 100000")
    _enable(capsys, "router")
    respx.post(f"{ROUTER}/chat/completions").mock(return_value=_chat(usage=None))
    code, _, _ = _run(["ask", "hi", "--provider", "router"], capsys)
    assert code == 0
    assert _used(capsys)["tokens"] > 0


@respx.mock
def test_price_list_is_not_fetched_for_providers_without_consent(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _budget(home, "daily_usd: 1.0")
    _enable(capsys, "ollama")  # router has no consent: its key must not be sent anywhere
    prices = respx.get(f"{ROUTER}/models").mock(return_value=_price_list())
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama())
    code, _, _ = _run(["ask", "hi"], capsys)
    assert code == 0
    assert not prices.called


@respx.mock
def test_dry_run_never_fetches_prices(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _budget(home, "daily_usd: 1.0")
    _enable(capsys, "router", "ollama")
    prices = respx.get(f"{ROUTER}/models").mock(return_value=_price_list())
    code, _, _ = _run(["ask", "hi", "--dry-run"], capsys)
    assert code == 0
    assert not prices.called


@respx.mock
def test_enable_closes_an_auth_circuit(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _enable(capsys, "router", "ollama")
    router = respx.post(f"{ROUTER}/chat/completions").mock(
        side_effect=[httpx.Response(401, json={}), _chat(usage=USAGE)]
    )
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama())
    _run(["ask", "hi"], capsys)  # 401: paused for an hour
    _enable(capsys, "router")  # the user fixed the key and enables the provider again
    code, out, _ = _run(["ask", "hi", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["provider"] == "router"
    assert router.call_count == 2


@respx.mock
def test_secret_in_the_prompt_stays_local(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _enable(capsys, "router", "ollama")
    router = respx.post(f"{ROUTER}/chat/completions").mock(return_value=_chat(usage=USAGE))
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama())
    code, out, err = _run(
        ["--lang", "en", "ask", "why: AWS_KEY=AKIAABCDEFGHIJKLMNOP", "--json"], capsys
    )
    assert code == 0
    assert json.loads(out)["provider"] == "ollama"
    assert router.call_count == 0
    assert "aws_access_key" in err


@respx.mock
def test_schema_check_sees_the_real_answer(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _enable(capsys, "ollama")
    Path("s.json").write_text(
        '{"type": "object", "required": ["dsn"], "properties": {"dsn": {"type": "string"}}}',
        encoding="utf-8",
    )
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=_ollama('{"dsn": "password=x"}'))
    code, out, _ = _run(["ask", "dsn?", "--provider", "ollama", "--schema", "s.json"], capsys)
    assert code == 0
    assert '{"dsn": "password=x"}' in out


@respx.mock
def test_crash_mid_run_still_closes_the_run(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _enable(capsys, "ollama")
    respx.post(f"{OLLAMA}/api/chat").mock(side_effect=RuntimeError("adapter bug"))
    code, _, _ = _run(["ask", "hi", "--provider", "ollama"], capsys)
    assert code == 10
    with closing(db.connect()) as conn:
        row = conn.execute("SELECT status, finished_at, run_id FROM runs").fetchone()
        reserved = conn.execute("SELECT COUNT(*) FROM usage WHERE kind = 'reservation'")
        assert reserved.fetchone()[0] == 0
    assert row["status"] == "error" and row["finished_at"] is not None
    envelope = json.loads((home / "runs" / row["run_id"] / "envelope.json").read_text("utf-8"))
    assert envelope["status"] == "error"
    assert "adapter bug" in envelope["error"]


# --- Faz 4 -----------------------------------------------------------------------------


@respx.mock
def test_retries_count_as_one_run(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _budget(home, "daily_runs: 2")
    _enable(capsys, "router")
    respx.post(f"{ROUTER}/chat/completions").mock(
        side_effect=[httpx.Response(503, json={"error": {}}),
                     httpx.Response(503, json={"error": {}}), _chat(usage=USAGE)]
    )  # fmt: skip
    code, _, _ = _run(["ask", "hi", "--provider", "router"], capsys)
    assert code == 0
    used = _used(capsys)
    assert (used["runs"], used["requests"]) == (1, 3)


@respx.mock
def test_timeout_counts_the_reserved_estimate(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _budget(home, "daily_tokens: 100000")
    _enable(capsys, "router")
    respx.post(f"{ROUTER}/chat/completions").mock(side_effect=httpx.ReadTimeout("slow"))
    code, _, _ = _run(["ask", "hi", "--provider", "router", "--model", "provider/model"], capsys)
    assert code == 3
    used = _used(capsys)
    assert used["requests"] == 3  # the third timeout opens the circuit
    assert used["tokens"] >= 3 * 4096  # the provider may have billed every timed-out request


@respx.mock
def test_missing_model_tries_the_next_model_and_keeps_the_circuit_closed(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _enable(capsys, "router", "ollama")

    def router(request: httpx.Request) -> httpx.Response:
        if _model_of(request) == "provider/model":
            return httpx.Response(404, json={"error": {"message": "no such model"}})
        return _chat("second model answer", USAGE)

    respx.post(f"{ROUTER}/chat/completions").mock(side_effect=router)
    code, out, _ = _run(["ask", "hi", "--json"], capsys)
    assert code == 0
    env = json.loads(out)
    assert (env["provider"], env["model"]) == ("router", "second/model")
    assert env["failovers"][0]["error"] == "ProviderModelNotFound"
    with closing(db.connect()) as conn:
        assert health.get(conn, "router").consecutive_failures == 0


@respx.mock
def test_unlisted_explicit_model_is_priced(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _budget(home, "daily_usd: 0.01")
    _enable(capsys, "router")
    respx.get(f"{ROUTER}/models").mock(return_value=_price_list("other/model"))
    chat = respx.post(f"{ROUTER}/chat/completions").mock(return_value=_chat(usage=USAGE))
    code, _, err = _run(
        ["--lang", "en", "ask", "hi", "--provider", "router", "--model", "other/model"], capsys
    )
    assert code == 3  # 4096 output tokens at 30 USD/M ≈ 0.12 USD > 0.01
    assert "daily_usd" in err
    assert "no price known" not in err
    assert not chat.called


@respx.mock
def test_budget_race_does_not_count_an_attempt(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from orkestra.errors import BudgetExhausted
    from orkestra.state import budget

    _enable(capsys, "router", "ollama")
    real = budget.reserve
    calls = {"n": 0}

    def racy(*args: Any, **kwargs: Any) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise BudgetExhausted("another process took the budget")
        return real(*args, **kwargs)

    monkeypatch.setattr(budget, "reserve", racy)
    respx.post(f"{ROUTER}/chat/completions").mock(return_value=_chat(usage=USAGE))
    code, out, _ = _run(["ask", "hi", "--json"], capsys)
    assert code == 0
    env = json.loads(out)
    assert env["attempts"] == 1
    assert env["failovers"][0]["attempts"] == 0
    run_dir = home / "runs" / env["run_id"]
    assert sorted(p.name for p in (run_dir / "attempts").iterdir()) == ["1"]
