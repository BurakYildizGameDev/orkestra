from __future__ import annotations

import json
from pathlib import Path

import pytest

from orkestra.envelope import ResultEnvelope, human_summary, summarize_text, to_json
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
    assert doc["envelope_version"] == 2
    assert set(doc) == {
        "envelope_version", "run_id", "task_id", "status", "provider", "model", "tier",
        "attempts", "escalations", "failovers", "summary", "verification", "changes", "output_path",
        "usage", "duration_s", "cached", "review", "error",
    }  # fmt: skip
    assert doc["usage"] == {"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}


def test_human_summary_mentions_error() -> None:
    env = ResultEnvelope(run_id="r", task_id="ask", status="error", error="boom")
    assert "Error: boom" in human_summary(env)
