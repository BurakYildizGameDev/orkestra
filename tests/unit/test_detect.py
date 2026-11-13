"""Setup detection: Ollama, code agents and API key variables (Faz 11a, Mimari §22)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import httpx
import pytest

from orkestra.tui import detect


class KeysOnly(Mapping[str, str]):
    """An environment whose values must never be read: only names may be looked at."""

    def __init__(self, names: set[str]) -> None:
        self._names = names

    def __contains__(self, key: object) -> bool:
        return key in self._names

    def __getitem__(self, key: str) -> str:
        raise AssertionError(f"the value of {key} was read")

    def get(self, key: str, default: Any = None) -> Any:
        raise AssertionError(f"the value of {key} was read")

    def __iter__(self) -> Iterator[str]:
        return iter(self._names)

    def __len__(self) -> int:
        return len(self._names)


def _tags(names: list[str]) -> detect.TagsFetcher:
    def fetch(url: str, timeout_s: float) -> object:
        return {"models": [{"name": name} for name in names]}

    return fetch


def _no_agents(command: str) -> str | None:
    return None


def test_a_running_ollama_and_its_models_are_found() -> None:
    tags = _tags(["qwen2.5-coder:14b", "llama3:8b"])
    found = detect.detect(environ=KeysOnly(set()), fetch_tags=tags, which=_no_agents)
    assert found.ollama.reachable is True
    assert found.ollama.models == ("qwen2.5-coder:14b", "llama3:8b")
    assert found.ollama.url == detect.OLLAMA_URL


def test_ollama_is_asked_with_a_two_second_timeout() -> None:
    seen: list[tuple[str, float]] = []

    def fetch(url: str, timeout_s: float) -> object:
        seen.append((url, timeout_s))
        return {"models": []}

    detect.detect(environ=KeysOnly(set()), fetch_tags=fetch, which=_no_agents)
    assert seen == [(f"{detect.OLLAMA_URL}/api/tags", 2.0)]


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), ValueError("not json")],
)
def test_an_unreachable_or_broken_ollama_is_reported_not_raised(error: Exception) -> None:
    def fetch(url: str, timeout_s: float) -> object:
        raise error

    found = detect.detect(environ=KeysOnly(set()), fetch_tags=fetch, which=_no_agents)
    assert found.ollama.reachable is False
    assert found.ollama.models == ()


@pytest.mark.parametrize("payload", [{"models": "x"}, ["list"], {"models": [{"id": 1}]}, None])
def test_an_ollama_answer_of_the_wrong_shape_means_no_models(payload: object) -> None:
    def fetch(url: str, timeout_s: float) -> object:
        return payload

    found = detect.detect(environ=KeysOnly(set()), fetch_tags=fetch, which=_no_agents)
    assert found.ollama.models == ()


def test_code_agents_and_their_versions_are_found() -> None:
    paths = {"codex": "/bin/codex", "claude": "/bin/claude"}
    versions = {"/bin/codex": "codex-cli 0.160.0", "/bin/claude": None}
    found = detect.detect(environ=KeysOnly(set()), fetch_tags=_tags([]), which=paths.get,
                          probe=versions.get)  # fmt: skip
    by_name = {agent.name: agent for agent in found.agents}
    assert list(by_name) == ["codex", "agy", "claude"]
    assert by_name["codex"].path == "/bin/codex"
    assert by_name["codex"].version == "codex-cli 0.160.0"
    assert by_name["claude"].path == "/bin/claude"
    assert by_name["claude"].version is None
    assert by_name["agy"].path is None
    assert by_name["agy"].found is False


def test_api_keys_are_only_checked_by_name_and_never_read() -> None:
    found = detect.detect(environ=KeysOnly({"OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"}),
                          fetch_tags=_tags([]), which=_no_agents)  # fmt: skip
    present = {key.api.env for key in found.keys if key.present}
    assert present == {"OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"}
    assert {key.api.env for key in found.keys} == {api.env for api in detect.KNOWN_APIS}


def test_the_detection_summary_shows_no_key_value() -> None:
    secret = "sk-or-v1-TESTKEYVALUE0123456789"
    environ = {"OPENROUTER_API_KEY": secret}
    found = detect.detect(environ=environ, fetch_tags=_tags([]), which=_no_agents)
    text = "\n".join(detect.summary_lines(found))
    assert secret not in text
    assert "OPENROUTER_API_KEY" in text


def test_every_known_api_has_a_unique_name_and_an_https_url() -> None:
    names = [api.name for api in detect.KNOWN_APIS]
    assert len(names) == len(set(names))
    assert all(api.base_url.startswith("https://") for api in detect.KNOWN_APIS)
    assert all(api.env.endswith("_API_KEY") for api in detect.KNOWN_APIS)
