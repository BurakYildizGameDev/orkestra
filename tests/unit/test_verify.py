from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from orkestra import i18n
from orkestra.errors import UsageError
from orkestra.tasks.spec import TaskSpec
from orkestra.verify import FileChange, VerifyContext, build_verifiers, run_verifiers

PY = f'"{sys.executable}"'


def _specs(*verifiers: dict[str, Any], **task: Any) -> TaskSpec:
    return TaskSpec.model_validate(
        {"id": "t", "kind": "ask", "prompt": "p", "verify": list(verifiers), **task}
    )


async def _check(
    tmp_path: Path,
    *verifiers: dict[str, Any],
    answer: str = "",
    changes: tuple[FileChange, ...] = (),
    task: dict[str, Any] | None = None,
) -> list[Any]:
    checks = build_verifiers(_specs(*verifiers, **(task or {})), base_dir=tmp_path)
    ctx = VerifyContext(workdir=tmp_path, output=answer, changes=changes)
    return await run_verifiers(checks, ctx)


# --- command ---------------------------------------------------------------------------


async def test_command_ok_and_failure_tail(tmp_path: Path) -> None:
    ok, bad = await _check(
        tmp_path,
        {"type": "command", "run": f"{PY} -c \"print('12 passed')\""},
        {"type": "command", "run": f"{PY} -c \"print('x' * 5000); raise SystemExit(3)\""},
    )
    assert (ok.result.ok, ok.result.detail.strip()) == (True, "12 passed")
    assert not bad.result.ok
    assert bad.result.detail.startswith("exit code 3")
    assert len(bad.result.detail) <= 2100  # last 2000 characters of output plus the header
    assert len(bad.log) > 5000  # the full output goes to verify.log


