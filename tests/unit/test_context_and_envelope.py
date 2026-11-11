from __future__ import annotations

import json
from pathlib import Path

import pytest

from orkestra.envelope import (
    ENVELOPE_VERSION,
    ResultEnvelope,
    human_summary,
    summarize_text,
    to_json,
)
from orkestra.errors import UsageError
from orkestra.tasks.context import collect_context, render_context
from orkestra.tasks.prompts import build_ask_messages
from orkestra.tasks.runner import new_run_id

# --- context ---------------------------------------------------------------------------


def test_collect_and_render(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "util.py").write_bytes(b"def f():\n    return 1\n")
    ctx = collect_context([Path("src/util.py")], max_bytes=1000, cwd=tmp_path)
    assert [f.display for f in ctx.files] == ["src/util.py"]
    assert render_context(ctx) == '<file path="src/util.py">\ndef f():\n    return 1\n</file>'


def test_render_adds_newline_before_closing_tag(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"no newline")
    ctx = collect_context([Path("a.txt")], max_bytes=1000, cwd=tmp_path)
    assert render_context(ctx) == '<file path="a.txt">\nno newline\n</file>'


def test_binary_file_skipped(tmp_path: Path) -> None:
    (tmp_path / "img.png").write_bytes(b"\x89PNG\x00\x00data")
    (tmp_path / "a.txt").write_bytes(b"text")
    ctx = collect_context([Path("img.png"), Path("a.txt")], max_bytes=1000, cwd=tmp_path)
    assert ctx.skipped_binary == ("img.png",)
    assert [f.display for f in ctx.files] == ["a.txt"]


