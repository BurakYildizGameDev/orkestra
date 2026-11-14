"""The night queue: store, single-runner lock, ``--until``, recovery, cost cap (Faz 12a, §21)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path

import psutil
import pytest

from orkestra.errors import ExitCode, QueueBusy, UsageError
from orkestra.queue import service, store
from orkestra.state import db

TZ = datetime(2026, 11, 15, 12, 0).astimezone().tzinfo


def _at(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


START = _at(15, 22, 0)


@pytest.fixture
def conn() -> Iterator[db.sqlite3.Connection]:
    with closing(db.connect()) as connection:
        yield connection


def _task(where: Path, name: str = "task.yaml", prompt: str = "say hi") -> Path:
    path = where / name
    path.write_text(f"id: {path.stem}\nkind: ask\nprompt: {prompt}\n", encoding="utf-8")
    return path


def _batch(where: Path, name: str = "batch.json") -> Path:
    path = where / name
    tasks = [
        {"id": "a", "kind": "ask", "prompt": "one"},
        {"id": "b", "kind": "ask", "prompt": "two"},
    ]
    path.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
    return path


class Clock:
    def __init__(self, start: datetime = START) -> None:
        self.moment = start

    def __call__(self) -> datetime:
        return self.moment


# --- store ------------------------------------------------------------------------------


def test_add_keeps_the_absolute_path_the_kind_the_hash_and_where_it_was_added(
    conn: db.sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _task(tmp_path)
    task = store.add(conn, Path("task.yaml"), now=START)  # relative to where it was added
    batch = store.add(conn, _batch(tmp_path), profile="quality", now=START)
    assert task.path == str((tmp_path / "task.yaml").resolve())
    assert task.kind == "task" and batch.kind == "batch"
    assert task.workdir == str(tmp_path.resolve())
    assert task.file_hash == store.file_hash(tmp_path / "task.yaml")
    assert task.status == "pending" and task.profile is None and batch.profile == "quality"
    assert [item.id for item in store.items(conn)] == [task.id, batch.id]


def test_a_broken_file_is_refused_and_nothing_is_queued(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("kind: nonsense\n", encoding="utf-8")
    with pytest.raises(UsageError):
        store.add(conn, broken, now=START)
    with pytest.raises(UsageError):
        store.add(conn, tmp_path / "missing.yaml", now=START)
    assert store.items(conn) == []


def test_remove_hides_a_pending_item_but_never_a_running_one(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    first = store.add(conn, _task(tmp_path, "one.yaml"), now=START)
    second = store.add(conn, _task(tmp_path, "two.yaml"), now=START)
    store.remove(conn, first.id)
    assert [item.id for item in store.items(conn)] == [second.id]
    store.mark_running(conn, second.id, START)
    store.acquire_lock(conn, START, owner=(4242, 1.0), alive=lambda pid, created: True)
    with pytest.raises(UsageError):  # a live queue run owns it
        store.remove(conn, second.id, alive=lambda pid, created: True)
    with pytest.raises(UsageError):
        store.remove(conn, 999)
    with pytest.raises(UsageError):
        store.remove(conn, first.id)  # already removed


def test_counts_leave_removed_and_done_items_out_of_the_waiting_numbers(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    items = [store.add(conn, _task(tmp_path, f"t{n}.yaml"), now=START) for n in range(4)]
    store.mark_running(conn, items[0].id, START)
    store.mark_finished(conn, items[0].id, "done", START, result_ref="r1")
    store.mark_running(conn, items[1].id, START)
    store.mark_finished(conn, items[1].id, "failed", START, note="verify")
    store.remove(conn, items[2].id)
    assert store.counts(conn) == {"pending": 1, "running": 0, "failed": 1, "done": 1}


# --- --until ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "until", "expected"),
    [
        (_at(15, 22, 0), "08:00", _at(16, 8, 0)),
        (_at(15, 7, 0), "08:00", _at(15, 8, 0)),
        (_at(15, 8, 0), "08:00", _at(16, 8, 0)),
        (_at(15, 23, 30), "0:15", _at(16, 0, 15)),
    ],
)
def test_until_is_the_next_time_the_clock_shows_that_hour(
    now: datetime, until: str, expected: datetime
) -> None:
    assert service.deadline(until, now) == expected


@pytest.mark.parametrize("until", ["25:00", "8", "08:60", "eight", ""])
def test_a_wrong_until_is_a_usage_error(until: str) -> None:
    with pytest.raises(UsageError):
        service.deadline(until, START)


def test_after_until_no_new_item_starts_but_the_running_one_finishes(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    items = [store.add(conn, _task(tmp_path, f"t{n}.yaml"), now=START) for n in range(3)]
    clock = Clock(_at(16, 7, 0))
    started: list[int] = []

    def execute(item: store.QueueItem, remaining: float | None) -> service.ItemResult:
        started.append(item.id)
        clock.moment += timedelta(hours=2)  # the first item runs past 08:00
        return service.ItemResult("done", result_ref=f"run-{item.id}")

    report = service.run_queue(conn, until="08:00", now=clock, execute=execute)
    assert started == [items[0].id]
    assert report.stopped == "until"
    statuses = {item.id: item.status for item in store.items(conn)}
    assert statuses == {items[0].id: "done", items[1].id: "pending", items[2].id: "pending"}


# --- the single-runner lock ---------------------------------------------------------------


def test_a_second_queue_run_stops_with_a_clear_message(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    store.add(conn, _task(tmp_path), now=START)
    store.acquire_lock(conn, START, owner=(4242, 1.0), alive=lambda pid, created: True)
    with pytest.raises(QueueBusy) as info:
        service.run_queue(
            conn,
            now=Clock(),
            execute=lambda i, r: service.ItemResult("done"),
            alive=lambda pid, created: True,
        )
    assert info.value.exit_code == ExitCode.CONFLICT
    assert "4242" in str(info.value)
    assert store.items(conn)[0].status == "pending"
    assert store.lock_owner(conn) is not None  # the other run keeps its lock


def test_a_lock_left_by_a_dead_process_is_cleared(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    item = store.add(conn, _task(tmp_path), now=START)
    store.acquire_lock(conn, START, owner=(4242, 1.0), alive=lambda pid, created: True)
    report = service.run_queue(
        conn,
        now=Clock(),
        execute=lambda i, r: service.ItemResult("done"),
        alive=lambda pid, created: False,
    )
    assert report.done == [item.id]
    assert store.lock_owner(conn) is None  # released at the end


def test_process_alive_tells_a_reused_pid_from_the_owner() -> None:
    me = psutil.Process()
    assert store.process_alive(me.pid, me.create_time())
    assert not store.process_alive(me.pid, me.create_time() - 3600)  # same pid, other process
    assert not store.process_alive(2**31 - 7, None)  # no such process


def test_the_lock_is_released_even_when_an_item_breaks_the_loop(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    store.add(conn, _task(tmp_path), now=START)

    def execute(item: store.QueueItem, remaining: float | None) -> service.ItemResult:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        service.run_queue(conn, now=Clock(), execute=execute)
    assert store.lock_owner(conn) is None
    assert store.items(conn)[0].status == "running"  # the next run puts it back


# --- recovery after a kill ----------------------------------------------------------------

_HOLDER = """
import sys, time
from contextlib import closing
from datetime import datetime
from orkestra.queue import store
from orkestra.state import db
with closing(db.connect()) as conn:
    now = datetime.now().astimezone()
    store.acquire_lock(conn, now)
    store.mark_running(conn, int(sys.argv[1]), now)
    print("ready", flush=True)
    time.sleep(60)
