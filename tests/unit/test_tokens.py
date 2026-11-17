"""``orkestra tokens``: where a Claude Code session's tokens go (Faz 13h), on fake transcripts."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from orkestra.chief import tokens
from orkestra.config.schema import TokenWeights
from orkestra.errors import UsageError

W = TokenWeights()  # input 1, output 5, cache write 1.25, cache read 0.1
LINES = ("y" * 39 + "\n") * 300  # 12 000 chars, 300 lines → ~3 000 tokens


def _usage(inp: int, write: int, read: int, out: int) -> dict[str, Any]:
    return {"input_tokens": inp, "cache_creation_input_tokens": write,
            "cache_read_input_tokens": read, "output_tokens": out}  # fmt: skip


def _assistant(msg_id: str, usage: dict[str, Any], *blocks: dict[str, Any]) -> dict[str, Any]:
    return {"type": "assistant", "version": "2.1.325", "isSidechain": False,
            "timestamp": "2026-11-17T10:00:00Z",
            "message": {"id": msg_id, "role": "assistant", "content": list(blocks),
                        "usage": usage}}  # fmt: skip


def _use(call_id: str, name: str, **inp: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": inp}


def _result(call_id: str, content: Any) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": call_id, "content": content}]}}  # fmt: skip


def _write(path: Path, entries: list[dict[str, Any]], extra: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(e) for e in entries) + "\n" + extra
    path.write_bytes(text.encode("utf-8"))
    return path


def _session(home: Path, cwd: Path, name: str = "s1") -> Path:
    work = str(cwd)
    entries = [
        {"type": "user", "cwd": work, "message": {"role": "user", "content": "fix it"}},
        _assistant(
            "m1",
            _usage(10, 1000, 0, 50),
            {"type": "thinking", "thinking": "hmm"},
            _use("t1", "Read", file_path=str(cwd / "src" / "a.py")),
        ),
        _result("t1", LINES),
        # A streamed message is written once per block, each with the usage so far.
        _assistant("m2", _usage(5, 3000, 1000, 20), _use("t2", "Bash", command="uv run pytest")),
        _assistant("m2", _usage(5, 3000, 1000, 80), {"type": "text", "text": "running"}),
        _result("t2", "ok\n" * 10),
        _assistant(
            "m3",
            _usage(5, 100, 4000, 300),
            _use("t3", "Write", file_path=str(cwd / "b.py"), content="z" * 800),
        ),
        _result("t3", [{"type": "text", "text": "File created"}]),
        _assistant("m4", _usage(5, 250, 4100, 10), {"type": "text", "text": "done"}),
        {"type": "ai-title", "aiTitle": "unknown entries are skipped"},
    ]
    return _write(tokens.project_folder(cwd, home) / f"{name}.jsonl", entries)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "claude"


@pytest.fixture
def cwd(tmp_path: Path) -> Path:
    path = tmp_path / "work" / "proj"
    path.mkdir(parents=True)
    return path


# --- finding the transcripts -----------------------------------------------------------


def test_the_project_folder_is_claude_codes_name_for_the_path(tmp_path: Path) -> None:
    folder = tokens.project_folder(Path("C:/Users/x/My App.v2"), tmp_path)
    assert folder == tmp_path / "projects" / "C--Users-x-My-App-v2"


def test_claude_config_dir_is_honoured(tmp_path: Path) -> None:
    assert tokens.claude_home({"CLAUDE_CONFIG_DIR": str(tmp_path)}) == tmp_path
    assert tokens.claude_home({}) == Path.home() / ".claude"


def test_the_latest_session_is_the_default(home: Path, cwd: Path) -> None:
    old = _session(home, cwd, "old")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    new = _session(home, cwd, "new")
    folder = tokens.project_folder(cwd, home)
    assert tokens.select_sessions(folder) == [new]
    assert tokens.select_sessions(folder, session="ol") == [old]  # a prefix is enough
    since = datetime.now(UTC) - timedelta(days=1)
    assert sorted(tokens.select_sessions(folder, since=since)) == sorted([old, new])


def test_no_transcripts_is_a_usage_error(home: Path, cwd: Path) -> None:
    with pytest.raises(UsageError):
        tokens.select_sessions(tokens.project_folder(cwd, home))
    _session(home, cwd)
    with pytest.raises(UsageError):
        tokens.select_sessions(tokens.project_folder(cwd, home), session="nope")


# --- one session -----------------------------------------------------------------------


def test_usage_is_counted_once_per_request(home: Path, cwd: Path) -> None:
    session = tokens.read_session(_session(home, cwd))
    assert len(session.turns) == 4
    total = session.total
    assert (total.input, total.cache_write, total.cache_read, total.output) == (
        25,
        4350,
        9100,
        50 + 80 + 300 + 10,
    )
    assert total.weighted(W) == pytest.approx(25 + 4350 * 1.25 + 9100 * 0.1 + 440 * 5)
    assert session.versions == ["2.1.325"]


def test_each_tool_result_costs_its_cache_write_and_every_later_read(home: Path, cwd: Path) -> None:
    session = tokens.read_session(_session(home, cwd), calibrate=False)
    calls = {c.id: c for c in session.calls}
    read = calls["t1"]
    assert read.tool == "Read" and read.category == "read"
    assert read.tokens == 3000 and read.lines == 300
    assert read.rereads == 2  # written at turn 1, read at turns 2 and 3
    assert read.raw(W) == 3000 * 3
    assert read.weighted(W) == pytest.approx(3000 * 1.25 + 3000 * 0.1 * 2)
    assert read.weighted_if_lines(W, 10) == pytest.approx(100 * 1.25 + 100 * 0.1 * 2)
    assert calls["t2"].category == "command" and calls["t2"].rereads == 1
    write = calls["t3"]
    assert write.category == "write" and write.rereads == 0
    assert write.tokens >= 200  # what it wrote enters the context too


def test_labels_carry_no_personal_paths(home: Path, cwd: Path, tmp_path: Path) -> None:
    entries = [
        {"type": "user", "cwd": str(cwd), "message": {"role": "user", "content": "x"}},
        _assistant("m1", _usage(1, 1, 1, 1),
                   _use("a", "Read", file_path=str(cwd / "src" / "a.py")),
                   _use("b", "Read", file_path=str(tmp_path / "elsewhere" / "secret.txt")),
                   _use("c", "Bash", command=f"cat {Path.home() / 'notes.txt'} | head"),
                   _use("d", "Grep", pattern="def main"),
                   _use("e", "Agent", description="find the parser", prompt="long")),
        _assistant("m2", _usage(1, 1, 1, 1), {"type": "text", "text": "ok"}),
    ]  # fmt: skip
    path = _write(tokens.project_folder(cwd, home) / "s.jsonl", entries)
    labels = {c.id: c.label for c in tokens.read_session(path).calls}
    assert labels["a"] == "src/a.py"
    assert labels["b"] == "secret.txt"
    assert labels["c"].startswith("cat ~") and str(Path.home()) not in labels["c"]
    assert labels["d"] == "def main" and labels["e"] == "find the parser"


def test_a_compaction_ends_the_rereads(home: Path, cwd: Path) -> None:
    entries = [
        _assistant("m1", _usage(1, 10, 0, 1), _use("t1", "Read", file_path="a.py")),
        _result("t1", "x" * 400),
        _assistant("m2", _usage(1, 10, 10, 1), {"type": "text", "text": "a"}),
        {"type": "system", "subtype": "compact_boundary"},
        _assistant("m3", _usage(1, 10, 10, 1), {"type": "text", "text": "b"}),
        _assistant("m4", _usage(1, 10, 10, 1), {"type": "text", "text": "c"}),
    ]
    path = _write(tokens.project_folder(cwd, home) / "s.jsonl", entries)
    (call,) = tokens.read_session(path).calls
    assert call.rereads == 0  # written at turn 1, then the context was summarised
    assert tokens.read_session(path).compactions == 1


def test_broken_lines_are_skipped_and_counted(home: Path, cwd: Path) -> None:
    path = _session(home, cwd)
    with path.open("a", encoding="utf-8") as f:
        f.write("{not json\n")
    session = tokens.read_session(path)
    assert session.skipped_lines == 1 and len(session.turns) == 4


def test_subagents_are_counted_apart(home: Path, cwd: Path) -> None:
    path = _session(home, cwd)
    _write(path.with_suffix("") / "subagents" / "agent-1.jsonl",
           [_assistant("x1", _usage(3, 500, 200, 40), {"type": "text", "text": "r"})])  # fmt: skip
    session = tokens.read_session(path)
    assert session.subagents.runs == 1
    assert session.subagents.total.output == 40
    assert session.total.output == 440  # the main context is not mixed with it


def test_claudes_replies_and_later_messages_are_counted_apart(home: Path, cwd: Path) -> None:
    entries = [
        {"type": "user", "message": {"role": "user", "content": "first: part of the start"}},
        _assistant("m1", _usage(1, 100, 0, 10), {"type": "thinking", "thinking": "t" * 4000},
                   {"type": "text", "text": "r" * 400}),
        {"type": "user", "message": {"role": "user", "content": "u" * 800}},
        {"type": "attachment", "attachment": {"type": "reminder", "content": "a" * 392}},
        _assistant("m2", _usage(1, 100, 100, 10), {"type": "text", "text": "ok"}),
        _assistant("m3", _usage(1, 100, 200, 10), {"type": "text", "text": "ok"}),
    ]  # fmt: skip
    path = _write(tokens.project_folder(cwd, home) / "s.jsonl", entries)
    session = tokens.read_session(path, calibrate=False)
    assert session.calls == []  # not tool calls: never in the top list
    shares = tokens.analyse([session], W).by_category
    # Claude's text of request 1 (not its thinking): written at 2, read at 3.
    assert shares["replies"] == pytest.approx(100 * 1.25 + 100 * 0.1)
    # The message and the attachment (as JSON) after request 1, sent with request 2.
    attachment = len(json.dumps({"type": "reminder", "content": "a" * 392}))
    sent = round((800 + attachment) / 4)
    assert shares["messages"] == pytest.approx(sent * 1.25 + sent * 0.1)


def test_estimates_are_scaled_to_the_measured_new_context(home: Path, cwd: Path) -> None:
    entries = [
        _assistant("m1", _usage(0, 1000, 0, 1), _use("t1", "Read", file_path="a.py")),
        _result("t1", "x" * 4000),  # estimated 1 000 tokens
        _assistant("m2", _usage(0, 2000, 1000, 1), {"type": "text", "text": ""}),
        _assistant("m3", _usage(0, 0, 3000, 1), {"type": "text", "text": ""}),
    ]  # 2 000 new tokens measured after the start
    path = _write(tokens.project_folder(cwd, home) / "s.jsonl", entries)
    session = tokens.read_session(path)
    assert session.scale == pytest.approx(2.0, rel=0.02)
    assert session.calls[0].tokens == pytest.approx(2000, rel=0.02)
    assert tokens.read_session(path, calibrate=False).calls[0].tokens == 1000


def test_a_cache_miss_is_found_and_priced_apart(home: Path, cwd: Path) -> None:
    entries = [
        _assistant("m1", _usage(0, 50_000, 0, 1), {"type": "text", "text": "a"}),
        _assistant("m2", _usage(0, 1_000, 50_000, 1), {"type": "text", "text": "b"}),
        # After a long pause the cache expired: everything is written again.
        _assistant("m3", _usage(0, 52_000, 0, 1), {"type": "text", "text": "c"}),
    ]
    path = _write(tokens.project_folder(cwd, home) / "s.jsonl", entries)
    session = tokens.read_session(path)
    assert session.rebuilds == [51_000]
    shares = tokens.analyse([session], W).by_category
    assert shares["rebuild"] == pytest.approx(51_000 * (1.25 - 0.1))


# --- the report ------------------------------------------------------------------------


def test_the_report_ranks_calls_and_splits_by_kind(home: Path, cwd: Path) -> None:
    report = tokens.analyse([tokens.read_session(_session(home, cwd), calibrate=False)], W, top=2)
    assert [c.id for c in report.top] == ["t1", "t3"]
    shares = report.by_category
    assert set(shares) >= {"read", "command", "write", "output"}
    assert shares["read"] == pytest.approx(3000 * 1.25 + 3000 * 0.1 * 2)
    assert shares["output"] == pytest.approx(440 * 5)
    # The first request's context (system prompt, tools, CLAUDE.md) is read with every request.
    assert shares["baseline"] == pytest.approx(1010 * 1.25 + 1010 * 0.1 * 3)
    assert report.growth[0] == 1010 and report.growth[-1] == 4355  # context per turn


def test_json_and_text_say_the_same_and_name_no_paths(
    home: Path, cwd: Path, tmp_path: Path
) -> None:
    report = tokens.analyse([tokens.read_session(_session(home, cwd))], W, top=10)
    data = tokens.to_dict(report)
    assert data["sessions"][0]["id"] == "s1"
    assert data["sessions"][0]["scale"] > 0 and data["sessions"][0]["cache_misses"] == 0
    assert data["top"][0]["label"] == "src/a.py"
    assert data["top"][0]["if_10_lines"] < data["top"][0]["weighted"]
    assert data["weights"] == {"input": 1.0, "output": 5.0, "cache_write": 1.25, "cache_read": 0.1}
    text = tokens.render(report)
    assert "src/a.py" in text and "2.1.325" in text
    for out in (json.dumps(data), text):
        assert str(tmp_path) not in out and str(Path.home()) not in out
