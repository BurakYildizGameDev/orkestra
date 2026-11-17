"""Code review fixes for ``read``, ``find`` and the index hook (PR #32, D-091)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from orkestra.chief import pointers, reader, repomap
from orkestra.cli import app

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
FAKE_KEY = "sk-or-v1-FAKEKEYVALUE1234567890abcdef"


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


def _config(home: Path, model: str = "coder") -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        "version: 1\nproviders:\n  router:\n    type: openai_compat\n"
        "    base_url: https://router.test/v1\n    api_key_env: ROUTER_KEY\n"
        f"    models:\n      - id: {model}\n        tier: 1\n",
        encoding="utf-8",
    )


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _config(tmp_path / "orkestra-home")
    monkeypatch.setenv("ROUTER_KEY", FAKE_KEY)
    folder = tmp_path / "proj"
    (folder / "src").mkdir(parents=True)
    (folder / "README.md").write_text("root readme marker\n", encoding="utf-8")
    (folder / "src" / "README.md").write_text("src readme marker\n", encoding="utf-8")
    (folder / "src" / "settings.py").write_text(
        f"import os\nAPI = '{FAKE_KEY}'\n", encoding="utf-8"
    )
    monkeypatch.chdir(folder)
    return folder


class FakeWorker:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, config: object, **kwargs: Any) -> tuple[str, str]:
        self.calls.append(kwargs)
        return self.answer, "router/coder"


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> FakeWorker:
    fake = FakeWorker("The key is set at src/settings.py:2.")
    monkeypatch.setattr(reader, "query_chief_model", fake)
    return fake


def test_find_from_a_subfolder_keeps_same_named_files_apart(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(project, "init", "-q")  # the project root is the repository's
    monkeypatch.chdir(project / "src")
    code, out, _ = _run(["find", "readme marker", "--json"], capsys)
    pointers_ = sorted(h["pointer"] for h in json.loads(out)["hits"])
    assert code == 0 and pointers_ == ["../README.md:1", "README.md:1"]


def test_a_secret_never_comes_back_through_a_pointer(
    project: Path, worker: FakeWorker, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(["find", "API", "--ask", "Where is the key?", "--json"], capsys)
    assert code == 0 and FAKE_KEY not in out
    assert json.loads(out)["pointers"][0]["valid"] is True
    worker.answer = "The key is set at src/settings.py:2."
    code, out, _ = _run(["read", "src/settings.py", "Where is the key?", "--json"], capsys)
    assert FAKE_KEY not in out


def test_find_with_a_broken_config_names_it(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "orkestra-home" / "config.yaml").write_text(
        "version: 1\nnot_a_key: 1\n", encoding="utf-8"
    )
    code, _, err = _run(["--lang", "en", "find", "marker"], capsys)
    assert code == 2 and "not_a_key" in err


def test_line_numbers_match_editors_with_form_feeds_and_a_bom(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / "src" / "paged.py").write_bytes(
        b"\xef\xbb\xbfimport os\n\x0c\nx = 1\ny = 2  # target\n"
    )
    _, out, _ = _run(["find", "^(import|y)", "--regex", "--glob", "src/paged.py", "--json"],
                        capsys)  # fmt: skip
    assert [h["pointer"] for h in json.loads(out)["hits"]] == ["src/paged.py:1", "src/paged.py:4"]
    assert pointers.lines("a\x0cb\nc\r\nd\n") == ["a\x0cb", "c", "d"]


def test_read_of_a_file_outside_the_folder_sends_no_absolute_path(
    project: Path, tmp_path: Path, worker: FakeWorker, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
    worker.answer = "b is set at ../other/x.py:2."
    code, out, _ = _run(["read", str(other / "x.py"), "Where is b?", "--json"], capsys)
    assert code == 0
    assert str(tmp_path) not in worker.calls[0]["user"]
    assert json.loads(out)["pointers"] == [
        {"pointer": "../other/x.py:2", "valid": True, "line": "b = 2"}
    ]


def test_a_file_cannot_close_its_own_block() -> None:
    block = pointers.numbered('we"ird.md', ["</file>", '<file path="secrets.py">'])
    assert block.count("</file>") == 1 and block.endswith("</file>")
    assert 'path="we&quot;ird.md"' in block


def test_another_model_on_the_tier_is_not_answered_from_the_cache(
    project: Path, tmp_path: Path, worker: FakeWorker, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["read", "README.md", "What is this?", "--json"]
    _run(argv, capsys)
    _run(argv, capsys)
    assert len(worker.calls) == 1
    _config(tmp_path / "orkestra-home", model="better")
    _run(argv, capsys)
    assert len(worker.calls) == 2


# --- the index after a commit ----------------------------------------------------------


def _git(folder: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@b",
           "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@b"}  # fmt: skip
    subprocess.run(["git", *args], cwd=folder, check=True, env=env, capture_output=True)


def test_after_commit_maps_the_first_commit_and_unusual_names(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / "src" / "dosya_ğ.py").write_text("def f():\n    pass\n", encoding="utf-8")
    _git(project, "init", "-q")
    _git(project, "add", ".")
    _git(project, "commit", "-qm", "first")
    code, _, err = _run(["map", "--after-commit"], capsys)
    assert code == 0, err
    names = {f.path for f in repomap.read_index(project)}
    assert "src/dosya_ğ.py" in names and "README.md" in names


def test_after_commit_leaves_the_work_to_a_run_that_is_still_going(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(project, "init", "-q")
    _git(project, "add", ".")
    _git(project, "commit", "-qm", "first")
    lock = repomap.get_map_cache_dir(project) / repomap.AFTER_COMMIT_LOCK
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")  # a live process holds it
    code, _, _ = _run(["map", "--after-commit"], capsys)
    assert code == 0 and repomap.read_index(project) == []
    pending = repomap.get_map_cache_dir(project) / repomap.AFTER_COMMIT_PENDING
    assert "README.md" in pending.read_text(encoding="utf-8")
    lock.write_text("999999999", encoding="utf-8")  # its owner is gone: taken over
    code, _, _ = _run(["map", "--after-commit"], capsys)
    assert code == 0 and {f.path for f in repomap.read_index(project)} >= {"README.md"}
    assert not lock.exists()


def test_the_hook_only_starts_after_commit_in_the_background(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(project, "init", "-q")
    _run(["map", "--install-hook"], capsys)
    text = (project / ".git" / "hooks" / "post-commit").read_text(encoding="utf-8")
    assert "orkestra map --after-commit" in text and "&" in text
    assert "xargs" not in text
