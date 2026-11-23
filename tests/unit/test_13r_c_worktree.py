"""Faz 13r-c acceptance trial findings (D-136): the reset keeps ``.venv``, the agent's change is
saved before the reset."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from orkestra.config.schema import Config
from orkestra.state import consent
from orkestra.tasks import runner, spec
from orkestra.workspace import git_worktree as gw

MakeRepo = Callable[..., Path]


def test_reset_keeps_the_virtual_environment(make_repo: MakeRepo) -> None:
    # ``uv run`` in a verifier creates ``.venv`` in the worktree. Deleting it between attempts
    # failed on Windows (a locked python.exe crashed the run) and rebuilt it every round.
    repo = make_repo({"app.py": "x = 1\n", ".gitignore": "build/\n"})
    wt = gw.create(repo, "run-1")
    (wt.path / ".venv" / "Scripts").mkdir(parents=True)
    (wt.path / ".venv" / "Scripts" / "python.exe").write_bytes(b"exe")
    (wt.path / ".venv" / ".gitignore").write_bytes(b"*\n")  # as uv (and venv 3.13+) write it
    (wt.path / "build").mkdir()
    (wt.path / "build" / "out.txt").write_bytes(b"ignored output\n")
    (wt.path / "junk.txt").write_bytes(b"left by a verifier\n")
    (wt.path / "app.py").write_bytes(b"x = 2\n")

    gw.reset(wt)

    assert (wt.path / ".venv" / "Scripts" / "python.exe").read_bytes() == b"exe"
    assert not (wt.path / "build").exists()  # other ignored files still go
    assert not (wt.path / "junk.txt").exists()
    assert (wt.path / "app.py").read_bytes() == b"x = 1\n"
    assert gw.diff(wt).files == ()  # .venv is not part of the change


async def test_agent_change_is_saved_before_the_reset(
    make_repo: MakeRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the reset after the checks fails, the agent's work must still be on disk.
    monkeypatch.setattr(consent, "state", lambda *_args: "granted")
    repo = make_repo({"base.txt": "initial\n"})
    agent = tmp_path / "agent.py"
    agent.write_text(
        "from pathlib import Path\n"
        "Path('new_module.py').write_text('VALUE = 41\\n', encoding='utf-8')\n"
        "print('done')\n",
        encoding="utf-8",
    )
    check = "from pathlib import Path; assert '42' in Path('new_module.py').read_text()"
    task = spec.parse_task(
        {
            "id": "saved-patch",
            "kind": "edit",
            "prompt": "write new_module.py",
            "limits": {"max_retries": 0},
            "verify": [{"type": "command", "run": f'"{sys.executable}" -c "{check}"'}],
        },
        source="test",
    )
    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agent": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(agent)],
                    "tier": 1,
                }
            },
        }
    )

    outcome = await runner.run_task(task, cfg, cwd=repo)

    assert outcome.envelope.status != "ok"
    run_dir = tmp_path / "orkestra-home" / "runs" / outcome.envelope.run_id
    patch = (run_dir / "attempts" / "1" / "changes.patch").read_text(encoding="utf-8")
    assert "new_module.py" in patch
    assert "VALUE = 41" in patch
