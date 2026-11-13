"""``orkestra handoff init|update|check|show`` end to end (Faz 10a)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from orkestra import paths
from orkestra.cli import app
from orkestra.handoff import store as handoff_store
from orkestra.i18n import t

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

CONFIG = """\
version: 1
handoff:
  file: .orkestra/HANDOFF.md
  max_lines: 200
  brief_max_lines: 60
  stale_after_commits: 5
"""


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    return (
        (code if isinstance(code, int) else 0),
        _ANSI.sub("", captured.out),
        _ANSI.sub("", captured.err),
    )


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str = CONFIG) -> Path:
    home = paths.orkestra_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(config, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    monkeypatch.chdir(work)
    monkeypatch.delenv("ORKESTRA_CHIEF", raising=False)
    return work


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }  # fmt: skip
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=repo, capture_output=True,
        check=True, env=env,
    )  # fmt: skip
    return done.stdout.decode("utf-8", errors="replace")


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str = CONFIG) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "init")
    _setup(tmp_path, monkeypatch, config)
    monkeypatch.chdir(repo)
    return repo


def test_init_creates_the_file_and_refuses_to_overwrite_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    code, out, _ = _run(["handoff", "init", "--json"], capsys)
    assert code == 0, out
    doc = json.loads(out)
    path = Path(doc["path"])
    assert path == work / ".orkestra" / "HANDOFF.md"
    assert path.read_text(encoding="utf-8").startswith("<!-- orkestra-handoff v1 -->")
    before = path.read_text(encoding="utf-8")
    code, _, err = _run(["handoff", "init"], capsys)
    assert code == 2
    assert t("handoff.error.exists", path=path) in err
    assert path.read_text(encoding="utf-8") == before


def test_update_adds_a_done_item_and_show_reads_it_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    assert _run(["handoff", "init"], capsys)[0] == 0
    code, out, _ = _run(
        ["handoff", "update", "--section", "done", "--add", "wrote tests",
         "--chief", "claude", "--json"], capsys,
    )  # fmt: skip
    assert code == 0, out
    result = json.loads(out)
    assert result["section"] == "done" and result["action"] == "add"
    assert result["last_updated"]["chief"] == "claude"
    code, out, _ = _run(["handoff", "show", "--json"], capsys)
    assert code == 0, out
    shown = json.loads(out)
    assert shown["marker"] is True
    assert shown["sections"]["done"]["text"].endswith("claude] wrote tests")
    assert shown["last_updated"]["chief"] == "claude"


def test_update_uses_orkestra_chief_when_the_flag_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    assert _run(["handoff", "init"], capsys)[0] == 0
    monkeypatch.setenv("ORKESTRA_CHIEF", "agy")
    code, out, _ = _run(["handoff", "update", "--section", "goal", "--set", "ship"], capsys)
    assert code == 0, out
    text = (work / ".orkestra" / "HANDOFF.md").read_text(encoding="utf-8")
    assert "chief: agy" in text


def test_update_without_any_chief_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    assert _run(["handoff", "init"], capsys)[0] == 0
    code, _, err = _run(["handoff", "update", "--section", "goal", "--set", "ship"], capsys)
    assert code == 2
    assert t("handoff.error.no_chief") in err


@pytest.mark.parametrize(
    "argv",
    [
        ["handoff", "update", "--section", "goals", "--set", "x", "--chief", "claude"],
        ["handoff", "update", "--section", "done", "--add", "x", "--set", "y", "--chief", "claude"],
        ["handoff", "update", "--section", "done", "--set", "x", "--chief", "claude"],
        ["handoff", "update", "--section", "goal", "--add", "x", "--chief", "claude"],
        ["handoff", "update", "--section", "goal", "--chief", "claude"],
    ],
)
def test_bad_update_arguments_exit_2(
    argv: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    assert _run(["handoff", "init"], capsys)[0] == 0
    assert _run(argv, capsys)[0] == 2


def test_update_and_show_require_an_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    target = work / ".orkestra" / "HANDOFF.md"
    code, _, err = _run(
        ["handoff", "update", "--section", "goal", "--set", "x", "--chief", "claude"], capsys
    )
    assert code == 2
    assert t("handoff.error.missing", path=target) in err
    assert _run(["handoff", "show"], capsys)[0] == 2
    assert _run(["handoff", "show", "--brief"], capsys)[0] == 2


def test_show_prints_the_file_and_the_brief_never_goes_over_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(
        tmp_path, monkeypatch, CONFIG.replace("brief_max_lines: 60", "brief_max_lines: 10")
    )
    assert _run(["handoff", "init"], capsys)[0] == 0
    path = work / ".orkestra" / "HANDOFF.md"
    code, out, _ = _run(["handoff", "show"], capsys)
    assert code == 0
    assert out == path.read_text(encoding="utf-8")
    code, out, _ = _run(["handoff", "show", "--brief"], capsys)
    assert code == 0
    assert 0 < len(out.rstrip("\n").splitlines()) <= 10
    code, out, _ = _run(["handoff", "show", "--brief", "--json"], capsys)
    assert code == 0
    doc = json.loads(out)
    assert doc["lines"] <= 10
    assert doc["brief"]


def test_check_warns_after_the_threshold_and_strict_turns_that_into_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    repo = _repo(tmp_path, monkeypatch, CONFIG.replace("stale_after_commits: 5",
                                                       "stale_after_commits: 1"))  # fmt: skip
    assert _run(["handoff", "init"], capsys)[0] == 0
    assert _run(["handoff", "update", "--section", "goal", "--set", "ship",
                 "--chief", "claude"], capsys)[0] == 0  # fmt: skip
    for n in range(2):
        (repo / f"b{n}.txt").write_text("b\n", encoding="utf-8")
        _git(repo, "add", f"b{n}.txt")
        _git(repo, "commit", "-q", "-m", f"later {n}")
    code, out, _ = _run(["handoff", "check"], capsys)
    assert code == 0
    assert t("handoff.check.stale", count=2) in out
    assert _run(["handoff", "check", "--strict"], capsys)[0] == 1
    assert _run(["handoff", "check", "--warn-only"], capsys)[0] == 0


def test_check_under_the_threshold_is_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _repo(tmp_path, monkeypatch)
    assert _run(["handoff", "init"], capsys)[0] == 0
    code, out, _ = _run(["handoff", "check", "--json"], capsys)
    assert code == 0
    doc = json.loads(out)
    assert doc["exists"] is True
    assert doc["stale"] is False
    assert doc["warnings"] == []


def test_check_without_a_file_says_so_and_strict_exits_1_but_warn_only_never_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    code, out, _ = _run(["handoff", "check"], capsys)
    assert code == 0
    assert t("handoff.check.missing") in out
    assert _run(["handoff", "check", "--strict"], capsys)[0] == 1
    assert _run(["handoff", "check", "--warn-only"], capsys)[0] == 0


def test_a_commit_that_is_not_in_history_is_reported_by_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    """Inside a repository: a commit that history does not know is an explicit warning.

    Outside a repository the same file must say ``no_git`` instead (GLM B4), which is why
    this test runs inside a real repository.
    """
    repo = _repo(tmp_path, monkeypatch)
    assert _run(["handoff", "init"], capsys)[0] == 0
    path = repo / ".orkestra" / "HANDOFF.md"
    path.write_text(
        re.sub(r"commit: [0-9a-f]+", "commit: deadbeef", path.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    code, out, _ = _run(["handoff", "check"], capsys)
    assert code == 0
    assert t("handoff.check.unknown_commit", commit="deadbeef") in out


def test_check_and_status_outside_a_repository_say_no_git_not_unknown_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    """GLM B4: without a repository there is no history to look the commit up in."""
    work = _setup(tmp_path, monkeypatch)
    assert _run(["handoff", "init"], capsys)[0] == 0
    path = work / ".orkestra" / "HANDOFF.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("commit: none", "commit: deadbeef"),
        encoding="utf-8",
    )
    code, out, _ = _run(["handoff", "check"], capsys)
    assert code == 0
    assert t("handoff.check.no_git") in out
    assert t("handoff.check.unknown_commit", commit="deadbeef") not in out
    code, out, _ = _run(["status"], capsys)
    assert code == 0
    assert t("status.handoff.no_git") in out
    assert t("status.handoff.unknown_commit", commit="deadbeef") not in out


def test_handoff_commands_from_a_subfolder_use_the_repository_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    """GLM B3: the handoff file belongs to the repository root, not to the current folder."""
    repo = _repo(tmp_path, monkeypatch)
    sub = repo / "sub" / "deeper"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert _run(["handoff", "init"], capsys)[0] == 0
    path = repo / ".orkestra" / "HANDOFF.md"
    assert path.exists()
    assert f"# Devir: {repo.name}" in path.read_text(encoding="utf-8")
    assert not (sub / ".orkestra").exists()
    code, out, _ = _run(["handoff", "show"], capsys)
    assert code == 0
    assert out == path.read_text(encoding="utf-8")
    code, _, err = _run(
        ["handoff", "update", "--section", "goal", "--set", "from the subfolder",
         "--chief", "claude"], capsys,
    )  # fmt: skip
    assert code == 0, err
    assert "from the subfolder" in path.read_text(encoding="utf-8")
    code, out, _ = _run(["status"], capsys)
    assert code == 0
    assert t("status.handoff.line", goal="from the subfolder") in out
    code, out, _ = _run(["handoff", "check", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["exists"] is True


def test_a_live_lock_times_out_with_exit_code_5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    """GLM B7: a lock held by someone else must fail the CLI run with the lock exit code."""
    work = _setup(tmp_path, monkeypatch)
    assert _run(["handoff", "init"], capsys)[0] == 0
    path = work / ".orkestra" / "HANDOFF.md"
    lock = handoff_store.lock_path(path)
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    monkeypatch.setattr(handoff_store, "LOCK_TIMEOUT_S", 0.2)
    try:
        code, _, err = _run(
            ["handoff", "update", "--section", "goal", "--set", "x", "--chief", "claude"],
            capsys,
        )
    finally:
        lock.unlink(missing_ok=True)  # a foreign lock is left in place by the timeout
    assert code == 5
    assert t("handoff.error.locked", path=lock) in err


def test_show_json_reports_a_missing_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    """GLM B8: a file without the marker line is still parsed and reported as such."""
    work = _setup(tmp_path, monkeypatch)
    assert _run(["handoff", "init"], capsys)[0] == 0
    path = work / ".orkestra" / "HANDOFF.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("<!-- orkestra-handoff v1 -->\n", ""),
        encoding="utf-8",
    )
    code, out, _ = _run(["handoff", "show", "--json"], capsys)
    assert code == 0
    doc = json.loads(out)
    assert doc["marker"] is False
    assert doc["warnings"]


def test_status_has_no_handoff_section_without_a_file_and_one_with_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    code, out, _ = _run(["status", "--json"], capsys)
    assert code == 0
    assert "handoff" not in json.loads(out)["sections"]
    assert _run(["handoff", "init"], capsys)[0] == 0
    assert _run(["handoff", "update", "--section", "goal", "--set", "finish phase 10a",
                 "--chief", "claude"], capsys)[0] == 0  # fmt: skip
    code, out, _ = _run(["status"], capsys)
    assert code == 0
    assert "finish phase 10a" in out
    code, out, _ = _run(["status", "--json"], capsys)
    assert code == 0
    section = json.loads(out)["sections"]["handoff"]
    assert section["goal"] == "finish phase 10a"
    assert len(out.rstrip("\n").splitlines()) <= 15


def test_show_json_lists_every_section_and_reports_unknown_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    assert _run(["handoff", "init"], capsys)[0] == 0
    path = work / ".orkestra" / "HANDOFF.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Last updated", "## Notes\nkeep me\n\n## Last updated"
        ),
        encoding="utf-8",
    )
    code, out, _ = _run(["handoff", "show", "--json"], capsys)
    assert code == 0
    doc = json.loads(out)
    assert set(doc["sections"]) == {
        "goal", "status", "done", "in_progress", "decisions", "open_questions", "watch_out",
    }  # fmt: skip
    assert doc["unknown_sections"] == [{"heading": "Notes", "text": "keep me"}]


MANY_PROVIDERS = "providers:\n" + "".join(
    f"  local{n:02d}:\n    type: ollama\n    base_url: http://ollama{n}.test:11434\n"
    f"    budget: {{daily_requests: 100}}\n    models:\n      - id: m\n        tier: 1\n"
    for n in range(31)
)


def test_update_outside_a_repository_records_no_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    assert _run(["handoff", "init"], capsys)[0] == 0
    code, _, err = _run(
        ["handoff", "update", "--section", "goal", "--set", "ship", "--chief", "claude"], capsys
    )
    assert code == 0, err
    text = (work / ".orkestra" / "HANDOFF.md").read_text(encoding="utf-8")
    assert "commit: none" in text
    assert "chief: claude" in text


def test_status_with_thirty_one_providers_and_a_handoff_file_still_fits_fifteen_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch, CONFIG + MANY_PROVIDERS)
    assert _run(["handoff", "init"], capsys)[0] == 0
    assert _run(["handoff", "update", "--section", "goal", "--set", "finish phase 10a",
                 "--chief", "claude"], capsys)[0] == 0  # fmt: skip
    code, out, _ = _run(["status"], capsys)
    assert code == 0, out
    lines = out.rstrip("\n").splitlines()
    assert 0 < len(lines) <= 15
    assert t("status.handoff.line", goal="finish phase 10a") in lines
    code, out, _ = _run(["status", "--json"], capsys)
    assert code == 0, out
    doc = json.loads(out)
    assert len(doc["sections"]["budget"]["providers"]) == 31
    assert doc["sections"]["handoff"]["goal"] == "finish phase 10a"


# --- Claude review of Faz 10 (D-066) -----------------------------------------------------


def test_check_warn_only_is_silent_when_up_to_date_and_prints_the_warning_when_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    """``--warn-only`` runs in the pre-commit hook: say nothing unless there is a reminder."""
    repo = _repo(tmp_path, monkeypatch, CONFIG.replace("stale_after_commits: 5",
                                                       "stale_after_commits: 1"))  # fmt: skip
    assert _run(["handoff", "init"], capsys)[0] == 0
    code, out, err = _run(["handoff", "check", "--warn-only"], capsys)
    assert (code, out, err) == (0, "", "")
    for n in range(2):
        (repo / f"b{n}.txt").write_text("b\n", encoding="utf-8")
        _git(repo, "add", f"b{n}.txt")
        _git(repo, "commit", "-q", "-m", f"later {n}")
    code, out, _ = _run(["handoff", "check", "--warn-only"], capsys)
    assert code == 0
    assert out == t("handoff.check.stale", count=2) + "\n"


def test_update_that_would_add_a_heading_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _repo(tmp_path, monkeypatch)
    assert _run(["handoff", "init"], capsys)[0] == 0
    code, _, err = _run(["handoff", "update", "--section", "status", "--set",
                         "ok\n## Done\nfake", "--chief", "claude"], capsys)  # fmt: skip
    assert code == 2
    assert t("handoff.error.breaks_structure", section="status") in err
