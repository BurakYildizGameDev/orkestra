"""``--dry-run`` shows the adaptive score and its sample count (Faz 12b, Mimari §20)."""

from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest

from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.i18n import t
from orkestra.state import consent, db

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
CONFIG = """\
version: 1
routing:
  adaptive: {adaptive}
  min_samples: 3
providers:
  ollama:
    type: ollama
    base_url: http://ollama.test:11434
    models:
      - id: first
        tier: 1
      - id: second
        tier: 1
"""


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, adaptive: bool = True) -> Path:
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(CONFIG.format(adaptive=str(adaptive).lower()),
                                      encoding="utf-8")  # fmt: skip
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    monkeypatch.chdir(work)
    config = load_config(cwd=work, environ={}).config
    now = db.local_now()
    with closing(db.connect()) as conn:
        consent.grant(conn, "ollama", config.providers["ollama"], now)
        for n in range(3):  # "second" did well on docstring tasks
            run_id = f"r{n}"
            started = now - timedelta(hours=n + 1)
            db.record_run_start(conn, run_id=run_id, task_id="t", kind="ask",
                                started_at=started, tags=["docstring"])  # fmt: skip
            db.record_run_end(conn, run_id, status="ok", provider="ollama", model="second")
    (work / "task.json").write_text(json.dumps(
        {"id": "doc", "kind": "ask", "prompt": "add a docstring", "tags": ["docstring"]}
    ), encoding="utf-8")  # fmt: skip
    return work


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    return (code if isinstance(code, int) else 0), _ANSI.sub("", captured.out), captured.err


def test_dry_run_puts_the_better_model_first_and_shows_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    code, out, err = _run(["run", "task.json", "--dry-run", "--json"], capsys)
    assert code == 0, err
    candidates = json.loads(out)["candidates"]
    assert [c["model"] for c in candidates] == ["second", "first"]
    assert candidates[0]["score"] == pytest.approx(0.8)  # (3 + 1) / (3 + 2)
    assert candidates[0]["score_samples"] == 3 and candidates[0]["score_used"] is True
    assert candidates[1]["score"] == 0.5 and candidates[1]["score_samples"] == 0
    assert candidates[1]["score_used"] is False
    code, out, _ = _run(["run", "task.json", "--dry-run"], capsys)
    assert t("route.dry.score", score="0.80", ok=3, samples=3) in out
    assert t("route.dry.score_neutral", samples=0, needed=3) in out


def test_without_adaptive_the_config_order_stays_and_no_score_is_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch, adaptive=False)
    code, out, _ = _run(["run", "task.json", "--dry-run", "--json"], capsys)
    assert code == 0
    candidates = json.loads(out)["candidates"]
    assert [c["model"] for c in candidates] == ["first", "second"]
    assert candidates[0]["score"] is None


def test_dry_run_shows_median_duration_when_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(CONFIG.format(adaptive="true"), encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    monkeypatch.chdir(work)
    config = load_config(cwd=work, environ={}).config
    now = db.local_now()
    with closing(db.connect()) as conn:
        consent.grant(conn, "ollama", config.providers["ollama"], now)
        for n, dur in enumerate([10.0, 15.0, 20.0]):
            run_id = f"dur_{n}"
            started = now - timedelta(hours=n + 1)
            db.record_run_start(
                conn, run_id=run_id, task_id="t", kind="ask", started_at=started, tags=["docstring"]
            )
            db.record_run_end(
                conn, run_id, status="ok", provider="ollama", model="second", duration_s=dur
            )
    (work / "task.json").write_text(
        json.dumps(
            {"id": "doc", "kind": "ask", "prompt": "add a docstring", "tags": ["docstring"]}
        ),
        encoding="utf-8",
    )
    code, out, _ = _run(["run", "task.json", "--dry-run", "--json"], capsys)
    assert code == 0
    candidates = json.loads(out)["candidates"]
    assert candidates[0]["model"] == "second"
    assert candidates[0]["median_duration_s"] == 15.0

    code, out, _ = _run(["run", "task.json", "--dry-run"], capsys)
    assert code == 0
    assert t("route.dry.duration", seconds="15") in out
