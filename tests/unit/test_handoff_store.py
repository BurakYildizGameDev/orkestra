"""Handoff storage: init, locked updates, archive and redaction (Faz 10a)."""

from __future__ import annotations

import multiprocessing
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orkestra.config.schema import Config, HandoffCfg, ModelSpec, OpenAICompatProvider
from orkestra.errors import HandoffLocked, UsageError
from orkestra.handoff import model, store
from orkestra.i18n import t

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


# --- Claude review of Faz 10 (D-066) -----------------------------------------------------


@pytest.mark.parametrize("text", ["line\n## Done\nfake", "```python\nnot closed"])
def test_set_text_that_would_change_the_sections_is_refused(tmp_path: Path, text: str) -> None:
    """A ``## `` line opens a fake section; an open fence hides every later heading."""
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    before = path.read_bytes()
    with pytest.raises(UsageError) as exc_info:
        store.update(path, config=Config(version=1), section="status", set_text=text,
                     chief="claude", now=NOW)  # fmt: skip
    assert exc_info.value.message == t("handoff.error.breaks_structure", section="status")
    assert path.read_bytes() == before
    assert not store.lock_path(path).exists()


def test_set_text_with_a_heading_inside_a_closed_fence_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    text = "```md\n## not a heading\n```"
    store.update(path, config=Config(version=1), section="watch_out", set_text=text,
                 chief="claude", now=NOW)  # fmt: skip
    assert model.section_text(model.parse(store.read(path)), "watch_out") == text


def test_set_text_with_crlf_in_a_crlf_file_has_no_double_carriage_return(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    path.write_bytes(model.template("demo", "claude", NOW, None).replace("\n", "\r\n").encode())
    store.update(path, config=Config(version=1), section="watch_out", set_text="w1\r\nw2\rw3",
                 chief="claude", now=NOW)  # fmt: skip
    raw = path.read_bytes()
    assert b"\r\r" not in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert model.section_text(model.parse(store.read(path)), "watch_out") == "w1\nw2\nw3"


def test_moves_in_a_row_write_one_archive_heading(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    config = Config(version=1, handoff=HandoffCfg(max_lines=2))
    for n in range(5):
        store.update(path, config=config, section="done", add=f"item {n}", chief="claude",
                     now=NOW)  # fmt: skip
    archive = store.archive_path(path).read_text(encoding="utf-8")
    assert archive.count("## Done (archived)") == 1
    assert [line for line in archive.splitlines() if line.startswith("- ")] == [
        "- [2026-11-11 claude] item 0",
        "- [2026-11-11 claude] item 1",
        "- [2026-11-11 claude] item 2",
    ]


def test_the_archive_gets_a_new_heading_when_the_section_changes(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    _write(path, model.template("demo", "claude", NOW, None))
    config = Config(version=1, handoff=HandoffCfg(max_lines=1))
    for section in ("done", "done", "decisions", "decisions", "done"):
        store.update(path, config=config, section=section, add="x", chief="claude", now=NOW)
    headings = [
        line
        for line in store.archive_path(path).read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    assert headings == ["## Done (archived)", "## Decisions (archived)", "## Done (archived)"]


def test_the_archive_uses_the_line_ending_of_the_handoff_file(tmp_path: Path) -> None:
    path = tmp_path / "HANDOFF.md"
    path.write_bytes(model.template("demo", "claude", NOW, None).replace("\n", "\r\n").encode())
    config = Config(version=1, handoff=HandoffCfg(max_lines=1))
    for n in range(3):
        store.update(path, config=config, section="done", add=f"item {n}", chief="claude",
                     now=NOW)  # fmt: skip
    raw = store.archive_path(path).read_bytes()
    assert raw.count(b"\r\n") > 0
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_timestamps_are_written_to_the_second(tmp_path: Path) -> None:
    """Mimari §17 shows a short time; microseconds are noise in a file people read."""
    now = datetime(2026, 11, 11, 12, 0, 5, 123456, tzinfo=UTC)
    path = tmp_path / "HANDOFF.md"
    store.init_file(path, project="demo", chief="claude", at=now, commit=None)
    assert "at: 2026-11-11T12:00:05+00:00 |" in store.read(path)
    store.update(path, config=Config(version=1), section="goal", set_text="x", chief="agy",
                 now=now)  # fmt: skip
    assert "chief: agy | at: 2026-11-11T12:00:05+00:00 | commit: none" in store.read(path)


# --- Windows lock race (CI windows py3.13, 2026-11-13, D-067) ----------------------------


def _flaky_opener(fail_times: int) -> tuple[list[str], Callable[[str, int], int]]:
    calls: list[str] = []

    def opener(path: str, flags: int) -> int:
        calls.append(path)
        if len(calls) <= fail_times:
            raise PermissionError(13, "Permission denied", path)
        return os.open(path, flags)

    return calls, opener


def test_a_lock_that_windows_is_still_deleting_is_waited_for(tmp_path: Path) -> None:
    """Windows: O_EXCL on a lock file its owner is deleting raises PermissionError, not
    FileExistsError; that is "busy, try again", not a crash."""
    lock = tmp_path / "HANDOFF.md.lock"
    calls, opener = _flaky_opener(fail_times=2)
    sleeps: list[float] = []
    store._acquire(lock, now=NOW, timeout_s=5.0, stale_after_s=30.0, clock=lambda: 0.0,
                   sleep=sleeps.append, opener=opener, platform="nt")  # fmt: skip
    assert len(calls) == 3
    assert sleeps == [store.POLL_S, store.POLL_S]
    assert lock.exists()


def test_a_lock_windows_never_releases_times_out_with_the_lock_error(tmp_path: Path) -> None:
    lock = tmp_path / "HANDOFF.md.lock"
    _, opener = _flaky_opener(fail_times=10_000)
    ticks = iter(float(n) for n in range(10_000))
    with pytest.raises(HandoffLocked) as exc_info:
        store._acquire(lock, now=NOW, timeout_s=3.0, stale_after_s=30.0,
                       clock=lambda: next(ticks), sleep=lambda seconds: None, opener=opener,
                       platform="nt")  # fmt: skip
    assert exc_info.value.message == t("handoff.error.locked", path=lock)


def test_a_permission_error_outside_windows_is_a_real_error(tmp_path: Path) -> None:
    """On Unix it means the folder is not writable; waiting would only hide that."""
    _, opener = _flaky_opener(fail_times=1)
    with pytest.raises(PermissionError):
        store._acquire(tmp_path / "HANDOFF.md.lock", now=NOW, timeout_s=5.0,
                       stale_after_s=30.0, clock=lambda: 0.0, sleep=lambda seconds: None,
                       opener=opener, platform="posix")  # fmt: skip
