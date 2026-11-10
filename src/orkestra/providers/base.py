"""Provider data classes and protocols (Mimari §4.3).

Every adapter translates its failures into the ``ProviderError`` family from ``errors.py``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from orkestra.errors import ProviderError

# Conservative characters per token for estimates before a request (real tokenizers average
# about 4). Shared by budgets, the router's context check and the Ollama num_ctx check.
CHARS_PER_TOKEN = 3.5


def estimate_tokens(chars: int) -> int:
    return math.ceil(chars / CHARS_PER_TOKEN)


def retry_after(headers: Mapping[str, str]) -> float | None:
    """Seconds from ``retry-after`` (or OpenAI's ``retry-after-ms``); ``None`` if unusable."""
    value = headers.get("retry-after")
    if value is None and headers.get("retry-after-ms") is not None:
        try:
            return float(headers["retry-after-ms"]) / 1000
        except ValueError:
            return None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    estimated: bool = False  # True when the numbers are estimates


@dataclass(frozen=True)
class CompletionRequest:
    model: str
    system: str
    user: str
    max_output_tokens: int
    json_mode: bool = False
    timeout_s: int = 300


@dataclass(frozen=True)
class CompletionResult:
    text: str
    usage: Usage
    raw_finish_reason: str | None


@dataclass(frozen=True)
class AgentRequest:
    prompt: str
    workdir: Path  # isolated worktree
    model: str | None
    sandbox: str
    timeout_s: int
    output_file: Path  # final message is written here; agent records go next to it


@dataclass(frozen=True)
class AgentResult:
    final_message: str
    exit_code: int
    stdout_path: Path
    stderr_path: Path
    usage: Usage


@dataclass(frozen=True)
class HealthReport:
    ok: bool
    models: tuple[str, ...] | None = None  # models the provider reports, if it can list them
    version: str | None = None
    error: ProviderError | None = None


class ChatProvider(Protocol):
    name: str

    async def complete(self, req: CompletionRequest) -> CompletionResult: ...

    async def health(self) -> HealthReport: ...


class AgentProvider(Protocol):
    name: str

    async def run(self, req: AgentRequest) -> AgentResult: ...

    async def health(self) -> HealthReport: ...  # installed, version, logged in
