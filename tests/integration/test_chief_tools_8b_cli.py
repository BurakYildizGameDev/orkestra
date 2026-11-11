"""Faz 8b: repomap, review, and plan expand, end to end (Mimari §19)."""

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
from orkestra.envelope import ENVELOPE_VERSION
from orkestra.providers.base import CompletionRequest, CompletionResult, Usage
from orkestra.providers.ollama import OllamaChat
from orkestra.providers.openai_compat import OpenAICompatChat
from orkestra.state import consent, db

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
        self.answers: list[str] = []
        self.default_answer: str = "A fine summary."

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        self.calls.append(req)
        text = self.answers.pop(0) if self.answers else self.default_answer
        return CompletionResult(text, Usage(40, 12, 0.0), "stop")


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
    assert "verify" in err.lower() or "verifier" in err.lower() or "add-docstrings" in err


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
