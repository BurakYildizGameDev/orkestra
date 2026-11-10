"""Real services. Skipped by default; run with ``uv run pytest -m live``.

Environment:
- ``ORKESTRA_LIVE_OLLAMA_MODEL``: installed Ollama model (default ``qwen2.5-coder:1.5b``)
- ``OPENROUTER_API_KEY`` and ``ORKESTRA_LIVE_OPENROUTER_MODEL`` for the OpenRouter test
- an installed, logged-in ``codex`` for the code agent test (uses one small task)
"""

from __future__ import annotations

import os

import httpx
import pytest

from orkestra.config.schema import OllamaProvider, OpenAICompatProvider
from orkestra.providers.base import CompletionRequest
from orkestra.providers.ollama import OllamaChat
from orkestra.providers.openai_compat import OpenAICompatChat

pytestmark = pytest.mark.live


def _ollama_running() -> bool:
    try:
        return httpx.get("http://localhost:11434/api/tags", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


async def test_live_ollama_ask() -> None:
    if not _ollama_running():
        pytest.skip("Ollama is not running on localhost:11434")
    model = os.environ.get("ORKESTRA_LIVE_OLLAMA_MODEL", "qwen2.5-coder:1.5b")
    cfg = OllamaProvider.model_validate(
        {"type": "ollama", "models": [{"id": model, "tier": 1, "context_window": 4096}]}
    )
    result = await OllamaChat("ollama", cfg).complete(
        CompletionRequest(
            model=model,
            system="Answer briefly.",
            user="merhaba",
            max_output_tokens=32,
            timeout_s=600,
        )
    )
    assert result.text.strip()
    assert result.usage.prompt_tokens


async def test_live_openrouter_ask() -> None:
    model = os.environ.get("ORKESTRA_LIVE_OPENROUTER_MODEL")
    if not (os.environ.get("OPENROUTER_API_KEY") and model):
        pytest.skip("OPENROUTER_API_KEY / ORKESTRA_LIVE_OPENROUTER_MODEL not set")
    cfg = OpenAICompatProvider.model_validate(
        {
            "type": "openai_compat",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            "models": [{"id": model, "tier": 2}],
        }
    )
    result = await OpenAICompatChat("openrouter", cfg).complete(
        CompletionRequest(model=model, system="Answer briefly.", user="hi", max_output_tokens=16)
    )
    assert result.text.strip()


def test_live_codex_edit_and_apply(make_repo: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real ``codex exec`` fixes a bug in a worktree; ``apply`` brings it home (Faz 6).

    Uses your ``codex login`` session (one small task). Skipped when codex is not installed.
    """
    import asyncio
    import shutil
    import sys
    from contextlib import closing
    from pathlib import Path

    from orkestra.config.loader import load_config
    from orkestra.state import consent, db
    from orkestra.tasks import runner, spec
    from orkestra.workspace import service

    if shutil.which("codex") is None:
        pytest.skip("codex is not installed")
    repo: Path = make_repo(  # type: ignore[operator]
        {
            "calc.py": "def add(a, b):\n    return a - b\n",
            "tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n"
            "    assert add(2, 3) == 5\n",
            ".gitignore": "__pycache__/\n",
        }
    )
    monkeypatch.chdir(repo)
    home = Path(os.environ["ORKESTRA_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        "version: 1\nproviders:\n  codex:\n    type: cli_agent\n    command: codex\n",
        encoding="utf-8",
    )
    config = load_config(cwd=repo).config
    with closing(db.connect()) as conn:
        consent.grant(conn, "codex", config.providers["codex"], db.local_now())
    task = spec.parse_task(
        {
            "id": "live-fix", "kind": "edit", "prompt": "Fix add() in calc.py so the tests pass.",
            "context": {"files": ["calc.py"]},
            "verify": [
                {"type": "command", "run": f'"{sys.executable}" -m pytest -q tests'},
                {"type": "protect_paths", "paths": ["tests/**"]},
            ],
        },
        source="live",
    )  # fmt: skip
    outcome = asyncio.run(runner.run_task(task, config, cwd=repo))
    assert outcome.envelope.status == "ok", outcome.envelope
    assert (repo / "calc.py").read_bytes().decode() == "def add(a, b):\n    return a - b\n"
    with closing(db.connect()) as conn:
        service.apply_run(conn, outcome.envelope.run_id)
    assert "a + b" in (repo / "calc.py").read_bytes().decode()