"""


def test_an_item_left_running_by_a_killed_process_is_pending_again(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    item = store.add(conn, _task(tmp_path), now=START)
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(item.id)],
        stdout=subprocess.PIPE,
        text=True,
        env=dict(os.environ),
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        assert store.items(conn)[0].status == "running"
        with pytest.raises(QueueBusy):  # alive: a second run must not start
            service.run_queue(conn, now=Clock(), execute=lambda i, r: service.ItemResult("done"))
    finally:  # the venv's python.exe on Windows starts the real interpreter as a child
        children = psutil.Process(holder.pid).children(recursive=True)
        for child in children:
            child.kill()
        holder.kill()
        holder.wait(timeout=30)
        psutil.wait_procs(children, timeout=30)
    seen: list[int] = []

    def execute(queued: store.QueueItem, remaining: float | None) -> service.ItemResult:
        seen.append(queued.id)
        return service.ItemResult("done", result_ref="run-1")

    report = service.run_queue(conn, now=Clock(), execute=execute)
    assert report.recovered == 1
    assert seen == [item.id]
    assert store.items(conn)[0].status == "done"


# --- results, skips and the cost cap ------------------------------------------------------


def test_a_failing_or_broken_item_does_not_stop_the_others(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    items = [store.add(conn, _task(tmp_path, f"t{n}.yaml"), now=START) for n in range(3)]

    def execute(item: store.QueueItem, remaining: float | None) -> service.ItemResult:
        if item.id == items[0].id:
            raise RuntimeError("boom")
        if item.id == items[1].id:
            return service.ItemResult("failed", result_ref="run-2", note="verify failed")
        return service.ItemResult("done", result_ref="run-3")

    report = service.run_queue(conn, now=Clock(), execute=execute)
    assert report.failed == [items[0].id, items[1].id] and report.done == [items[2].id]
    rows = {item.id: item for item in store.items(conn)}
    assert rows[items[0].id].status == "failed" and "boom" in (rows[items[0].id].note or "")
    assert rows[items[1].id].result_ref == "run-2"
    assert rows[items[2].id].finished_at is not None


def test_a_skipped_item_stays_pending_with_the_reason_and_the_next_one_runs(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    first = store.add(conn, _task(tmp_path, "one.yaml"), now=START)
    second = store.add(conn, _task(tmp_path, "two.yaml"), now=START)

    def execute(item: store.QueueItem, remaining: float | None) -> service.ItemResult:
        if item.id == first.id:
            return service.ItemResult("skipped", note="needs cost confirmation")
        return service.ItemResult("done")

    report = service.run_queue(conn, now=Clock(), execute=execute)
    assert report.skipped == [first.id] and report.done == [second.id]
    row = store.items(conn)[0]
    assert row.status == "pending" and row.note == "needs cost confirmation"


def test_max_cost_stops_new_items_once_it_is_spent_and_passes_what_is_left(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    items = [store.add(conn, _task(tmp_path, f"t{n}.yaml"), now=START) for n in range(3)]
    remaining_seen: list[float | None] = []

    def execute(item: store.QueueItem, remaining: float | None) -> service.ItemResult:
        remaining_seen.append(remaining)
        return service.ItemResult("done", cost_usd=0.30)

    report = service.run_queue(conn, now=Clock(), max_cost_usd=0.50, execute=execute)
    assert remaining_seen == [pytest.approx(0.50), pytest.approx(0.20)]
    assert report.stopped == "cost" and report.spent_usd == pytest.approx(0.60)
    assert [i.status for i in store.items(conn)] == ["done", "done", "pending"]
    assert report.done == [items[0].id, items[1].id]


def test_an_item_added_while_the_queue_runs_is_picked_up(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    store.add(conn, _task(tmp_path, "one.yaml"), now=START)
    added: list[int] = []

    def execute(item: store.QueueItem, remaining: float | None) -> service.ItemResult:
        if not added:
            added.append(store.add(conn, _task(tmp_path, "two.yaml"), now=START).id)
        return service.ItemResult("done")

    report = service.run_queue(conn, now=Clock(), execute=execute)
    assert len(report.done) == 2 and added[0] in report.done


def test_an_item_without_a_profile_runs_on_the_queue_default_profile() -> None:
    from orkestra.config.schema import Config

    config = Config.model_validate(
        {"version": 1, "queue": {"default_profile": "cheap"}, "defaults": {"profile": "balanced"}}
    )
    plain = service.item_config(config, None)
    assert plain.defaults.profile == "cheap"  # gives way like a default when a task needs more
    assert service.item_config(config, "quality") is config  # --profile goes through RunOptions


# --- code review fixes (PR #23, D-073) ------------------------------------------------


def test_mark_running_only_takes_a_pending_item(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    item = store.add(conn, _task(tmp_path), now=START)
    store.remove(conn, item.id)
    assert store.mark_running(conn, item.id, START) is False
    assert store.get(conn, item.id).status == "removed"


def test_an_item_removed_after_it_was_fetched_does_not_run(
    conn: db.sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = store.add(conn, _task(tmp_path, "one.yaml"), now=START)
    second = store.add(conn, _task(tmp_path, "two.yaml"), now=START)
    real_next = store.next_pending

    def racing_next(connection: db.sqlite3.Connection, after_id: int) -> store.QueueItem | None:
        found = real_next(connection, after_id)
        if found is not None and found.id == first.id:
            store.remove(connection, first.id)  # `queue remove` lands right after the read
        return found

    monkeypatch.setattr(store, "next_pending", racing_next)
    seen: list[int] = []

    def execute(item: store.QueueItem, remaining: float | None) -> service.ItemResult:
        seen.append(item.id)
        return service.ItemResult("done")

    report = service.run_queue(conn, now=Clock(), execute=execute)
    assert seen == [second.id] and report.done == [second.id]
    assert store.get(conn, first.id).status == "removed"


def test_a_running_item_without_a_live_runner_can_be_removed(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    item = store.add(conn, _task(tmp_path), now=START)
    store.mark_running(conn, item.id, START)  # Ctrl+C left it running; no lock
    store.remove(conn, item.id)
    assert store.items(conn) == []
    other = store.add(conn, _task(tmp_path, "two.yaml"), now=START)
    store.mark_running(conn, other.id, START)
    store.acquire_lock(conn, START, owner=(4242, 1.0), alive=lambda pid, created: True)
    with pytest.raises(UsageError):
        store.remove(conn, other.id, alive=lambda pid, created: True)
    store.remove(conn, other.id, alive=lambda pid, created: False)  # the owner is gone
    assert store.items(conn) == []


def test_max_cost_zero_still_runs_free_items(conn: db.sqlite3.Connection, tmp_path: Path) -> None:
    items = [store.add(conn, _task(tmp_path, f"t{n}.yaml"), now=START) for n in range(2)]
    seen: list[float | None] = []

    def execute(item: store.QueueItem, remaining: float | None) -> service.ItemResult:
        seen.append(remaining)
        return service.ItemResult("done", cost_usd=0.0)

    report = service.run_queue(conn, now=Clock(), max_cost_usd=0.0, execute=execute)
    assert report.done == [i.id for i in items] and report.stopped is None
    assert seen == [0.0, 0.0]


def test_max_cost_zero_stops_after_anything_is_spent(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    for n in range(2):
        store.add(conn, _task(tmp_path, f"t{n}.yaml"), now=START)
    report = service.run_queue(
        conn, now=Clock(), max_cost_usd=0.0,
        execute=lambda i, r: service.ItemResult("done", cost_usd=0.01),
    )  # fmt: skip
    assert len(report.done) == 1 and report.stopped == "cost"


class _Berlin(tzinfo):
    """+02:00 until 2026-10-25 01:00 UTC, +01:00 after (no tzdata on Windows)."""

    CHANGE = datetime(2026, 10, 25, 1, 0)

    def utcoffset(self, dt: datetime | None) -> timedelta:
        assert dt is not None
        local = dt.replace(tzinfo=None)
        return (
            timedelta(hours=2) if local < self.CHANGE + timedelta(hours=2) else timedelta(hours=1)
        )

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "Berlin"


def test_until_keeps_the_wall_clock_across_a_dst_change() -> None:
    berlin = _Berlin()
    now = datetime(2026, 10, 24, 22, 0, tzinfo=berlin)
    stop = service.deadline("06:00", now, localize=lambda naive: naive.replace(tzinfo=berlin))
    assert stop.replace(tzinfo=None) == datetime(2026, 10, 25, 6, 0)
    assert stop.utcoffset() == timedelta(hours=1)  # 06:00 on the clock, after the change
    assert stop.astimezone(UTC) - now.astimezone(UTC) == timedelta(hours=9)


def test_only_a_batch_waits_for_cost_confirmation_a_single_task_never(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from orkestra.config.schema import Config
    from orkestra.envelope import BatchEstimate
    from orkestra.tasks import batch, runner

    async def estimate(*args: object, **kwargs: object) -> BatchEstimate:
        return BatchEstimate(needs_confirmation=True)

    monkeypatch.setattr(batch, "checks_cost", lambda config: True)
    monkeypatch.setattr(batch, "estimate_batch", estimate)
    from orkestra.tasks.spec import parse_task

    config = Config.model_validate({"version": 1})
    one = batch.from_tasks([parse_task({"id": "a", "kind": "ask", "prompt": "x"}, source="t")], "t")
    options = runner.RunOptions()
    assert service.cost_skip(one, config, options, None, confirm=False) is None
    assert service.cost_skip(one, config, options, None, confirm=True) is not None


def test_access_denied_is_not_our_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(pid: int) -> object:
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr(store.psutil, "Process", denied)
    assert store.process_alive(4242, 1.0) is False  # our own runner is always readable


def test_failed_items_count_only_when_they_are_recent(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    old = store.add(conn, _task(tmp_path, "old.yaml"), now=START)
    store.mark_running(conn, old.id, START)
    store.mark_finished(conn, old.id, "failed", START - timedelta(days=3))
    assert store.counts(conn, failed_since=START - timedelta(hours=24))["failed"] == 0
    fresh = store.add(conn, _task(tmp_path, "new.yaml"), now=START)
    store.mark_running(conn, fresh.id, START)
    store.mark_finished(conn, fresh.id, "failed", START - timedelta(hours=1))
    assert store.counts(conn, failed_since=START - timedelta(hours=24))["failed"] == 1
    assert store.counts(conn)["failed"] == 2


def test_a_wrong_finished_status_is_an_internal_error(
    conn: db.sqlite3.Connection, tmp_path: Path
) -> None:
    from orkestra.errors import InternalError

    item = store.add(conn, _task(tmp_path), now=START)
    with pytest.raises(InternalError):
        store.mark_finished(conn, item.id, "pending", START)
