"""Faz 8b: repomap, review, and plan expand, end to end (Mimari §19)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from orkestra import paths
from orkestra.chief import call, repomap, review
from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.envelope import ENVELOPE_VERSION
from orkestra.errors import ExitCode, ProviderAuthError, ProviderTransient
from orkestra.i18n import t
from orkestra.providers.base import CompletionRequest, CompletionResult, Usage
from orkestra.providers.ollama import OllamaChat
from orkestra.providers.openai_compat import OpenAICompatChat
from orkestra.state import consent, db, health
from orkestra.tasks import batch
from orkestra.tasks.runner import ProviderSlots

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
MakeRepo = Callable[..., Path]

CONFIG_LOCAL_AND_REMOTE = """\
version: 1
defaults:
  profile: balanced
providers:
  ollama:
    type: ollama
    base_url: http://ollama.test:11434
    local: true
    concurrency: 4
    models:
      - id: coder
        tier: 1
  router:
    type: openai_compat
    base_url: https://router.test/api/v1
    local: false
    api_key_env: ROUTER_KEY
    models:
      - id: remote-model
        tier: 2
"""

CONFIG_REMOTE_ONLY = """\
version: 1
providers:
  router:
    type: openai_compat
    base_url: https://router.test/api/v1
    local: false
    api_key_env: ROUTER_KEY
    models:
      - id: remote-model
        tier: 2
"""


class FakeWorker:
    def __init__(self) -> None:
        self.calls: list[CompletionRequest] = []
        self.answers: list[str | Exception] = []
        self.default_answer: str = "A fine summary."

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        self.calls.append(req)
        answer = self.answers.pop(0) if self.answers else self.default_answer
        if isinstance(answer, Exception):
            raise answer
        return CompletionResult(answer, Usage(40, 12, 0.0), "stop")


@pytest.fixture
def fake_ollama(monkeypatch: pytest.MonkeyPatch) -> FakeWorker:
    worker = FakeWorker()

    async def complete(self: OllamaChat, req: CompletionRequest) -> CompletionResult:
        return await worker.complete(req)

    monkeypatch.setattr(OllamaChat, "complete", complete)
    return worker


@pytest.fixture
def fake_remote(monkeypatch: pytest.MonkeyPatch) -> FakeWorker:
    worker = FakeWorker()

    async def complete(self: OpenAICompatChat, req: CompletionRequest) -> CompletionResult:
        return await worker.complete(req)

    monkeypatch.setattr(OpenAICompatChat, "complete", complete)
    return worker


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


def _setup_repo(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: str = CONFIG_LOCAL_AND_REMOTE,
    files: dict[str, str] | None = None,
) -> Path:
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(config, encoding="utf-8")
    initial_files = files or {
        "src/util.py": "def add(a: int, b: int) -> int:\n    return a + b\n",
        "README.md": "# Sample Project\n",
    }
    repo_path = make_repo(initial_files)
    monkeypatch.chdir(repo_path)
    monkeypatch.setenv("ROUTER_KEY", "sk-or-v1-TESTKEY000000000000000000000000")
    loaded = load_config(cwd=repo_path, environ={}).config
    with closing(db.connect()) as conn:
        for name, provider in loaded.providers.items():
            consent.grant(conn, name, provider, db.local_now())
    return repo_path


# --- 1. Map Privacy & Caching -----------------------------------------------------------


def test_map_privacy_rule_never_sends_file_content_to_remote_when_no_local_provider(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_remote: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The very first test (GEMINI.md rule): if no local provider is available, map never sends
    any file content to a remote provider (privacy: local_only default).

    Only model-free structural information is extracted; model summaries are skipped, and a
    notice is written.
    """
    repo = _setup_repo(
        make_repo,
        tmp_path,
        monkeypatch,
        config=CONFIG_REMOTE_ONLY,
        files={
            "src/secret_logic.py": (
                "class SecretVault:\n    def unlock(self, key: str) -> bool:\n        return True\n"
            ),
        },
    )

    code, out, err = _run(["map"], capsys)
    assert code == 0

    # Privacy guarantee: remote provider must have received 0 requests!
    assert len(fake_remote.calls) == 0

    # Structural info must still be generated in .orkestra/MAP.md
    map_md = repo / ".orkestra" / "MAP.md"
    assert map_md.is_file()
    content = map_md.read_text(encoding="utf-8")
    assert "SecretVault" in content
    assert "unlock" in content

    # Notice must inform that no local provider was available and model summaries were skipped
    assert "local" in (err + out).lower()


