"""Handoff storage: init, locked updates, archive and redaction (Faz 10a)."""

from __future__ import annotations

import multiprocessing
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orkestra.config.schema import Config, HandoffCfg, ModelSpec, OpenAICompatProvider
from orkestra.errors import HandoffLocked, UsageError
from orkestra.handoff import model, store

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_init_creates_the_template_and_never_overwrites(tmp_path: Path) -> None:
    path = tmp_path / ".orkestra" / "HANDOFF.md"
    store.init_file(path, project="demo", chief="claude", at=NOW, commit="abc123")
    original = path.read_text(encoding="utf-8")
    assert original.startswith("<!-- orkestra-handoff v1 -->\n# Devir: demo\n")
    assert "chief: claude | at: 2026-11-11T12:00:00+00:00 | commit: abc123" in original
    with pytest.raises(UsageError):
        store.init_file(path, project="demo", chief="agy", at=NOW, commit=None)
    assert path.read_text(encoding="utf-8") == original


def test_update_requires_an_existing_file(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        store.update(
            tmp_path / "missing.md", config=Config(version=1), section="done",
            add="x", chief="claude", now=NOW,
        )  # fmt: skip


def test_update_rejects_an_invalid_section_before_touching_the_file(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    before = path.read_text(encoding="utf-8")
    with pytest.raises(UsageError):
        store.update(path, config=Config(version=1), section="goals", set_text="x",
                     chief="claude", now=NOW)  # fmt: skip
    assert path.read_text(encoding="utf-8") == before


def test_update_sets_a_section_and_the_last_updated_line(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    result = store.update(
        path, config=Config(version=1), section="status", set_text="halfway",
        chief="agy", now=NOW, commit="def456",
    )  # fmt: skip
    text = path.read_text(encoding="utf-8")
    assert model.section_text(model.parse(text), "status") == "halfway"
    assert "chief: agy | at: 2026-11-11T12:00:00+00:00 | commit: def456" in text
    assert result.section == "status"
    assert result.last_updated.commit == "def456"


@pytest.mark.parametrize(
    "section", ["goal", "status", "in_progress", "open_questions", "watch_out"]
)
def test_set_covers_every_non_list_section(tmp_path: Path, section: str) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    store.update(path, config=Config(version=1), section=section, set_text="some text",
                 chief="claude", now=NOW, commit=None)  # fmt: skip
    assert model.section_text(model.parse(path.read_text(encoding="utf-8")), section) == "some text"


@pytest.mark.parametrize("section", ["done", "decisions"])
def test_add_covers_both_list_sections(tmp_path: Path, section: str) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    store.update(path, config=Config(version=1), section=section, add="a decision",
                 chief="claude", now=NOW, commit=None)  # fmt: skip
    item = model.section_text(model.parse(path.read_text(encoding="utf-8")), section)
    assert item == "- [2026-11-11 claude] a decision"


def test_done_and_decisions_do_not_accept_set(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    with pytest.raises(UsageError):
        store.update(path, config=Config(version=1), section="done", set_text="x",
                     chief="claude", now=NOW)  # fmt: skip


def test_the_other_sections_do_not_accept_add(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    with pytest.raises(UsageError):
        store.update(path, config=Config(version=1), section="goal", add="x",
                     chief="claude", now=NOW)  # fmt: skip


def test_add_and_set_together_is_a_usage_error(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    with pytest.raises(UsageError):
        store.update(path, config=Config(version=1), section="done", add="x", set_text="y",
                     chief="claude", now=NOW)  # fmt: skip


def test_done_entries_move_to_the_archive_oldest_first_and_the_archive_is_appended(
    tmp_path: Path,
) -> None:
    path = tmp_path / "HANDOFF.md"
    document = model.parse(model.template("demo", "claude", NOW, None))
    model.set_section(document, "done", "\n".join(f"- old {n}" for n in range(1, 6)))
    _write(path, model.render(document))
    result = store.update(
        path, config=Config(version=1, handoff=HandoffCfg(max_lines=3)),
        section="done", add="new 6", chief="claude", now=NOW,
    )  # fmt: skip
    assert result.archived == 3
    assert model.section_text(
        model.parse(path.read_text(encoding="utf-8")), "done"
    ).splitlines() == [
        "- old 4",
        "- old 5",
        "- [2026-11-11 claude] new 6",
    ]
    archive = store.archive_path(path)
    first = archive.read_text(encoding="utf-8")
    assert "old 1" in first and "old 3" in first and "new 6" not in first
    store.update(
        path, config=Config(version=1, handoff=HandoffCfg(max_lines=3)),
        section="done", add="new 7", chief="claude", now=NOW,
    )  # fmt: skip
    second = archive.read_text(encoding="utf-8")
    assert "old 1" in second and "old 4" in second  # the old archive stayed
    body = model.section_text(model.parse(path.read_text(encoding="utf-8")), "done")
    everything = body + "\n" + second
    assert sorted(line for line in everything.splitlines() if line.startswith("- ")) == [
        "- [2026-11-11 claude] new 6",
        "- [2026-11-11 claude] new 7",
        "- old 1",
        "- old 2",
        "- old 3",
        "- old 4",
        "- old 5",
    ]


def test_configured_and_pattern_secrets_are_masked_in_the_file_and_archive(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    config = Config(
        version=1,
        providers={
            "cloud": OpenAICompatProvider(
                type="openai_compat", base_url="https://example.invalid/v1",
                api_key_env="TEST_API_KEY", models=[ModelSpec(id="m", tier=2)],
            )
        },
    )  # fmt: skip
    secret = "sk-or-v1-TESTKEY0123456789"
    store.update(
        path,
        config=config,
        section="watch_out",
        set_text=f"key {secret} and sk-abcdefghijklmnopqrstuvwxyz",
        chief="claude",
        now=NOW,
        commit=None,
        environ={"TEST_API_KEY": secret},
    )
    text = path.read_text(encoding="utf-8")
    assert secret not in text
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in text
    assert text.count("***") >= 2


def test_a_live_lock_times_out_with_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    lock = store.lock_path(path)
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        with pytest.raises(HandoffLocked):
            store.update(path, config=Config(version=1), section="goal", set_text="x",
                         chief="claude", now=NOW, lock_timeout_s=0.05)  # fmt: skip
    finally:
        lock.unlink()
    assert not lock.exists()


def test_a_stale_lock_is_removed_and_the_update_goes_through(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    lock = store.lock_path(path)
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    old = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    os.utime(lock, (old, old))
    store.update(path, config=Config(version=1), section="goal", set_text="after crash",
                 chief="claude", now=NOW, stale_after_s=30, lock_timeout_s=1)  # fmt: skip
    assert not lock.exists()
    assert (
        model.section_text(model.parse(path.read_text(encoding="utf-8")), "goal") == "after crash"
    )


def _concurrent_worker(path: str, number: int) -> None:
    config = Config(version=1)
    for index in range(20):
        store.update(
            Path(path), config=config, section="done", add=f"p{number}-{index}",
            chief=f"c{number}", now=NOW, commit=None, lock_timeout_s=60,
        )  # fmt: skip


def test_two_processes_adding_twenty_items_each_keep_all_forty(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    processes = [
        multiprocessing.Process(target=_concurrent_worker, args=(str(path), number))
        for number in (1, 2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=120)
        assert process.exitcode == 0
    document = model.parse(path.read_text(encoding="utf-8"))
    items = [line for line in model.section_text(document, "done").splitlines() if line.strip()]
    assert len(items) == 40
    joined = "\n".join(items)
    assert all(f"p{number}-{index}" in joined for number in (1, 2) for index in range(20))
    assert not store.lock_path(path).exists()


def test_update_keeps_a_crlf_file_crlf_through_the_real_read_path(tmp_path: Path) -> None:
    """GLM B1: the real read path must not translate CRLF away before the parser sees it."""
    path = tmp_path / "HANDOFF.md"
    text = model.template("demo", "claude", NOW, None).replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))
    store.update(
        path, config=Config(version=1), section="status", set_text="halfway",
        chief="claude", now=NOW,
    )  # fmt: skip
    raw = path.read_bytes()
    assert raw.count(b"\r\n") > 0
    assert raw.count(b"\n") == raw.count(b"\r\n")  # no bare LF anywhere
    assert b"halfway" in raw


def test_project_root_uses_git_and_falls_back_to_cwd(tmp_path: Path) -> None:
    """GLM B3: the handoff file belongs to the repository root, not to the current folder."""
    root = tmp_path / "repo"

    def at_root(args: list[str], cwd: Path) -> tuple[bool, str]:
        return True, str(root) + "\n"

    def no_git(args: list[str], cwd: Path) -> tuple[bool, str]:
        return False, ""

    assert store.project_root(tmp_path / "sub", at_root) == root
    assert store.project_root(tmp_path / "sub", no_git) == tmp_path / "sub"
    target = store.handoff_path(Config(version=1), tmp_path / "sub", at_root)
    assert target == root / ".orkestra" / "HANDOFF.md"


@pytest.mark.parametrize("chief", ["a | b", "a:b", "a\nb"])
def test_a_chief_that_would_break_the_last_updated_line_is_rejected(
    tmp_path: Path, chief: str,
) -> None:  # fmt: skip
    """GLM B9: '|', ':' and line breaks would corrupt the ``Last updated`` line."""
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    before = path.read_text(encoding="utf-8")
    with pytest.raises(UsageError):
        store.update(path, config=Config(version=1), section="goal", set_text="x",
                     chief=chief, now=NOW)  # fmt: skip
    assert path.read_text(encoding="utf-8") == before


def test_init_rejects_a_chief_that_would_break_the_last_updated_line(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        store.init_file(tmp_path / "HANDOFF.md", project="demo", chief="a | b", at=NOW, commit=None)


def test_add_rejects_line_breaks(tmp_path: Path) -> None:
    """GLM B13: a multi-line --add would be split by the line-counting archive."""
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    before = path.read_text(encoding="utf-8")
    with pytest.raises(UsageError):
        store.update(path, config=Config(version=1), section="done", add="line one\nline two",
                     chief="claude", now=NOW)  # fmt: skip
    assert path.read_text(encoding="utf-8") == before
