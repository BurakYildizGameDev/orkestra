"""Faz 13r-b2/b3 code review fixes (D-135): the continuation note and ``partial_dropped``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
import respx
from conftest import git

from orkestra.config.schema import Config, ModelSpec
from orkestra.envelope import Failover
from orkestra.routing.router import Candidate
from orkestra.state import consent
from orkestra.tasks import runner, spec
from orkestra.tasks.prompts import FEEDBACK_CHARS

SECRET = "secret-test-key-123"
NOTE_HEADER = "## Continuation Note"
NOTE_OVERHEAD = 600  # header, worker line, file list and the closing instruction


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "calc.py").write_text("def a(): return 0\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def _script(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _agent(script: Path, tier: int) -> dict[str, object]:
    return {
        "type": "cli_agent",
        "command": sys.executable,
        "kind": "generic",
        "extra_args": [str(script)],
        "tier": tier,
    }


CHAT = {
    "type": "openai_compat",
    "base_url": "https://api.test/v1",
    "api_key_env": "TEST_KEY",
    "models": [{"id": "model-1", "tier": 3, "edit_format": "whole"}],
}


def test_continuation_note_names_last_agent_when_an_unavailable_candidate_intervened() -> None:
    config = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agent-a": {
                    "type": "cli_agent",
                    "command": "python",
                    "kind": "generic",
                    "tier": 1,
                },
                "agent-b": {
                    "type": "cli_agent",
                    "command": "python",
                    "kind": "generic",
                    "tier": 1,
                },
            },
        }
    )
    model = ModelSpec(id="generic", tier=1)
    last_agent = Candidate("agent-a", config.providers["agent-a"], model, 1.0, None)
    unavailable = Candidate("agent-b", config.providers["agent-b"], model, 1.0, None)
    task_run = object.__new__(runner._TaskRun)
    task_run.wt = None
    task_run.failovers = [
        Failover(
            provider="agent-b",
            model="generic",
            tier=1,
            error="ProviderCommandNotFound",
            reason="not installed",
            attempts=0,
        )
    ]
    task_run.last_agent_candidate = last_agent
    task_run.last_verify_failures = []

    note = task_run._build_continuation_note(unavailable)

    assert "Previous worker (agent-a/generic) last ran" in note
    assert "candidate agent-b/generic (ProviderCommandNotFound: not installed) failed" in note


async def test_continuation_note_is_masked_capped_and_english(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(consent, "state", lambda *_args: "granted")
    monkeypatch.setenv("TEST_KEY", SECRET)
    repo = _repo(tmp_path)
    prompt2 = tmp_path / "prompt2.txt"
    agent1 = _script(
        tmp_path / "agent1.py",
        "from pathlib import Path\n"
        "Path('file1.txt').write_text('one\\n', encoding='utf-8')\n"
        "print('agent 1 done')\n",
    )
    agent2 = _script(
        tmp_path / "agent2.py",
        "import sys\n"
        "from pathlib import Path\n"
        f"Path({str(prompt2)!r}).write_text(sys.stdin.read(), encoding='utf-8')\n"
        "Path('file2.txt').write_text('two\\n', encoding='utf-8')\n"
        "print('agent 2 done')\n",
    )
    # Unrecognised output (raw feedback): the secret, then far more than the feedback limit.
    check = (
        "import sys; from pathlib import Path; "
        f"print({SECRET[:6]!r} + {SECRET[6:]!r}); print('y' * 20000); "
        "sys.exit(0 if Path('file2.txt').exists() else 1)"
    )
    task = spec.parse_task(
        {
            "id": "note-task",
            "kind": "edit",
            "prompt": "write files 1 and 2",
            "on_failover": "continue",
            "limits": {"max_retries": 0},
            "verify": [{"type": "command", "run": f'"{sys.executable}" -c "{check}"'}],
        },
        source="test",
    )
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {"agent1": _agent(agent1, 1), "agent2": _agent(agent2, 2), "chat": CHAT},
        }
    )

    outcome = await runner.run_task(task, cfg, cwd=repo)

    assert outcome.envelope.status == "ok"
    assert outcome.envelope.changes is not None
    assert outcome.envelope.changes.files == 2
    text = prompt2.read_text(encoding="utf-8")
    note = text[text.index(NOTE_HEADER) :]
    assert SECRET not in text
    assert len(note) <= FEEDBACK_CHARS + NOTE_OVERHEAD
    assert "y" * 1000 in note  # the summary is there, only cut
    assert "VerificationFailed" in note  # English error class, not only the localized reason
    assert "file1.txt" in note


async def test_partial_dropped_only_when_the_agent_left_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(consent, "state", lambda *_args: "granted")
    monkeypatch.setenv("TEST_KEY", SECRET)
    repo = _repo(tmp_path)
    # The agent stops before writing anything: there is no partial work to drop.
    agent1 = _script(
        tmp_path / "agent1.py",
        "import sys\nsys.stderr.write('quota exhausted\\n')\nsys.exit(1)\n",
    )
    task = spec.parse_task(
        {
            "id": "no-partial",
            "kind": "edit",
            "prompt": "fix calc.py",
            "on_failover": "continue",
            "context": {"files": ["calc.py"]},
            "verify": [
                {
                    "type": "command",
                    "run": f'"{sys.executable}" -c "import calc; assert calc.a() == 42"',
                }
            ],
        },
        source="test",
    )
    cfg = Config.model_validate(
        {"version": 1, "providers": {"agent1": _agent(agent1, 1), "chat": CHAT}}
    )
    content = json.dumps({"files": [{"path": "calc.py", "content": "def a(): return 42\n"}]})
    body = {
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 20},
    }

    with respx.mock(base_url="https://api.test/v1") as mock:
        mock.post("/chat/completions").mock(return_value=httpx.Response(200, json=body))
        outcome = await runner.run_task(task, cfg, cwd=repo)

    assert outcome.envelope.status == "ok"
    assert len(outcome.envelope.failovers) == 1
    assert outcome.envelope.partial_dropped is None
    assert "partial_dropped" not in json.loads(outcome.envelope.model_dump_json())