def test_map_caches_unchanged_files_and_invalidates_changed_and_drops_deleted(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Acceptance criterion: 2nd map run makes 0 model calls for unchanged files; modifying one
    file only summarizes that file; a deleted file drops from MAP.md."""
    repo = _setup_repo(
        make_repo,
        tmp_path,
        monkeypatch,
        config=CONFIG_LOCAL_AND_REMOTE,
        files={
            "src/a.py": "def foo(): pass\n",
            "src/b.py": "def bar(): pass\n",
        },
    )

    # 1st run: both files summarized
    code, _out, _err = _run(["map"], capsys)
    assert code == 0
    assert len(fake_ollama.calls) == 2

    # 2nd run: unchanged files, 0 model calls
    fake_ollama.calls.clear()
    code, _out, _err = _run(["map"], capsys)
    assert code == 0
    assert len(fake_ollama.calls) == 0

    # Modify src/b.py
    (repo / "src" / "b.py").write_text("def bar(): return 42\n", encoding="utf-8")
    fake_ollama.calls.clear()
    code, _out, _err = _run(["map"], capsys)
    assert code == 0
    # Exactly 1 call, only for modified b.py
    assert len(fake_ollama.calls) == 1
    call_req = fake_ollama.calls[0]
    assert "bar" in call_req.user or "b.py" in call_req.user

    # Delete src/a.py: drops from MAP.md, 0 calls
    (repo / "src" / "a.py").unlink()
    fake_ollama.calls.clear()
    code, _out, _err = _run(["map"], capsys)
    assert code == 0
    assert len(fake_ollama.calls) == 0
    map_text = (repo / ".orkestra" / "MAP.md").read_text(encoding="utf-8")
    assert "a.py" not in map_text
    assert "b.py" in map_text


# --- 2. Review: Schema-invalid fallback and --only-flagged --------------------------------


_DEFAULT_PATCH = (
    "--- a/src/calc.py\n+++ b/src/calc.py\n@@ -10,3 +10,4 @@\n"
    " def add(a, b):\n-    return a - b\n+    return a + b\n+    # risky line\n"
)


def _create_fake_run(
    run_id: str,
    patch: str = _DEFAULT_PATCH,
    task_prompt: str = "Fix add in calc.py",
) -> Path:
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.yaml").write_text(
        f"id: fix-add\nkind: edit\nprompt: {task_prompt}\n", encoding="utf-8"
    )
    (run_dir / "changes.patch").write_text(patch, encoding="utf-8")
    envelope_data = {
        "envelope_version": 3,
        "run_id": run_id,
        "task_id": "fix-add",
        "status": "ok",
        "provider": "ollama",
        "model": "coder",
        "tier": 1,
        "attempts": 1,
        "summary": "1 file changed",
        "changes": {
            "files": 1,
            "insertions": 2,
            "deletions": 1,
            "patch_path": str(run_dir / "changes.patch"),
        },
    }
    (run_dir / "envelope.json").write_text(json.dumps(envelope_data, indent=2), encoding="utf-8")
    return run_dir


def test_review_retries_once_on_schema_invalid_output_then_falls_back_to_unknown_risk(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_remote: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Acceptance criterion: if the fake model returns schema-invalid output, review retries
    once with feedback, and if still invalid, falls back to risk: unknown."""
    _setup_repo(make_repo, tmp_path, monkeypatch, config=CONFIG_LOCAL_AND_REMOTE)
    run_id = "20261111-120000-a1b2"
    run_dir = _create_fake_run(run_id)

    # Both tries return invalid JSON
    fake_remote.answers = ["This is not valid JSON at all.", "Still invalid JSON schema output"]

    code, _out, _err = _run(["review", run_id], capsys)
    assert code == 0

    # Tried first attempt + 1 retry = 2 calls
    assert len(fake_remote.calls) == 2
    assert (
        "schema" in fake_remote.calls[1].user.lower() or "json" in fake_remote.calls[1].user.lower()
    )

    # Result saved to runs/<run_id>/review.json
    review_path = run_dir / "review.json"
    assert review_path.is_file()
    review_data = json.loads(review_path.read_text(encoding="utf-8"))
    assert review_data["risk"] == "unknown"

    # envelope.json bumped to ENVELOPE_VERSION (4) and review summary added
    env_data = json.loads((run_dir / "envelope.json").read_text(encoding="utf-8"))
    assert env_data["envelope_version"] == ENVELOPE_VERSION
    assert env_data["review"]["risk"] == "unknown"
    assert env_data["review"]["flags_count"] == 0


def test_review_valid_flags_and_show_only_flagged(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_remote: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Acceptance criterion: review produces flags, and show --only-flagged shows only flagged
    ranges with +-5 lines of context."""
    _setup_repo(make_repo, tmp_path, monkeypatch, config=CONFIG_LOCAL_AND_REMOTE)
    run_id = "20261111-120500-c3d4"
    run_dir = _create_fake_run(
        run_id,
        patch="""\
--- a/src/calc.py
+++ b/src/calc.py
@@ -1,15 +1,16 @@
 # Line 1
 # Line 2
 # Line 3
 # Line 4
 # Line 5
 # Line 6
 # Line 7
 # Line 8
 # Line 9
 def add(a, b):
-    return a - b
+    return a + b
+    dangerous_exec()
 # Line 12
 # Line 13
 # Line 14
 # Line 15
""",
    )

    valid_review = {
        "risk": "high",
        "flags": [
            {
                "file": "src/calc.py",
                "start_line": 11,
                "end_line": 12,
                "reason": "Dangerous call to exec",
                "severity": "high",
            }
        ],
        "summary": "Found dangerous execution call.",
    }
    fake_remote.answers = [json.dumps(valid_review)]

    code, out, _err = _run(["review", run_id], capsys)
    assert code == 0

    review_data = json.loads((run_dir / "review.json").read_text(encoding="utf-8"))
    assert review_data["risk"] == "high"
    assert len(review_data["flags"]) == 1

    # Now run show --diff --only-flagged
    code, out, _err = _run(["show", run_id, "--diff", "--only-flagged"], capsys)
    assert code == 0
    # Must show flagged context lines around lines 11-12
    assert "dangerous_exec" in out
    # Context should not show the very far top or bottom lines if outside +-5 context
    assert "Line 1\n" not in out
    assert "Line 6" in out or "Line 7" in out


# --- 3. Plan Expand ----------------------------------------------------------------------


def test_plan_expand_retries_twice_on_invalid_yaml_then_fails_with_clear_error(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_remote: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Acceptance criterion: plan expand retries 2 times (3 attempts total) on invalid YAML,
    then fails with clear error and exit code 2."""
    repo = _setup_repo(make_repo, tmp_path, monkeypatch, config=CONFIG_LOCAL_AND_REMOTE)
    draft = repo / "draft.md"
    draft.write_text("# Plan: Add docstrings to all modules\n", encoding="utf-8")
    out_yaml = repo / "batch.yaml"

    # All 3 attempts return invalid YAML
    fake_remote.answers = [
        "not a valid yaml: [: invalid",
        "tasks: [unclosed list",
        "tasks: invalid_type",
    ]

    code, _out, err = _run(["plan", "expand", str(draft), "-o", str(out_yaml)], capsys)
    assert code == 2  # UsageError exit code

    # Initial attempt + 2 retries = 3 calls
    assert len(fake_remote.calls) == 3
    # Output file was NOT created
    assert not out_yaml.exists()
    assert "plan" in err.lower() or "yaml" in err.lower()


def test_plan_expand_valid_yaml_writes_output_and_does_not_execute(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_remote: FakeWorker,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Acceptance criterion: valid output is written to file and NOT executed.
    Also warns if an edit task has no verifiers."""
    repo = _setup_repo(make_repo, tmp_path, monkeypatch, config=CONFIG_LOCAL_AND_REMOTE)
    draft = repo / "draft.md"
    draft.write_text("# Plan: Add docstrings\n", encoding="utf-8")
    out_yaml = repo / "batch.yaml"

    valid_batch_yaml = """\
tasks:
  - id: add-docstrings
    kind: edit
    prompt: Add docstrings to src/util.py
    context:
      files: [src/util.py]
    verify: []
"""
    fake_remote.answers = [valid_batch_yaml]

    code, _out, err = _run(["plan", "expand", str(draft), "-o", str(out_yaml)], capsys)
    assert code == 0

    # Output file written
    assert out_yaml.is_file()
    saved = out_yaml.read_text(encoding="utf-8")
    assert "add-docstrings" in saved

    # CRITICAL: the batch is NOT executed! (fake_ollama worker has 0 calls)
    assert len(fake_ollama.calls) == 0

    # Warning for edit task without verifiers
    assert t("plan.warning.no_verifiers", task_id="add-docstrings") in err
    # The written file is a batch file that ``orkestra batch`` loads as it is.
    loaded = batch.load_batch(out_yaml)
    assert [task.id for task in loaded.tasks] == ["add-docstrings"]


# --- 4. Cache clear clears map cache ----------------------------------------------------


def test_cache_clear_also_removes_map_cache(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """cache clear removes both response cache and project map cache."""
    repo = _setup_repo(make_repo, tmp_path, monkeypatch, config=CONFIG_LOCAL_AND_REMOTE)

    # Generate map cache
    code, _out, _err = _run(["map"], capsys)
    assert code == 0
    map_cache_dir = repo / ".orkestra" / "cache" / "map"
    assert map_cache_dir.is_dir()
    assert list(map_cache_dir.glob("*.json"))

    # Now clear cache
    code, _out, _err = _run(["cache", "clear"], capsys)
    assert code == 0

    # Map cache files are cleared
    assert not list(map_cache_dir.glob("*.json"))


# --- 5. Automatic Review on Edit --------------------------------------------------------


def test_review_auto_triggers_review_on_successful_edit(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Acceptance criterion: when review.auto: true, a successful edit with changes
    automatically triggers review and attaches review metadata to ResultEnvelope."""
    repo = _setup_repo(
        make_repo,
        tmp_path,
        monkeypatch,
        config="""\
version: 1
review:
  auto: true
  tier: 1
providers:
  ollama:
    type: ollama
    base_url: http://ollama.test:11434
    local: true
    concurrency: 4
    models:
      - id: coder
        tier: 1
        edit_format: whole
""",
        files={"src/calc.py": "def add(a, b):\n    return 0\n"},
    )
    edit_answer = json.dumps(
        {
            "files": [{"path": "src/calc.py", "content": "def add(a, b):\n    return a + b\n"}],
            "note": "fixed add",
        }
    )
    review_answer = json.dumps({"risk": "low", "flags": [], "summary": "Fix looks clean"})
    fake_ollama.answers = [edit_answer, review_answer]

    task_file = repo / "task.yaml"
    task_file.write_text(
        """\
id: fix-add
kind: edit
prompt: Fix add function
context:
  files: [src/calc.py]
verify: []
""",
        encoding="utf-8",
    )

    code, out, err = _run(["run", str(task_file), "--json"], capsys)
    assert code == 0, f"out: {out}\nerr: {err}"
    envelope = json.loads(out)
    assert envelope["status"] == "ok"
    assert envelope["envelope_version"] == 4
    assert envelope["review"] is not None
    assert envelope["review"]["risk"] == "low"
    assert envelope["review"]["flags_count"] == 0


# --- 6. Code review of PR #17 (D-062) ---------------------------------------------------

SECRET = "sk-or-v1-TESTKEY000000000000000000000000"  # the fake ROUTER_KEY of _setup_repo


def test_one_failed_summary_does_not_stop_the_map(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A provider error on one file skips that file only, with its own warning."""
    repo = _setup_repo(
        make_repo,
        tmp_path,
        monkeypatch,
        files={"src/a.py": "A = 1\n", "src/b.py": "B = 2\n", "src/c.py": "C = 3\n"},
    )
    fake_ollama.answers = [ProviderTransient("connection reset"), "Holds B.", "Holds C."]

    code, _out, err = _run(["map"], capsys)
    assert code == 0
    assert len(fake_ollama.calls) == 3
    content = (repo / ".orkestra" / "MAP.md").read_text(encoding="utf-8")
    assert "Holds B." in content
    assert "Holds C." in content
    assert t("map.warning.summary_failed", path="src/a.py", reason="connection reset") in err
    assert t("map.warning.no_local_provider") not in err


def test_chief_call_raises_the_provider_error_and_a_success_resets_the_failure_count(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
) -> None:
    """The real error comes out (not "no provider"), and a success ends the failure streak:
    failures spread between successes must not open the circuit."""
    repo = _setup_repo(make_repo, tmp_path, monkeypatch)
    config = load_config(cwd=repo, environ={}).config
    fake_ollama.answers = [
        ProviderTransient("first"),
        "fine",
        ProviderTransient("second"),
        ProviderTransient("third"),
    ]

    async def ask() -> str:
        answer, _label = await call.query_chief_model(
            config, tier=1, system="s", user="u", privacy="local_only"
        )
        return answer

    with pytest.raises(ProviderTransient, match="first"):
        asyncio.run(ask())
    assert asyncio.run(ask()) == "fine"
    for expected in ("second", "third"):
        with pytest.raises(ProviderTransient, match=expected):
            asyncio.run(ask())
    with closing(db.connect()) as conn:
        state = health.get(conn, "ollama")
    assert state.consecutive_failures == 2
    assert not state.is_open(db.local_now())


def test_map_skips_only_the_file_that_holds_a_secret(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_remote: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``map.privacy: normal`` with only a remote model: the file with a key is not sent, and
    the files after it still are."""
    repo = _setup_repo(
        make_repo,
        tmp_path,
        monkeypatch,
        config=CONFIG_REMOTE_ONLY + "map:\n  privacy: normal\n",
        files={
            "src/a_leak.py": f'KEY = "{SECRET}"\n',
            "src/b_clean.py": "def ok() -> int:\n    return 1\n",
        },
    )
    fake_remote.default_answer = "Clean helper."

    code, _out, err = _run(["map"], capsys)
    assert code == 0
    assert len(fake_remote.calls) == 1
    assert "b_clean.py" in fake_remote.calls[0].user
    assert all(SECRET not in c.user for c in fake_remote.calls)
    assert t("map.warning.secret_skipped", path="src/a_leak.py") in err
    content = (repo / ".orkestra" / "MAP.md").read_text(encoding="utf-8")
    assert "Clean helper." in content


def test_an_empty_summary_is_not_cached(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _setup_repo(make_repo, tmp_path, monkeypatch)  # README.md, src/util.py
    fake_ollama.answers = ["   ", "Adds numbers."]

    code, _out, err = _run(["map"], capsys)
    assert code == 0
    assert t("map.warning.empty_summary", path="README.md") in err
    entries = [p for p in (repo / ".orkestra" / "cache" / "map").glob("*.json")]
    assert len([p for p in entries if p.name != repomap.INDEX_FILE_NAME]) == 1

    fake_ollama.calls.clear()
    code, _out, _err = _run(["map"], capsys)
    assert code == 0
    assert len(fake_ollama.calls) == 1  # README.md is asked again, util.py is cached
    assert "README.md" in fake_ollama.calls[0].user


def test_map_max_files_says_the_map_was_cut(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _setup_repo(make_repo, tmp_path, monkeypatch)  # README.md, src/util.py

    code, _out, err = _run(["map", "--max-files", "1"], capsys)
    assert code == 0
    assert t("map.warning.truncated", max=1) in err
    content = (repo / ".orkestra" / "MAP.md").read_text(encoding="utf-8")
    assert "README.md" in content
    assert "util.py" not in content

    code, _out, err = _run(["map", "--max-files", "2"], capsys)
    assert code == 0
    assert t("map.warning.truncated", max=2) not in err


def test_mapping_some_paths_keeps_the_rest_of_the_map(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _setup_repo(make_repo, tmp_path, monkeypatch)  # README.md, src/util.py
    fake_ollama.answers = ["The readme.", "Adds numbers."]
    assert _run(["map"], capsys)[0] == 0

    (repo / "src" / "util.py").write_text(
        "def sub(a: int, b: int) -> int:\n    return a - b\n", encoding="utf-8"
    )
    fake_ollama.calls.clear()
    fake_ollama.answers = ["Subtracts numbers."]
    code, out, _err = _run(["map", "src/util.py", "--json"], capsys)
    assert code == 0
    assert len(fake_ollama.calls) == 1
    data = json.loads(out)
    assert [f["path"] for f in data["files"]] == ["src/util.py"]
    assert data["map_files"] == 2

    content = (repo / ".orkestra" / "MAP.md").read_text(encoding="utf-8")
    assert "The readme." in content  # kept from the first run
    assert "Subtracts numbers." in content
    assert "Adds numbers." not in content
    assert "def sub(" in content


def test_map_paths_are_relative_to_the_current_directory(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _setup_repo(
        make_repo,
        tmp_path,
        monkeypatch,
        files={"pkg/core/x.py": "X = 1\n", "core/y.py": "Y = 2\n"},
    )
    monkeypatch.chdir(repo / "pkg")

    code, out, _err = _run(["map", "core", "--json"], capsys)
    assert code == 0
    assert [f["path"] for f in json.loads(out)["files"]] == ["pkg/core/x.py"]
    assert (repo / ".orkestra" / "MAP.md").is_file()


@pytest.mark.parametrize("where", ["outside", "missing"])
def test_map_refuses_paths_outside_the_project_or_missing(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
    where: str,
) -> None:
    _setup_repo(make_repo, tmp_path, monkeypatch)
    outside = tmp_path / "elsewhere.py"
    outside.write_text("Z = 0\n", encoding="utf-8")
    target = str(outside) if where == "outside" else "src/nope.py"

    code, _out, err = _run(["map", target], capsys)
    assert code == 2
    assert "Traceback" not in err
    key = "map.error.outside_root" if where == "outside" else "map.error.not_found"
    assert t(key, path=str(Path(target))) in err
    assert len(fake_ollama.calls) == 0


def test_cache_clear_from_a_subdirectory_clears_the_project_map_cache(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _setup_repo(make_repo, tmp_path, monkeypatch)
    assert _run(["map"], capsys)[0] == 0
    map_cache_dir = repo / ".orkestra" / "cache" / "map"
    assert list(map_cache_dir.glob("*.json"))

    monkeypatch.chdir(repo / "src")
    assert _run(["cache", "clear"], capsys)[0] == 0
    assert not list(map_cache_dir.glob("*.json"))


def test_map_reports_progress_for_each_file(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
) -> None:
    repo = _setup_repo(make_repo, tmp_path, monkeypatch)  # README.md, src/util.py
    config = load_config(cwd=repo, environ={}).config
    seen: list[tuple[int, int, str]] = []

    def on_progress(done: int, total: int, path: str) -> None:
        seen.append((done, total, path))

    asyncio.run(repomap.generate_repomap(repo, None, config, on_progress=on_progress))
    assert seen == [(1, 2, "README.md"), (2, 2, "src/util.py")]


def _git_patch(*files: tuple[str, int]) -> str:
    parts: list[str] = []
    for name, lines in files:
        body = "".join(f"+line {i}\n" for i in range(1, lines + 1))
        parts.append(
            f"diff --git a/{name} b/{name}\nnew file mode 100644\n--- /dev/null\n"
            f"+++ b/{name}\n@@ -0,0 +1,{lines} @@\n{body}"
        )
    return "".join(parts)


_LOW = json.dumps({"risk": "low", "flags": [], "summary": "fine"})


def test_a_large_single_file_diff_is_reviewed_in_one_call(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_remote: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_repo(make_repo, tmp_path, monkeypatch)
    run_id = "20261111-130000-e5f6"
    _create_fake_run(run_id, patch=_git_patch(("src/big.py", 450)))
    fake_remote.answers = [_LOW]

    code, _out, _err = _run(["review", run_id], capsys)
    assert code == 0
    assert len(fake_remote.calls) == 1
    assert "diff --git a/src/big.py b/src/big.py" in fake_remote.calls[0].user


def test_a_large_diff_is_reviewed_file_by_file_with_each_header(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_remote: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_repo(make_repo, tmp_path, monkeypatch)
    run_id = "20261111-130100-a7b8"
    run_dir = _create_fake_run(run_id, patch=_git_patch(("src/one.py", 250), ("src/two.py", 250)))
    medium = json.dumps(
        {
            "risk": "medium",
            "flags": [{"file": "src/two.py", "start_line": 3, "end_line": 4, "reason": "r"}],
            "summary": "hmm",
        }
    )
    fake_remote.answers = [_LOW, medium]

    code, _out, _err = _run(["review", run_id], capsys)
    assert code == 0
    assert len(fake_remote.calls) == 2
    assert "diff --git a/src/one.py" in fake_remote.calls[0].user
    assert "src/two.py" not in fake_remote.calls[0].user
    assert "diff --git a/src/two.py" in fake_remote.calls[1].user
    data = json.loads((run_dir / "review.json").read_text(encoding="utf-8"))
    assert data["risk"] == "medium"
    assert len(data["flags"]) == 1


def test_review_reports_the_provider_error_instead_of_a_fake_review(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_remote: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_repo(make_repo, tmp_path, monkeypatch)
    run_id = "20261111-130200-c9d0"
    run_dir = _create_fake_run(run_id)
    fake_remote.answers = [ProviderAuthError("the key was rejected")]

    code, _out, err = _run(["review", run_id], capsys)
    assert code == int(ExitCode.NO_PROVIDER)
    assert "the key was rejected" in err
    assert not (run_dir / "review.json").exists()


def test_review_masks_configured_secrets_in_the_diff(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_remote: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_repo(make_repo, tmp_path, monkeypatch)
    run_id = "20261111-130300-e1f2"
    patch = (
        "diff --git a/src/cfg.py b/src/cfg.py\n--- a/src/cfg.py\n+++ b/src/cfg.py\n"
        f'@@ -1 +1 @@\n-KEY = ""\n+KEY = "{SECRET}"\n'
    )
    _create_fake_run(run_id, patch=patch)
    fake_remote.answers = [_LOW]

    code, _out, _err = _run(["review", run_id], capsys)
    assert code == 0
    assert len(fake_remote.calls) == 1
    assert SECRET not in fake_remote.calls[0].user


def test_only_flagged_with_an_unreadable_review_is_a_translated_usage_error(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_repo(make_repo, tmp_path, monkeypatch)
    run_id = "20261111-130400-a3b4"
    run_dir = _create_fake_run(run_id)
    (run_dir / "review.json").write_text("{broken", encoding="utf-8")

    code, _out, err = _run(["--lang", "tr", "show", run_id, "--diff", "--only-flagged"], capsys)
    assert code == 2
    assert "inceleme dosyası okunamadı" in err


def test_plan_expand_reports_a_routing_error_without_retrying(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No tier-2 model: the router's error and exit code, not "invalid YAML after 3 tries"."""
    repo = _setup_repo(
        make_repo,
        tmp_path,
        monkeypatch,
        config=CONFIG_LOCAL_AND_REMOTE.split("  router:")[0],  # only the tier-1 Ollama
    )
    draft = repo / "draft.md"
    draft.write_text("# Plan\n", encoding="utf-8")

    code, _out, err = _run(["plan", "expand", str(draft), "-o", "batch.yaml"], capsys)
    assert code == int(ExitCode.NO_PROVIDER)
    assert len(fake_ollama.calls) == 0
    assert t("select.none") in err
    assert not (repo / "batch.yaml").exists()


AUTO_REVIEW_CONFIG = """\
version: 1
review:
  auto: true
  tier: 1
providers:
  ollama:
    type: ollama
    base_url: http://ollama.test:11434
    local: true
    concurrency: 4
    models:
      - id: coder
        tier: 1
        edit_format: whole
"""

_EDIT_TASK = """\
id: fix-add
kind: edit
prompt: Fix add function
context:
  files: [src/calc.py]
verify: []
"""


def _edit_answer() -> str:
    return json.dumps(
        {"files": [{"path": "src/calc.py", "content": "def add(a, b):\n    return a + b\n"}]}
    )


def test_review_auto_shares_the_run_slots_and_counts_in_its_duration(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _setup_repo(
        make_repo,
        tmp_path,
        monkeypatch,
        config=AUTO_REVIEW_CONFIG,
        files={"src/calc.py": "def add(a, b):\n    return 0\n"},
    )
    seen: dict[str, Any] = {}

    async def fake_review_run(run_id: str, config: Any, **kwargs: Any) -> review.ReviewReport:
        seen.update(kwargs)
        await asyncio.sleep(0.3)
        return review.ReviewReport(risk="medium", summary="looked")

    monkeypatch.setattr(review, "review_run", fake_review_run)
    fake_ollama.answers = [_edit_answer()]
    (repo / "task.yaml").write_text(_EDIT_TASK, encoding="utf-8")

    code, out, err = _run(["run", "task.yaml", "--json"], capsys)
    assert code == 0, err
    envelope = json.loads(out)
    assert envelope["review"] == {"risk": "medium", "flags_count": 0}
    assert envelope["duration_s"] >= 0.3
    assert isinstance(seen["slots"], ProviderSlots)
    assert seen["conn"] is not None


def test_a_failed_auto_review_leaves_the_run_ok_without_a_review(
    make_repo: MakeRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: FakeWorker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _setup_repo(
        make_repo,
        tmp_path,
        monkeypatch,
        config=AUTO_REVIEW_CONFIG,
        files={"src/calc.py": "def add(a, b):\n    return 0\n"},
    )
    fake_ollama.answers = [_edit_answer(), ProviderTransient("review model fell over")]
    (repo / "task.yaml").write_text(_EDIT_TASK, encoding="utf-8")

    code, out, err = _run(["run", "task.yaml", "--json"], capsys)
    assert code == 0, err
    envelope = json.loads(out)
    assert envelope["status"] == "ok"
    assert envelope["review"] is None
