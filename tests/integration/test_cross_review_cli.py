"""Faz 13m (D-098): another provider reviews a worker's change, ``apply --max-risk`` trusts
only such a review, and ``show --report`` is the short report for the chief."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import pytest

from orkestra import paths
from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.providers.base import CompletionRequest, CompletionResult, Usage
from orkestra.providers.ollama import OllamaChat
from orkestra.providers.openai_compat import OpenAICompatChat
from orkestra.state import consent, db

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
MakeRepo = Callable[..., Path]
LOW = json.dumps({"risk": "low", "flags": [], "summary": "Looks right."})
FLAGGED = json.dumps({"risk": "medium", "summary": "One doubt.", "flags": [
    {"file": "src/calc.py", "start_line": 2, "end_line": 2, "reason": "sign", "severity": "medium"}
]})  # fmt: skip

CONFIG = """\
version: 1
providers:
  ollama:
    type: ollama
    base_url: http://ollama.test:11434
    models: [{id: coder, tier: 2}]
  router:
    type: openai_compat
    base_url: https://router.test/api/v1
    api_key_env: ROUTER_KEY
    models: [{id: remote-model, tier: 2}]
"""
PATCH = """\
--- a/src/calc.py
+++ b/src/calc.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""


class Calls:
    def __init__(self) -> None:
        self.by: list[str] = []
        self.answer = LOW


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    seen = Calls()

    async def ollama(self: OllamaChat, req: CompletionRequest) -> CompletionResult:
        seen.by.append("ollama")
        return CompletionResult(seen.answer, Usage(10, 5, 0.0), "stop")

    async def remote(self: OpenAICompatChat, req: CompletionRequest) -> CompletionResult:
        seen.by.append("router")
        return CompletionResult(seen.answer, Usage(10, 5, 0.0), "stop")

    monkeypatch.setattr(OllamaChat, "complete", ollama)
    monkeypatch.setattr(OpenAICompatChat, "complete", remote)
    return seen


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: str = "") -> None:
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(CONFIG + extra, encoding="utf-8")
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("ROUTER_KEY", "sk-test-000000000000000000000000")
    loaded = load_config(cwd=project, environ={}).config
    with closing(db.connect()) as conn:
        for name, provider in loaded.providers.items():
            consent.grant(conn, name, provider, db.local_now())


def _fake_run(run_id: str, author: str, *, status: str = "ok") -> Path:
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.yaml").write_text("id: fix-add\nkind: edit\nprompt: Fix add\n",
                                       encoding="utf-8")  # fmt: skip
    (run_dir / "changes.patch").write_text(PATCH, encoding="utf-8")
    envelope = {
        "envelope_version": 4, "run_id": run_id, "task_id": "fix-add", "status": status,
        "provider": author, "model": "coder", "tier": 2, "attempts": 1,
        "summary": "Fixed the sign in add().\nMore detail here.",
        "verification": [{"type": "command", "ok": True, "detail": "pytest -q"}],
        "changes": {"files": 1, "insertions": 1, "deletions": 1},
    }  # fmt: skip
    (run_dir / "envelope.json").write_text(json.dumps(envelope), encoding="utf-8")
    return run_dir


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    return (code if isinstance(code, int) else 0), _ANSI.sub("", captured.out), captured.err


RUN = "20261118-120000-ab12"


def test_the_author_does_not_review_its_own_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: Calls,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    run_dir = _fake_run(RUN, "ollama")  # ollama comes first in the config

    code, out, _ = _run(["review", RUN, "--json"], capsys)

    assert code == 0 and calls.by == ["router"]
    report = json.loads(out)
    assert report["author"] == "ollama" and report["independent"] is True
    assert report["model"] == "router/remote-model"
    envelope = json.loads((run_dir / "envelope.json").read_text(encoding="utf-8"))
    assert envelope["review"] == {"risk": "low", "flags_count": 0, "by": "router/remote-model",
                                  "independent": True}  # fmt: skip


def test_review_by_names_the_reviewer_for_an_author(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: Calls,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch, "review:\n  by:\n    router: [router, ollama]\n")
    _fake_run(RUN, "router")

    code, out, _ = _run(["review", RUN, "--json"], capsys)

    assert code == 0 and calls.by == ["ollama"]  # the author is dropped from its own list
    assert json.loads(out)["independent"] is True


def test_a_star_entry_is_every_authors_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: Calls,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch, "review:\n  by:\n    '*': [router]\n")
    _fake_run(RUN, "ollama")
    code, _, _ = _run(["review", RUN, "--json"], capsys)
    assert code == 0 and calls.by == ["router"]


