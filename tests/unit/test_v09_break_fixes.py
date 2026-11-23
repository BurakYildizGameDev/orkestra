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


# --- B-09: "needs consent" only when consent is what blocks -----------------------------


def test_consent_heading_only_when_consent_is_the_only_obstacle() -> None:
    from orkestra.errors import ConsentRequired, NoProviderAvailable
    from orkestra.routing.router import Elimination, Route

    def _route(*elims: Elimination) -> Route:
        return Route("balanced", (1, 3), 10, (), elims)

    secrets = Elimination("fake", None, "secrets_remote", "fake: secrets", False)
    no_consent = Elimination("off", None, "consent_none", "off: no consent", True)
    disabled = Elimination("old", None, "disabled", "old: disabled", False)
    assert isinstance(_route(secrets, no_consent).error(), NoProviderAvailable)
    assert isinstance(_route(no_consent, disabled).error(), ConsentRequired)
    assert isinstance(_route(no_consent).error(), ConsentRequired)


# --- B-13: an API key over plain http to another machine --------------------------------


@pytest.mark.parametrize(
    ("url", "key", "plain"),
    [
        ("http://api.example.test/v1", "KEY", True),
        ("https://api.example.test/v1", "KEY", False),
        ("http://127.0.0.1:1234/v1", "KEY", False),
        ("http://192.168.1.5:8000/v1", "KEY", False),
        ("http://api.example.test/v1", None, False),
    ],
)
def test_plain_http_key_is_detected(url: str, key: str | None, plain: bool) -> None:
    from orkestra.config.schema import plain_http_key

    data: dict[str, object] = {
        "type": "openai_compat", "base_url": url, "models": [{"id": "m", "tier": 1}],
    }  # fmt: skip
    if key:
        data["api_key_env"] = key
    assert plain_http_key(OpenAICompatProvider.model_validate(data)) is plain


def test_consent_warns_about_a_key_over_plain_http() -> None:
    from orkestra.state import consent

    cfg = OpenAICompatProvider.model_validate(
        {"type": "openai_compat", "base_url": "http://api.example.test/v1",
         "api_key_env": "KEY", "models": [{"id": "m", "tier": 1}]}
    )  # fmt: skip
    assert "https" in "\n".join(consent.describe("plain", cfg))


# --- B-18: a plan outside the repository is a usage error -------------------------------


def test_delegate_plan_outside_the_repository_is_a_usage_error(tmp_path: Path) -> None:
    import subprocess

    from orkestra.config.schema import Config
    from orkestra.errors import UsageError
    from orkestra.tasks import delegate

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    plan = tmp_path / "plan.md"
    plan.write_text("# plan\n", encoding="utf-8")
    config = Config.model_validate(
        {"version": 1, "providers": {"codex": {"type": "cli_agent", "command": "codex"}}}
    )
    with pytest.raises(UsageError) as exc_info:
        delegate.delegate_task(Path("../plan.md"), ["python -V"], config, cwd=repo, dry_run=True)
    assert "plan.md" in exc_info.value.message


# --- B-19 / B-20: a folder where a file belongs, and the other way round ----------------


def test_orkestra_home_that_is_a_file_is_a_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orkestra import paths
    from orkestra.errors import UsageError

    home = tmp_path / "home.txt"
    home.write_text("x", encoding="utf-8")
    monkeypatch.setenv("ORKESTRA_HOME", str(home))
    with pytest.raises(UsageError) as exc_info:
        paths.orkestra_home()
    assert "ORKESTRA_HOME" in exc_info.value.message


def test_config_flag_pointing_to_a_folder_says_so(tmp_path: Path) -> None:
    from orkestra.config import loader
    from orkestra.errors import ConfigError

    with pytest.raises(ConfigError) as exc_info:
        loader.find_sources(config_flag=tmp_path, cwd=tmp_path)
    assert "folder" in exc_info.value.message


# --- B-24: a version probe that never answers does not hang doctor ----------------------


def test_version_probe_gives_up_on_a_hung_program(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import sys
    import time

    from orkestra import doctor

    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":  # npm installs agents as .cmd shims: cmd.exe -> node
        program = tmp_path / "agent.cmd"
        program.write_text(f'@"{sys.executable}" "{sleeper}" %*\r\n', encoding="utf-8")
    else:
        program = tmp_path / "agent"
        program.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{sleeper}" "$@"\n', encoding="utf-8"
        )
        os.chmod(program, 0o755)
    monkeypatch.setattr(doctor, "VERSION_TIMEOUT_S", 1)
    start = time.monotonic()
    assert doctor.probe_version(str(program)) is None
    assert time.monotonic() - start < 20
