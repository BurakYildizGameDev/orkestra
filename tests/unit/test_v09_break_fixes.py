"""Problems found by the v0.9 break test (2026-11-23, D-139)."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
import respx

from orkestra import i18n
from orkestra.config.schema import OpenAICompatProvider
from orkestra.errors import ProviderBadOutput, ProviderTimeout, ProviderTransient
from orkestra.providers.base import CompletionRequest
from orkestra.providers.openai_compat import OpenAICompatChat
from orkestra.routing.retry import Action, classify, give_up
from orkestra.tasks import edit_format as ef

SRC = Path(__file__).resolve().parents[2] / "src" / "orkestra"
BASE = "https://router.test/api/v1"
URL = f"{BASE}/chat/completions"


def _chat() -> OpenAICompatChat:
    cfg = OpenAICompatProvider.model_validate(
        {
            "type": "openai_compat",
            "base_url": BASE,
            "api_key_env": "ROUTER_KEY",
            "models": [{"id": "provider/model", "tier": 2}],
        }
    )
    return OpenAICompatChat("router", cfg, {"ROUTER_KEY": "sk-test-FAKE0000000000000000"})


def _req() -> CompletionRequest:
    return CompletionRequest(model="provider/model", system="s", user="u", max_output_tokens=16)


# --- B-04: an HTML page instead of an API answer ---------------------------------------


@respx.mock
async def test_html_answer_is_bad_output_naming_the_base_url() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            200, text="<html>login</html>", headers={"content-type": "text/html"}
        )
    )
    with pytest.raises(ProviderBadOutput) as exc_info:
        await _chat().complete(_req())
    assert "base_url" in exc_info.value.message
    assert "AttributeError" not in exc_info.value.message


@respx.mock
async def test_json_that_is_not_a_chat_completion_is_bad_output() -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(ProviderBadOutput):
        await _chat().complete(_req())


# --- B-05: a hung provider is not waited for again and again ----------------------------


def test_timeout_moves_on_instead_of_retrying_the_same_candidate() -> None:
    assert classify(ProviderTimeout("slow")) is Action.NEXT
    assert classify(ProviderTransient("5xx")) is Action.RETRY  # unchanged
    assert give_up(ProviderTimeout("slow")) is Action.NEXT


# --- B-07 / B-08: paths Windows cannot hold --------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "src/CON",
        "src/nul.txt",
        "src/aux",
        "Lpt1.py",
        "com9.log",
        "src/calc.py:stream",
        "src/trailing.",
        "src/trailing ",
        'src/a"b.py',
        "src/a|b.py",
        "src/a?b.py",
        "src/a*b.py",
        "src/a\tb.py",
    ],
)
def test_paths_windows_cannot_hold_are_rejected(raw: str) -> None:
    assert ef.normalize_path(raw) is None


@pytest.mark.parametrize("raw", ["src/console.py", "src/con_utils.py", "src/nullable.py"])
def test_names_that_only_start_like_a_device_are_fine(raw: str) -> None:
    assert ef.normalize_path(raw) == raw


# --- B-02: every translation key the code uses exists -----------------------------------

_T_CALL = re.compile(r"""\bt\(\s*["']([a-z0-9_]+(?:\.[a-z0-9_]+)+)["']""")


def test_every_literal_translation_key_is_in_the_catalog() -> None:
    known = set(i18n.load_catalog("en"))
    missing = sorted(
        f"{path.relative_to(SRC)}: {key}"
        for path in SRC.rglob("*.py")
        for key in _T_CALL.findall(path.read_text(encoding="utf-8"))
        if key not in known
    )
    assert not missing, missing


# --- B-03: an empty budget says what to do ----------------------------------------------


def test_budget_without_providers_points_to_init(capsys: pytest.CaptureFixture[str]) -> None:
    from orkestra.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(["--lang", "en", "budget"])
    assert exc_info.value.code in (0, None)
    assert "orkestra init" in capsys.readouterr().out


# --- B-06: a server on this computer is not silently "remote" ---------------------------


@pytest.mark.parametrize(
    ("url", "hint"),
    [
        ("http://127.0.0.1:1234/v1", True),
        ("http://localhost:8000/v1", True),
        ("http://[::1]:8000/v1", True),
        ("https://openrouter.ai/api/v1", False),
    ],
)
def test_remote_description_hints_local_for_a_loopback_url(url: str, hint: bool) -> None:
    from orkestra.state import consent

    cfg = OpenAICompatProvider.model_validate(
        {"type": "openai_compat", "base_url": url, "models": [{"id": "m", "tier": 1}]}
    )
    text = "\n".join(consent.describe("lm", cfg))
    assert ("local: true" in text) is hint