def test_with_no_other_provider_the_author_reviews_and_it_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: Calls,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch, "review:\n  by:\n    ollama: [nobody-else]\n")
    (tmp_path / "orkestra-home" / "config.yaml").write_text(
        CONFIG.split("  router:")[0], encoding="utf-8"
    )
    _fake_run(RUN, "ollama")

    code, out, _ = _run(["review", RUN, "--json"], capsys)

    assert code == 0 and calls.by == ["ollama"]
    assert json.loads(out)["independent"] is False


def test_independence_can_be_turned_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: Calls,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch, "review:\n  independent: false\n")
    _fake_run(RUN, "ollama")
    code, out, _ = _run(["review", RUN, "--json"], capsys)
    assert code == 0 and calls.by == ["ollama"]
    assert json.loads(out)["independent"] is False


# --- apply --max-risk ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("review", "key"),
    [
        (None, "not_reviewed"),
        ({"risk": "medium", "flags_count": 1, "by": "router/x", "independent": True}, "too_risky"),
        ({"risk": "unknown", "flags_count": 0, "by": "router/x", "independent": True}, "too_risky"),
        ({"risk": "low", "flags_count": 0, "by": "ollama/coder", "independent": False},
         "not_independent"),
        ({"risk": "low", "flags_count": 0}, "not_independent"),  # a review from before 13m
    ],
)  # fmt: skip
def test_apply_max_risk_refuses_what_an_independent_review_did_not_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    review: dict[str, object] | None, key: str,
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    run_dir = _fake_run(RUN, "ollama")
    if review is not None:
        envelope = json.loads((run_dir / "envelope.json").read_text(encoding="utf-8"))
        envelope["review"] = review
        (run_dir / "envelope.json").write_text(json.dumps(envelope), encoding="utf-8")

    code, _, err = _run(["--lang", "en", "apply", RUN, "--max-risk", "low"], capsys)

    assert code == 2
    fragment = {"not_reviewed": "has no review", "too_risky": "above --max-risk",
                "not_independent": "not by another provider"}[key]  # fmt: skip
    assert fragment in " ".join(err.split())


def test_risk_check_passes_an_independent_low_review(tmp_path: Path) -> None:
    from orkestra.workspace import service

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    review = {"risk": "low", "flags_count": 0, "by": "r/m", "independent": True}
    envelope = {"run_id": RUN, "task_id": "t", "status": "ok", "review": review}
    (run_dir / "envelope.json").write_text(json.dumps(envelope), encoding="utf-8")
    assert service.risk_problem(RUN, run_dir, "low") is None
    assert service.risk_problem(RUN, run_dir, "medium") is None


# --- show --report ------------------------------------------------------------------------


def test_show_report_is_the_short_report_for_the_chief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: Calls,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    _fake_run(RUN, "ollama")
    calls.answer = FLAGGED
    _run(["review", RUN, "--json"], capsys)

    code, out, _ = _run(["--lang", "en", "show", RUN, "--report"], capsys)

    assert code == 0
    lines = out.strip().splitlines()
    assert len(lines) <= 7
    assert "Fixed the sign in add()." in lines[0] and "More detail" not in out
    assert "command ok" in out and "1 file" in out
    assert "medium" in out and "router/remote-model" in out and "independent" in out
    assert "src/calc.py:2" in out  # the flag as a pointer
    assert f"orkestra show {RUN} --diff --only-flagged" in out

    code, out, _ = _run(["show", RUN, "--report", "--json"], capsys)
    report = json.loads(out)
    assert report["risk"] == "medium" and report["pointers"] == ["src/calc.py:2 sign"]
    assert report["next"] == f"orkestra show {RUN} --diff --only-flagged"


def test_a_low_independent_review_points_at_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: Calls,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    _fake_run(RUN, "ollama")
    _run(["review", RUN, "--json"], capsys)
    _, out, _ = _run(["show", RUN, "--report", "--json"], capsys)
    assert json.loads(out)["next"] == f"orkestra apply {RUN} --max-risk low"


def test_an_unreviewed_run_points_at_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path, monkeypatch)
    _fake_run(RUN, "ollama")
    code, out, _ = _run(["show", RUN, "--report", "--json"], capsys)
    assert code == 0 and json.loads(out)["next"] == f"orkestra review {RUN} --json"
    assert json.loads(out)["risk"] is None