async def test_command_runs_in_the_workdir(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("here", encoding="utf-8")
    (result,) = await _check(
        tmp_path,
        {"type": "command", "run": f"{PY} -c \"print(open('marker.txt').read())\""},
    )
    assert result.result.ok and "here" in result.result.detail


async def test_command_timeout_kills_the_process(tmp_path: Path) -> None:
    (result,) = await _check(
        tmp_path,
        {"type": "command", "run": f'{PY} -c "import time; time.sleep(30)"', "timeout_s": 1},
    )
    assert not result.result.ok
    assert "timed out after 1 s" in result.result.detail


async def test_command_not_found(tmp_path: Path) -> None:
    (result,) = await _check(tmp_path, {"type": "command", "run": "no-such-tool-xyz --flag"})
    assert not result.result.ok
    assert "no-such-tool-xyz" in result.result.detail


async def test_shell_only_when_asked(tmp_path: Path) -> None:
    pipe = f'{PY} -c "print(\'a\')" | {PY} -c "import sys; print(sys.stdin.read().upper())"'
    (shell,) = await _check(tmp_path, {"type": "command", "run": pipe, "shell": True})
    assert shell.result.ok and "A" in shell.result.detail


# --- output checks ---------------------------------------------------------------------


async def test_json_schema_from_output_spec(tmp_path: Path) -> None:
    (tmp_path / "s.json").write_text(
        json.dumps({"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}),
        encoding="utf-8",
    )
    task = {"output": {"format": "json", "schema": "s.json"}}
    (ok,) = await _check(tmp_path, answer='```json\n{"n": 1}\n```', task=task)
    (wrong,) = await _check(tmp_path, answer='{"n": "one"}', task=task)
    (broken,) = await _check(tmp_path, answer="{oops", task=task)
    assert ok.result.ok
    assert not wrong.result.ok and wrong.result.detail.startswith("n:")
    assert not broken.result.ok and "not valid JSON" in broken.result.detail


async def test_json_without_schema_only_checks_parsing(tmp_path: Path) -> None:
    (ok,) = await _check(tmp_path, answer="[1, 2]", task={"output": {"format": "json"}})
    (bad,) = await _check(tmp_path, answer="not json", task={"output": {"format": "json"}})
    assert ok.result.ok and not bad.result.ok


def test_bad_schema_file_is_a_usage_error(tmp_path: Path) -> None:
    (tmp_path / "s.json").write_text('{"type": 12}', encoding="utf-8")
    with pytest.raises(UsageError):
        build_verifiers(_specs({"type": "json_schema", "schema": "s.json"}), base_dir=tmp_path)
    with pytest.raises(UsageError):
        build_verifiers(
            _specs({"type": "json_schema", "schema": "missing.json"}), base_dir=tmp_path
        )


async def test_regex(tmp_path: Path) -> None:
    spec = {"type": "regex", "must_match": [r"^def \w+", "return"], "must_not_match": ["TODO"]}
    (ok,) = await _check(tmp_path, spec, answer="x = 1\ndef f():\n    return 1\n")
    (missing,) = await _check(tmp_path, spec, answer="def f():\n    pass\n")
    (forbidden,) = await _check(tmp_path, spec, answer="def f():\n    return 1  # TODO\n")
    assert ok.result.ok
    assert not missing.result.ok and "return" in missing.result.detail
    assert not forbidden.result.ok and "TODO" in forbidden.result.detail


# --- file checks -----------------------------------------------------------------------

CHANGES = (
    FileChange("src/util.py", insertions=30, deletions=5),
    FileChange("tests/test_util.py", insertions=2, deletions=2),
)


async def test_change_limits(tmp_path: Path) -> None:
    files_ok, files_bad, lines_ok, lines_bad = await _check(
        tmp_path,
        {"type": "max_changed_files", "value": 2},
        {"type": "max_changed_files", "value": 1},
        {"type": "max_diff_lines", "value": 39},
        {"type": "max_diff_lines", "value": 38},
        changes=CHANGES,
    )
    assert files_ok.result.ok and lines_ok.result.ok
    assert not files_bad.result.ok and "2" in files_bad.result.detail
    assert not lines_bad.result.ok and "39" in lines_bad.result.detail


async def test_protect_and_forbid_paths(tmp_path: Path) -> None:
    protect, forbid, clean = await _check(
        tmp_path,
        {"type": "protect_paths", "paths": ["tests/**"]},
        {"type": "forbid_paths", "paths": ["*.py"]},
        {"type": "protect_paths", "paths": ["docs/**", ".env"]},
        changes=CHANGES,
    )
    assert not protect.result.ok and "tests/test_util.py" in protect.result.detail
    assert not forbid.result.ok and "src/util.py" in forbid.result.detail
    assert clean.result.ok


async def test_files_exist(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("a", encoding="utf-8")
    ok, missing = await _check(
        tmp_path,
        {"type": "files_exist", "paths": ["docs/a.md", "docs/*.md"]},
        {"type": "files_exist", "paths": ["docs/a.md", "CHANGELOG.md", "src/*.py"]},
    )
    assert ok.result.ok
    assert not missing.result.ok
    assert "CHANGELOG.md" in missing.result.detail and "src/*.py" in missing.result.detail


async def test_ask_task_without_changes_passes_change_checks(tmp_path: Path) -> None:
    results = await _check(
        tmp_path,
        {"type": "max_changed_files", "value": 0},
        {"type": "protect_paths", "paths": ["**"]},
    )
    assert all(r.result.ok for r in results)


# --- languages -------------------------------------------------------------------------


async def test_detail_follows_the_ui_language_feedback_stays_english(tmp_path: Path) -> None:
    i18n.set_language("tr")
    (result,) = await _check(tmp_path, {"type": "regex", "must_match": ["xyz"]}, answer="abc")
    assert "xyz" in result.result.detail and "pattern not found" not in result.result.detail
    assert result.feedback.startswith("regex: pattern not found: xyz")


# --- code review fixes (PR #6) ---------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="PATHEXT lookup is Windows-only")
async def test_windows_cmd_tools_are_found_without_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "fakenpm.cmd").write_text("@echo npm says %1\r\n", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{tools};{__import__('os').environ['PATH']}")
    (result,) = await _check(tmp_path, {"type": "command", "run": "fakenpm hello"})
    assert result.result.ok, result.result.detail
    assert "npm says hello" in result.result.detail


async def test_timeout_never_hangs_on_a_process_that_keeps_the_pipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from orkestra.verify import command

    monkeypatch.setattr(command, "KILL_GRACE_S", 0.5)
    # The parent exits at once; its child keeps stdout open and is no longer in the tree.
    script = (
        "import subprocess, sys; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(8)'])"
    )
    started = time.monotonic()
    (result,) = await _check(
        tmp_path, {"type": "command", "run": f'{PY} -c "{script}"', "timeout_s": 1}
    )
    assert time.monotonic() - started < 6
    assert not result.result.ok and "timed out" in result.result.detail


async def test_regex_reports_every_failed_pattern(tmp_path: Path) -> None:
    spec = {"type": "regex", "must_match": ["^Summary:", "^Risks:"], "must_not_match": ["TODO"]}
    (result,) = await _check(tmp_path, spec, answer="TODO: write it")
    assert not result.result.ok
    for part in ("^Summary:", "^Risks:", "TODO"):
        assert part in result.result.detail and part in result.feedback


async def test_files_exist_accepts_absolute_paths_and_globs(tmp_path: Path) -> None:
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "a.json").write_text("{}", encoding="utf-8")
    absolute = (tmp_path / "out").as_posix()
    (result,) = await _check(
        tmp_path, {"type": "files_exist", "paths": [f"{absolute}/a.json", f"{absolute}/*.json"]}
    )
    assert result.result.ok, result.result.detail