def test_size_limit_is_error_not_truncation(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_bytes(b"x" * 600)
    (tmp_path / "small.txt").write_bytes(b"y" * 500)
    with pytest.raises(UsageError) as exc_info:
        collect_context([Path("small.txt"), Path("big.txt")], max_bytes=1000, cwd=tmp_path)
    assert "1100" in exc_info.value.message
    assert exc_info.value.details[0].startswith("big.txt: 600")


def test_missing_context_file(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        collect_context([Path("nope.py")], max_bytes=1000, cwd=tmp_path)


def test_duplicate_paths_once(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"a")
    ctx = collect_context([Path("a.txt"), tmp_path / "a.txt"], max_bytes=1000, cwd=tmp_path)
    assert len(ctx.files) == 1


def test_utf8_bom_and_bad_bytes(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"\xef\xbb\xbfhello \xff")
    ctx = collect_context([Path("a.txt")], max_bytes=1000, cwd=tmp_path)
    assert ctx.files[0].text == "hello �"


def test_ask_messages_are_english_and_include_context(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"x = 1\n")
    ctx = collect_context([Path("a.py")], max_bytes=1000, cwd=tmp_path)
    system, user = build_ask_messages("Explain", ctx, {"type": "object"})
    assert "CANNOT_DO" in system
    assert '<file path="a.py">' in user
    assert user.index("Context files") < user.index("Task:\nExplain")
    assert '"type": "object"' in user


# --- envelope --------------------------------------------------------------------------


def test_run_id_format() -> None:
    from datetime import datetime

    assert new_run_id(datetime(2026, 11, 7, 10, 15, 0), "a1b2") == "20261107-101500-a1b2"
    assert len(new_run_id()) == len("20261107-101500-a1b2")


def test_summary_short_text_unchanged() -> None:
    assert summarize_text("short  answer\n", "/x/output.md") == "short answer"


def test_summary_cut_at_word_boundary() -> None:
    text = "word " * 200
    summary = summarize_text(text, "/x/output.md", limit=20)
    assert summary.startswith("word word word word…")
    assert "/x/output.md" in summary


def test_envelope_json_shape() -> None:
    env = ResultEnvelope(run_id="r", task_id="ask", status="ok", provider="p", model="m", tier=1)
    doc = json.loads(to_json(env))
    assert doc["envelope_version"] == ENVELOPE_VERSION
    assert set(doc) == {
        "envelope_version", "run_id", "task_id", "status", "provider", "model", "tier",
        "edit_format", "attempts", "escalations", "failovers", "summary", "verification",
        "changes", "output_path", "usage", "duration_s", "cached", "review", "error",
    }  # fmt: skip
    assert doc["usage"] == {"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}


def test_a_stored_version_2_envelope_still_loads() -> None:
    old = {"envelope_version": 2, "run_id": "r", "task_id": "t", "status": "ok"}
    assert ResultEnvelope.model_validate(old).edit_format is None


def test_a_stored_version_3_envelope_still_loads() -> None:
    old = {
        "envelope_version": 3,
        "run_id": "r",
        "task_id": "t",
        "status": "ok",
        "provider": "p",
        "model": "m",
        "tier": 1,
    }
    loaded = ResultEnvelope.model_validate(old)
    assert loaded.envelope_version == 3
    assert loaded.review is None


def test_human_summary_mentions_error() -> None:
    env = ResultEnvelope(run_id="r", task_id="ask", status="error", error="boom")
    assert "Error: boom" in human_summary(env)


# --- code review fixes (Faz 2, PR #3) ---------------------------------------------------


def test_oversized_context_is_rejected_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "huge.txt").write_bytes(b"x" * 5000)

    def never(_: Path) -> bytes:
        raise AssertionError("read the whole file before the size check")

    monkeypatch.setattr(Path, "read_bytes", never)
    with pytest.raises(UsageError) as exc_info:
        collect_context([Path("huge.txt")], max_bytes=1000, cwd=tmp_path)
    assert exc_info.value.details[0].startswith("huge.txt: 5000")


def test_binary_files_do_not_count_towards_the_limit(tmp_path: Path) -> None:
    (tmp_path / "img.png").write_bytes(b"\x89PNG\x00" + b"x" * 5000)
    (tmp_path / "a.txt").write_bytes(b"text")
    ctx = collect_context([Path("img.png"), Path("a.txt")], max_bytes=1000, cwd=tmp_path)
    assert ctx.skipped_binary == ("img.png",)


def test_render_escapes_path_and_closing_tag(tmp_path: Path) -> None:
    (tmp_path / "a&b.txt").write_bytes(b"before </file> after\n")  # '"' is invalid on Windows
    ctx = collect_context([Path("a&b.txt")], max_bytes=1000, cwd=tmp_path)
    rendered = render_context(ctx)
    assert rendered.startswith('<file path="a&amp;b.txt">\n')
    assert rendered.count("</file>") == 1
    assert "before <\\/file> after" in rendered


def test_verification_words_are_translated() -> None:
    from orkestra import i18n
    from orkestra.envelope import VerificationResult

    i18n.set_language("tr")
    envelope = ResultEnvelope(
        run_id="r", task_id="t", status="failed",
        verification=[VerificationResult(type="json_schema", ok=False, detail="x")],
    )  # fmt: skip
    text = human_summary(envelope)
    assert "FAIL" not in text
    assert "BAŞARISIZ" in text


# --- ignore files and globs (Faz 5a) ---------------------------------------------------


def test_orkestraignore_excludes_even_explicit_files(tmp_path: Path) -> None:
    (tmp_path / ".orkestraignore").write_text("secrets/\n", encoding="utf-8")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "k.txt").write_text("k", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    ctx = collect_context(
        [Path("secrets/k.txt"), Path("a.txt")], max_bytes=1000, cwd=tmp_path,
        ignore_file=".orkestraignore",
    )  # fmt: skip
    assert [f.display for f in ctx.files] == ["a.txt"]
    assert ctx.skipped_ignored == (("secrets/k.txt", ".orkestraignore"),)


def test_globs_skip_gitignored_files_and_git_dir(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
    for name in ("src/a.py", "src/b.py", "build/c.py", ".git/hooks/d.py"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x", encoding="utf-8")
    ctx = collect_context([], globs=["**/*.py"], max_bytes=1000, cwd=tmp_path)
    assert [f.display for f in ctx.files] == ["src/a.py", "src/b.py"]
    assert ctx.skipped_ignored == ()  # ignored directories are pruned, not listed file by file


def test_absolute_glob_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        collect_context([], globs=[str(tmp_path / "*.py")], max_bytes=1000, cwd=tmp_path)


def test_glob_walk_prunes_ignored_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".gitignore").write_text(".venv/\nsrc/gen.py\n", encoding="utf-8")
    for name in ("src/a.py", "src/gen.py", ".venv/lib/x.py"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x", encoding="utf-8")
    visited: list[str] = []
    real_walk = __import__("os").walk

    def spy(top: object, *args: object, **kwargs: object) -> object:
        for entry in real_walk(top, *args, **kwargs):  # type: ignore[arg-type]
            visited.append(Path(entry[0]).name)
            yield entry

    monkeypatch.setattr("orkestra.tasks.context.os.walk", spy)
    ctx = collect_context([], globs=["**/*.py"], max_bytes=1000, cwd=tmp_path)
    assert [f.display for f in ctx.files] == ["src/a.py"]
    assert ctx.skipped_ignored == (("src/gen.py", ".gitignore"),)
    assert ".venv" not in visited and "lib" not in visited


@pytest.mark.parametrize(
    ("pattern", "path", "matches"),
    [
        ("notes/*.txt", "notes/a.txt", True),
        ("notes/*.txt", "notes/sub/a.txt", False),  # like glob, unlike .gitignore
        ("**/*.py", "a.py", True),
        ("**/*.py", "x/y/a.py", True),
        ("src/**", "src/a/b.c", True),
        ("file?.md", "file1.md", True),
        ("file?.md", "file10.md", False),
        ("[!a]*.txt", "b.txt", True),
        ("[!a]*.txt", "a.txt", False),
        ("*.py", "sub/a.py", False),
    ],
)
def test_glob_semantics(pattern: str, path: str, matches: bool) -> None:
    from orkestra.tasks.context import glob_regex

    assert bool(glob_regex(pattern).match(path)) is matches
