"""``show``, ``apply``, ``discard`` and ``gc`` through the real CLI (Faz 5b).

Edit tasks that create worktrees arrive in Faz 5c, so these tests set up a finished run the
way the runner will: a run directory, a ``runs`` row and a worktree attached to it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from orkestra import paths
from orkestra.cli import app
from orkestra.state import budget, db
from orkestra.workspace import git_worktree as gw
from orkestra.workspace import service

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
MakeRepo = Callable[..., Path]
FILES = {"src/app.py": "def f():\n    return 1\n", "README.md": "# demo\n"}


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


def _fake_run(
    run_id: str, repo: Path | None = None, *, edit: str | None = "    return 10\n"
) -> gw.Worktree | None:
    """A finished run with an envelope, output and log, optionally with a worktree."""
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True)
    envelope = {"envelope_version": 2, "run_id": run_id, "task_id": "t", "status": "ok",
                "summary": "did it"}  # fmt: skip
    (run_dir / "envelope.json").write_bytes(json.dumps(envelope).encode())
    (run_dir / "output.md").write_bytes(b"full output text\n")
    (run_dir / "orkestra.log").write_bytes(b"log line\n")
    started = datetime.strptime(run_id[:15], "%Y%m%d-%H%M%S").astimezone()
    with closing(db.connect()) as conn:
        db.record_run_start(conn, run_id=run_id, task_id="t", kind="edit", started_at=started)
        db.record_run_end(conn, run_id, status="ok", finished_at=started)
        if repo is None:
            return None
        wt = gw.create(repo, run_id)
        if edit is not None:
            (wt.path / "src" / "app.py").write_bytes((f"def f():\n{edit}").encode())
        service.attach_worktree(conn, run_id, wt)
    return wt


RUN = datetime.now().strftime("%Y%m%d-%H%M%S") + "-abcd"  # recent: gc keeps it


@pytest.fixture
def repo(make_repo: MakeRepo, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = make_repo(FILES)
    monkeypatch.chdir(path)
    return path


# --- show ------------------------------------------------------------------------------


def test_show_parts(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _fake_run(RUN, repo)
    code, out, _ = _run(["show", RUN, "--json"], capsys)
    assert code == 0 and json.loads(out)["summary"] == "did it"
    code, out, _ = _run(["show", RUN, "--output"], capsys)
    assert out == "full output text\n"
    code, out, _ = _run(["show", RUN, "--log"], capsys)
    assert "log line" in out
    code, out, _ = _run(["show", RUN, "--diff"], capsys)
    assert code == 0 and "+    return 10" in out and "src/app.py" in out


def test_show_errors(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _run(["--lang", "en", "show", "20261110-120000-ffff"], capsys)
    assert code == 2 and "20261110-120000-ffff" in err
    code, _, _ = _run(["show", "../../etc"], capsys)
    assert code == 2
    _fake_run(RUN, repo)
    code, _, _ = _run(["show", RUN, "--diff", "--log"], capsys)
    assert code == 2


def test_show_diff_of_a_run_without_changes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _fake_run(RUN)  # an ask run
    code, out, err = _run(["--lang", "en", "show", RUN, "--diff"], capsys)
    assert code == 0 and out == ""
    assert "no changes" in err


# --- apply -----------------------------------------------------------------------------


def test_apply_then_apply_again(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "README.md").write_bytes(b"# demo\nmine, uncommitted\n")
    wt = _fake_run(RUN, repo)
    assert wt is not None
    code, out, _ = _run(["apply", RUN, "--json"], capsys)
    assert code == 0
    result = json.loads(out)
    assert result["applied"] is True and result["files"] == ["src/app.py"]
    assert "return 10" in (repo / "src" / "app.py").read_text(encoding="utf-8")
    assert "mine, uncommitted" in (repo / "README.md").read_text(encoding="utf-8")
    assert not wt.path.exists()
    assert (paths.run_dir(RUN) / "changes.patch").is_file()  # kept for show --diff
    with closing(db.connect()) as conn:
        row = conn.execute("SELECT applied FROM runs WHERE run_id = ?", (RUN,)).fetchone()
    assert row["applied"] == 1
    code, _, err = _run(["--lang", "en", "apply", RUN], capsys)
    assert code == 2 and "already applied" in err
    code, out, _ = _run(["show", RUN, "--diff"], capsys)
    assert "+    return 10" in out


def test_apply_conflict_exits_5_and_keeps_the_worktree(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wt = _fake_run(RUN, repo)
    assert wt is not None
    (repo / "src" / "app.py").write_bytes(b"def f():\n    return 99\n")
    code, out, _ = _run(["apply", RUN, "--json"], capsys)
    assert code == 5
    error = json.loads(out)["error"]
    assert error["type"] == "WorkspaceConflict" and "src/app.py" in error["details"]
    assert wt.path.is_dir()
    assert "return 99" in (repo / "src" / "app.py").read_text(encoding="utf-8")


def test_apply_without_changes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _fake_run(RUN)  # an ask run: nothing to apply
    code, _, err = _run(["--lang", "en", "apply", RUN], capsys)
    assert code == 2 and "no changes" in err
    _fake_run(RUN[:-4] + "abce", repo, edit=None)  # worktree but the worker changed nothing
    code, out, _ = _run(["apply", RUN[:-4] + "abce", "--json"], capsys)
    assert code == 0 and json.loads(out)["files"] == []


# --- discard ---------------------------------------------------------------------------


def test_discard(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wt = _fake_run(RUN, repo)
    assert wt is not None
    code, _, _ = _run(["discard", RUN], capsys)
    assert code == 0
    assert not wt.path.exists()
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == FILES["src/app.py"]
    code, _, err = _run(["--lang", "en", "apply", RUN], capsys)
    assert code == 2 and "discarded" in err
    code, _, _ = _run(["discard", RUN], capsys)
    assert code == 0  # nothing left to do is not an error


# --- gc --------------------------------------------------------------------------------


def test_gc(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    keep = _fake_run(RUN, repo)
    old_id = (datetime.now() - timedelta(days=40)).strftime("%Y%m%d-%H%M%S") + "-0001"
    old = _fake_run(old_id, repo)
    orphan = gw.create(repo, "20261110-130000-dead")  # no run record at all
    assert keep and old
    with closing(db.connect()) as conn:
        stale = (db.local_now() - timedelta(hours=3)).isoformat()
        conn.execute(
            "INSERT INTO usage (run_id, provider, model, day, prompt_tokens, completion_tokens,"
            " cost_usd, requests, runs, estimated, kind, created_at)"
            " VALUES ('r', 'p', 'm', ?, 1, 0, 0, 1, 1, 1, 'reservation', ?)",
            (db.local_now().date().isoformat(), stale),
        )

    code, out, _ = _run(["gc", "--dry-run", "--json"], capsys)
    assert code == 0
    plan = json.loads(out)
    assert plan["dry_run"] is True
    assert sorted(plan["worktrees"]) == sorted([str(orphan.path), str(old.path)])
    assert plan["runs"] == [old_id]
    assert orphan.path.exists() and old.path.exists()

    code, out, _ = _run(["gc", "--json"], capsys)
    assert code == 0
    done = json.loads(out)
    assert done["reservations"] == 1
    assert not orphan.path.exists() and not old.path.exists()
    assert not paths.run_dir(old_id).exists()
    assert keep.path.exists() and paths.run_dir(RUN).exists()
    with closing(db.connect()) as conn:
        assert budget.used(conn, "p", db.local_now()).requests == 0
