"""What is installed on this machine, for the setup wizard (Mimari §22).

- Ollama: ``GET /api/tags`` with a 2 second timeout, so a stopped Ollama never hangs the
  wizard; any network or format problem means "not reachable", never an exception.
- Code agents: ``codex``, ``agy`` and ``claude`` with ``shutil.which`` and ``--version``.
- API keys: only whether the environment variable **exists**. The value is never read, so it
  cannot leak into the wizard's output, a log or the config file.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from orkestra.doctor import probe_version
from orkestra.i18n import t

OLLAMA_URL = "http://localhost:11434"
OLLAMA_TIMEOUT_S = 2.0
AGENTS = ("codex", "agy", "claude")

TagsFetcher = Callable[[str, float], object]
Which = Callable[[str], str | None]
Probe = Callable[[str], str | None]


@dataclass(frozen=True)
class KnownApi:
    name: str  # the provider name the wizard writes
    env: str  # the environment variable that holds the key
    base_url: str


# OpenAI-compatible endpoints the wizard can set up from a key variable alone.
KNOWN_APIS = (
    KnownApi("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
    KnownApi("openai", "OPENAI_API_KEY", "https://api.openai.com/v1"),
    KnownApi("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/v1"),
    KnownApi("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    KnownApi("mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
    KnownApi("gemini", "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai"),
)


@dataclass(frozen=True)
class OllamaFound:
    url: str
    reachable: bool
    models: tuple[str, ...]  # chat models only
    skipped: tuple[str, ...] = ()  # embedding models: they cannot answer a task


@dataclass(frozen=True)
class AgentFound:
    name: str
    path: str | None
    version: str | None

    @property
    def found(self) -> bool:
        return self.path is not None


@dataclass(frozen=True)
class KeyFound:
    api: KnownApi
    present: bool


@dataclass(frozen=True)
class Detection:
    ollama: OllamaFound
    agents: tuple[AgentFound, ...]
    keys: tuple[KeyFound, ...]

    def agent(self, name: str) -> AgentFound | None:
        return next((agent for agent in self.agents if agent.name == name), None)


def fetch_tags(url: str, timeout_s: float) -> object:
    """Ollama's model list as JSON; raises ``httpx.HTTPError`` or ``ValueError``."""
    response = httpx.get(url, timeout=timeout_s)
    response.raise_for_status()
    return response.json()


def detect(
    *,
    environ: Mapping[str, str] | None = None,
    ollama_url: str = OLLAMA_URL,
    fetch_tags: TagsFetcher = fetch_tags,
    which: Which = shutil.which,
    probe: Probe = probe_version,
) -> Detection:
    env = os.environ if environ is None else environ
    agents: list[AgentFound] = []
    for name in AGENTS:
        path = which(name)
        agents.append(AgentFound(name, path, probe(path) if path is not None else None))
    # ``in`` only: the value of a key variable is never looked at (Mimari §22).
    keys = tuple(KeyFound(api, api.env in env) for api in KNOWN_APIS)
    return Detection(_ollama(ollama_url, fetch_tags), tuple(agents), keys)


def _ollama(url: str, fetch: TagsFetcher) -> OllamaFound:
    try:
        payload = fetch(f"{url.rstrip('/')}/api/tags", OLLAMA_TIMEOUT_S)
    except (httpx.HTTPError, ValueError, OSError):
        return OllamaFound(url, False, ())
    chat, skipped = _model_names(payload)
    return OllamaFound(url, True, chat, skipped)


EMBEDDING_FAMILIES = frozenset({"bert", "nomic-bert"})


def _is_embedding(name: str, item: dict[str, Any]) -> bool:
    """``nomic-embed-text``, ``mxbai-embed-large`` …: by name, or by Ollama's model family."""
    details = item.get("details")
    families: set[str] = set()
    if isinstance(details, dict):
        family = details.get("family")
        if isinstance(family, str):
            families.add(family)
        listed = details.get("families")
        if isinstance(listed, list):
            families.update(value for value in listed if isinstance(value, str))
    return "embed" in name.lower() or bool(families & EMBEDDING_FAMILIES)


def _model_names(payload: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not isinstance(payload, dict):
        return (), ()
    models = payload.get("models")
    if not isinstance(models, list):
        return (), ()
    chat: list[str] = []
    skipped: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name:
            (skipped if _is_embedding(name, item) else chat).append(name)
    return tuple(chat), tuple(skipped)


def summary_lines(found: Detection) -> list[str]:
    """What the wizard shows after detection; key variables by name only."""
    lines: list[str] = []
    if found.ollama.reachable:
        models = ", ".join(found.ollama.models) or "-"
        lines.append(t("wizard.detect.ollama", url=found.ollama.url, models=models))
        if found.ollama.skipped:
            lines.append(t("wizard.detect.embedding", models=", ".join(found.ollama.skipped)))
    else:
        lines.append(t("wizard.detect.ollama_missing", url=found.ollama.url))
    for agent in found.agents:
        if agent.found:
            lines.append(t("wizard.detect.agent", name=agent.name, version=agent.version or "?"))
        else:
            lines.append(t("wizard.detect.agent_missing", name=agent.name))
    present = [key.api.env for key in found.keys if key.present]
    lines.append(
        t("wizard.detect.keys", names=", ".join(present)) if present else t("wizard.detect.no_keys")
    )
    return lines
