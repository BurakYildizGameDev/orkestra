"""Tests for concise feedback digests, fair feedback allocation, and fix commands (Faz 13r-b1)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import git

from orkestra import paths
from orkestra.chief import outparse
from orkestra.config.schema import CliAgentProvider, Config
from orkestra.errors import UsageError
from orkestra.tasks import delegate, runner, spec
from orkestra.tasks.prompts import build_retry_message
from orkestra.verify.base import VerifyContext
from orkestra.verify.command import CommandCheck

FAKE_AGENT_SCRIPT = Path(__file__).resolve().parents[1] / "fixtures" / "fake_agent.py"
START = datetime(2026, 11, 23, 10, 0).astimezone()


def _sample_ruff_13_errors() -> str:
    lines = ["Found 13 errors."]
    for i in range(1, 14):
        lines.append(f"src/pkg/mod_{i}.py:{i}:1: F40{i % 10} [*] 'unused_{i}' imported but unused")
        lines.append("  |")
        lines.append(f"{i} | import unused_import_{i}")
        lines.append(f"  | ^^^^^^^^^^^^^^^^^^^^^^^ F40{i % 10}")
        lines.append("  |")
    return "\n".join(lines) + "\n"


def _sample_pytest_9_failures() -> str:
    lines = [
        "============================= test session starts ==============================",
        "platform win32 -- Python 3.12.0",
        "rootdir: /work/proj",
        "collected 9 items",
        "",
        "=================================== FAILURES ===================================",
    ]
    for i in range(1, 10):
        sep = "_" * 30
        lines.extend(
            [
                f"{sep} test_{i} {sep}",
                f"tests/test_feature.py:{10 + i}: in test_{i}",
                f"    assert result_{i} == expected_{i}",
                "E   AssertionError: assert False == True",
            ]
        )
    lines.extend(
        [
            "=========================== short test summary info ============================",
        ]
    )
    for i in range(1, 10):
        lines.append(f"FAILED tests/test_f.py::test_{i} - AssertionError: assert False == True")
    lines.append("============================== 9 failed in 0.25s ===============================")
    return "\n".join(lines) + "\n"


def test_feedback_keeps_all_9_pytest_names_when_mixed_with_13_ruff_errors() -> None:
    ruff_out = _sample_ruff_13_errors()
    pytest_out = _sample_pytest_9_failures()

    # Digest or format failures
    digest_ruff = outparse.parse(ruff_out)
    digest_pytest = outparse.parse(pytest_out)
    assert digest_ruff is not None
    assert digest_pytest is not None

    summary_ruff = outparse.render_items(digest_ruff)
    summary_pytest = outparse.render_items(digest_pytest)

    # Build retry message with both failures
    retry_msg = build_retry_message(
        "Implement the plan",
        "I changed files.",
        [
            f"command (ruff): Command failed\n{summary_ruff}",
            f"command (pytest): Command failed\n{summary_pytest}",
        ],
        edit=True,
    )

    # All 9 test names must be present in the prompt
    for i in range(1, 10):
        assert f"test_{i}" in retry_msg, f"test_{i} was dropped from retry message!"

    # Total length must be reasonable and details within FEEDBACK_CHARS
    assert len(retry_msg) < 4000  # including base prompt and template


def test_feedback_unrecognized_output_falls_back_to_raw() -> None:
    unrecognized = "unknown_tool: error on line 42: something went wrong\n" * 5
    digest = outparse.parse(unrecognized)
    assert digest is None

    retry_msg = build_retry_message("task", "ans", [f"command: exit 1\n{unrecognized}"], edit=False)
    assert "unknown_tool: error on line 42" in retry_msg


def test_feedback_fair_share_prevents_one_verifier_crowding_out_another() -> None:
    # Two massive failures, each 5000 chars of unrecognized text
    failure_1 = "FAIL_1: " + ("A" * 5000)
    failure_2 = "FAIL_2: " + ("B" * 5000)

    retry_msg = build_retry_message("task", "ans", [failure_1, failure_2], edit=False)

    # Both must be represented in the retry message
    assert "FAIL_1" in retry_msg
    assert "FAIL_2" in retry_msg
    # Total details must not exceed FEEDBACK_CHARS
    assert "[... truncated]" in retry_msg


@pytest.mark.asyncio
async def test_command_check_uses_outparse_digest_for_feedback(tmp_path: Path) -> None:
    ctx = VerifyContext(workdir=tmp_path, output="")
    cmd = "python -c \"import sys; sys.stderr.write('bad.py:1:1: F401 unused'); sys.exit(1)\""
    check = CommandCheck(run=cmd, timeout_s=30)
    # When output matches ruff/compiler, check.feedback should contain the rendered item
    result = await check.check(ctx)
    assert not result.result.ok
    assert "bad.py:1" in result.feedback


def test_task_spec_fix_valid_on_edit() -> None:
    task = spec.parse_task(
        {
            "id": "t1",
            "kind": "edit",
            "prompt": "fix code",
            "fix": [
                {"run": "ruff check --fix .", "timeout_s": 120},
                {"run": "ruff format ."},
            ],
        },
        source="test",
    )
    assert len(task.fix) == 2
    assert task.fix[0].run == "ruff check --fix ."
    assert task.fix[0].timeout_s == 120
    assert not task.fix[0].shell
    assert task.fix[1].timeout_s == 300


def test_task_spec_fix_fails_schema_on_ask() -> None:
    with pytest.raises(UsageError):
        spec.parse_task(
            {
                "id": "t2",
                "kind": "ask",
                "prompt": "answer question",
                "fix": [{"run": "echo 1"}],
            },
            source="test",
        )


@pytest.fixture
def agent_config(tmp_path: Path) -> Config:
    agent = CliAgentProvider.model_validate(
        {
            "type": "cli_agent",
            "command": "python",
            "kind": "generic",
            "extra_args": [str(FAKE_AGENT_SCRIPT), "edit"],
        }
    )
    return Config.model_validate({"version": 1, "providers": {"agy": agent}})


@pytest.mark.asyncio
async def test_fix_runs_before_verifiers_and_modifications_are_in_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orkestra.state import consent

    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    # A fix script that appends 'fixed' to file.txt
    fix_script = tmp_path / "fixer.py"
    fix_script.write_text(
        "from pathlib import Path\n"
        "p = Path('file.txt')\n"
        "p.write_text(p.read_text() + 'fixed\\n')\n",
        encoding="utf-8",
    )

    task_data: dict[str, Any] = {
        "id": "edit-with-fix",
        "kind": "edit",
        "prompt": "add something",
        "provider": "agy",
        "fix": [{"run": f'"{sys.executable}" "{fix_script}"'}],
        "verify": [
            {
                "type": "command",
                "run": (
                    f'"{sys.executable}" -c '
                    "\"from pathlib import Path; assert 'fixed' in Path('file.txt').read_text()\""
                ),
            }
        ],
    }
    task = spec.parse_task(task_data, source="test")

    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agy": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(FAKE_AGENT_SCRIPT), "echo"],
                }
            },
        }
    )

    outcome = await runner.run_task(task, cfg, cwd=repo)
    assert outcome.exit_code == 0
    assert outcome.envelope.status == "ok"
    assert outcome.envelope.changes is not None
    assert outcome.envelope.changes.patch_path is not None
    patch_text = Path(outcome.envelope.changes.patch_path).read_text(encoding="utf-8")
    assert "fixed" in patch_text

    # Check that attempts/1/fix.log exists
    runs_dir = paths.run_dir(outcome.envelope.run_id)
    fix_log = runs_dir / "attempts" / "1" / "fix.log"
    assert fix_log.is_file()


@pytest.mark.asyncio
async def test_fix_failing_exit_code_is_ignored_and_verifiers_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orkestra.state import consent

    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    # A fix script that exits with 1 (like a formatter that changed files or flagged something)
    cmd_fix = f'"{sys.executable}" -c "import sys; print(\'formatter exit 1\'); sys.exit(1)"'
    cmd_verify = f'"{sys.executable}" -c "print(\'verifier passed\')"'
    task_data: dict[str, Any] = {
        "id": "edit-failing-fix",
        "kind": "edit",
        "prompt": "do work",
        "provider": "agy",
        "fix": [{"run": cmd_fix}],
        "verify": [{"type": "command", "run": cmd_verify}],
    }
    task = spec.parse_task(task_data, source="test")

    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agy": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(FAKE_AGENT_SCRIPT), "echo"],
                }
            },
        }
    )

    outcome = await runner.run_task(task, cfg, cwd=repo)
    assert outcome.exit_code == 0
    assert outcome.envelope.status == "ok"

    runs_dir = paths.run_dir(outcome.envelope.run_id)
    fix_log = runs_dir / "attempts" / "1" / "fix.log"
    assert fix_log.is_file()
    assert "formatter exit 1" in fix_log.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_when_fix_not_specified_behavior_is_identical_no_fix_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orkestra.state import consent

    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    cmd_verify = f'"{sys.executable}" -c "print(\'verifier passed\')"'
    task_data: dict[str, Any] = {
        "id": "edit-no-fix",
        "kind": "edit",
        "prompt": "do work",
        "provider": "agy",
        "verify": [{"type": "command", "run": cmd_verify}],
    }
    task = spec.parse_task(task_data, source="test")

    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agy": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(FAKE_AGENT_SCRIPT), "echo"],
                }
            },
        }
    )

    outcome = await runner.run_task(task, cfg, cwd=repo)
    assert outcome.exit_code == 0
    assert outcome.envelope.status == "ok"

    runs_dir = paths.run_dir(outcome.envelope.run_id)
    fix_log = runs_dir / "attempts" / "1" / "fix.log"
    assert not fix_log.exists()


def test_delegate_task_records_fix_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orkestra.state import consent

    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("test\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")

    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\nImplement feature.\n", encoding="utf-8")

    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agy": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "tier": 1,
                    "extra_args": [str(FAKE_AGENT_SCRIPT), "edit"],
                }
            },
        }
    )

    res = delegate.delegate_task(
        plan_path=plan,
        verify_commands=["pytest -q"],
        fix_commands=["ruff check --fix .", "ruff format ."],
        config=cfg,
        cwd=tmp_path,
        dry_run=True,
    )
    assert res.task_spec is not None
    assert len(res.task_spec.fix) == 2
    assert res.task_spec.fix[0].run == "ruff check --fix ."
    assert res.task_spec.fix[1].run == "ruff format ."


@pytest.mark.asyncio
async def test_fix_command_nonexistent_executable_logged_and_does_not_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orkestra.state import consent

    monkeypatch.setattr(consent, "state", lambda *_args: "granted")

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    cmd_verify = f'"{sys.executable}" -c "print(\'verifier passed\')"'
    task_data: dict[str, Any] = {
        "id": "edit-nonexistent-fix",
        "kind": "edit",
        "prompt": "do work",
        "provider": "agy",
        "fix": [{"run": "nonexistent_fixer_command_xyz --flag"}],
        "verify": [{"type": "command", "run": cmd_verify}],
    }
    task = spec.parse_task(task_data, source="test")

    cfg = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "agy": {
                    "type": "cli_agent",
                    "command": sys.executable,
                    "kind": "generic",
                    "extra_args": [str(FAKE_AGENT_SCRIPT), "echo"],
                }
            },
        }
    )

    outcome = await runner.run_task(task, cfg, cwd=repo)
    assert outcome.exit_code == 0
    assert outcome.envelope.status == "ok"

    runs_dir = paths.run_dir(outcome.envelope.run_id)
    fix_log = runs_dir / "attempts" / "1" / "fix.log"
    assert fix_log.is_file()
    assert "nonexistent_fixer_command_xyz" in fix_log.read_text(encoding="utf-8")
