"""Faz 13l: a local provider's ``concurrency`` holds across processes (D-096), so a batch in
one terminal and ``orkestra exec`` in another never load two heavy local models at once."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any, cast

import pytest

from orkestra.config.schema import Config
from orkestra.state import db, slots
from orkestra.tasks.runner import ProviderSlots

PROVIDERS: dict[str, Any] = {
    "ollama": {"type": "ollama", "models": [{"id": "m", "tier": 1}]},
    "remote": {
        "type": "openai_compat",
        "base_url": "https://r.test/v1",
        "models": [{"id": "r", "tier": 1}],
    },
}


@pytest.fixture(autouse=True)
def fresh_process_state() -> Iterator[None]:
    """Slot ids restart in every test database; this process's held set must too."""
    slots._HELD.clear()
    yield
    slots._HELD.clear()


SERVER = "localhost:11434"  # the default Ollama server: the machine slot's key


@pytest.fixture
def db_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "state.db"
    with closing(db.connect(path)):
        pass
    yield path


def _config(concurrency: int = 1) -> Config:
    providers = {**PROVIDERS, "ollama": {**PROVIDERS["ollama"], "concurrency": concurrency}}
    return Config.model_validate({"version": 1, "providers": providers})


def _machine(db_path: Path, owner: tuple[int, float] = (1, 1.0)) -> slots.MachineSlots:
    return slots.MachineSlots(lambda: db.connect(db_path), poll_s=0.01, owner=owner,
                              alive=lambda pid, created: True)  # fmt: skip


def _rows(db_path: Path) -> int:
    with closing(db.connect(db_path)) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM local_slots").fetchone()[0])


def test_a_second_process_waits_for_the_local_model(db_path: Path) -> None:
    first = ProviderSlots(_config(), machine=_machine(db_path, (1, 1.0)))
    second = ProviderSlots(_config(), machine=_machine(db_path, (2, 2.0)))
    events: list[str] = []

    async def hold() -> None:
        async with first("ollama"):
            events.append("first in")
            await asyncio.sleep(0.1)
            events.append("first out")

    async def wait() -> None:
        await asyncio.sleep(0.02)
        async with second("ollama"):
            events.append("second in")

    async def both() -> None:
        await asyncio.gather(hold(), wait())

    asyncio.run(both())
    assert events == ["first in", "first out", "second in"]
    assert _rows(db_path) == 0  # every slot was given back


def test_concurrency_two_lets_two_processes_in(db_path: Path) -> None:
    first = ProviderSlots(_config(2), machine=_machine(db_path, (1, 1.0)))
    second = ProviderSlots(_config(2), machine=_machine(db_path, (2, 2.0)))

    async def both() -> int:
        async with first("ollama"), second("ollama"):
            return _rows(db_path)

    assert asyncio.run(both()) == 2


def test_remote_providers_take_no_machine_slot(db_path: Path) -> None:
    first = ProviderSlots(_config(), machine=_machine(db_path))

    async def use() -> int:
        async with first("remote"):
            return _rows(db_path)

    assert asyncio.run(use()) == 0


def test_a_slot_of_a_dead_process_is_taken_back(db_path: Path) -> None:
    with closing(db.connect(db_path)) as conn, db.transaction(conn):
        conn.execute(
            "INSERT INTO local_slots (provider, pid, created, acquired_at) "
            "VALUES (?, 999999, 1.0, '2026-11-18T12:00:00+03:00')",
            (SERVER,),
        )
    machine = slots.MachineSlots(lambda: db.connect(db_path), poll_s=0.01, owner=(1, 1.0),
                                 alive=lambda pid, created: pid != 999999)  # fmt: skip

    async def use() -> None:
        async with ProviderSlots(_config(), machine=machine)("ollama"):
            pass

    asyncio.run(asyncio.wait_for(use(), timeout=2))
    assert _rows(db_path) == 0


def test_acquire_and_release_by_hand_like_the_runner(db_path: Path) -> None:
    provider_slots = ProviderSlots(_config(), machine=_machine(db_path))

    async def use() -> tuple[int, int]:
        slot = provider_slots("ollama")
        await slot.acquire()
        held = _rows(db_path)
        slot.release()
        return held, _rows(db_path)

    assert asyncio.run(use()) == (1, 0)


def test_a_failure_inside_still_gives_the_slot_back(db_path: Path) -> None:
    provider_slots = ProviderSlots(_config(), machine=_machine(db_path))

    async def use() -> None:
        async with provider_slots("ollama"):
            raise RuntimeError("worker broke")

    with pytest.raises(RuntimeError):
        asyncio.run(use())
    assert _rows(db_path) == 0


def test_without_a_database_the_process_limit_still_works() -> None:
    def broken() -> Any:
        raise OSError("no state.db")

    machine = slots.MachineSlots(broken, poll_s=0.01, owner=(1, 1.0))

    async def use() -> None:
        async with ProviderSlots(_config(), machine=machine)("ollama"):
            pass

    asyncio.run(asyncio.wait_for(use(), timeout=2))


# --- code review #35 ---------------------------------------------------------------------


def test_a_short_wait_gives_up_instead_of_blocking(db_path: Path) -> None:
    """A chief tool must not wait behind another process's 30-minute task: it gives up after
    ``wait_s`` and the next candidate gets the work."""
    holder = _machine(db_path, (1, 1.0))
    other = _machine(db_path, (2, 2.0))

    async def both() -> None:
        held = await holder.acquire("ollama", 1)
        try:
            with pytest.raises(TimeoutError):
                await other.acquire("ollama", 1, wait_s=0.05)
        finally:
            holder.release(held)

    asyncio.run(both())
    assert _rows(db_path) == 0


def test_the_process_slot_is_given_back_when_the_machine_wait_gives_up(db_path: Path) -> None:
    holder = _machine(db_path, (1, 1.0))
    provider_slots = ProviderSlots(_config(), machine=_machine(db_path, (2, 2.0)))

    async def use() -> None:
        held = await holder.acquire(SERVER, 1)
        slot = provider_slots("ollama")
        with pytest.raises(TimeoutError):
            await slot.acquire(wait_s=0.05)
        holder.release(held)
        async with provider_slots("ollama"):  # the process's own semaphore is free again
            pass

    asyncio.run(asyncio.wait_for(use(), timeout=2))


def test_a_row_this_process_failed_to_give_back_is_taken_back(db_path: Path) -> None:
    """A failed release left a row with our own (live) pid; the next acquire must not wait
    six hours for it."""
    me = (1, 1.0)
    with closing(db.connect(db_path)) as conn, db.transaction(conn):
        conn.execute("INSERT INTO local_slots (provider, pid, created, acquired_at) "
                     "VALUES ('ollama', 1, 1.0, ?)", (db.local_now().isoformat(),))  # fmt: skip

    async def use() -> int | None:
        return await _machine(db_path, me).acquire("ollama", 1, wait_s=1)

    assert asyncio.run(use()) is not None


def test_a_locked_database_keeps_waiting_instead_of_skipping_the_limit(db_path: Path) -> None:
    import sqlite3

    calls = {"n": 0}

    def flaky() -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return db.connect(db_path)

    machine = slots.MachineSlots(flaky, poll_s=0.01, owner=(1, 1.0),
                                 alive=lambda pid, created: True)  # fmt: skip
    held = asyncio.run(machine.acquire("ollama", 1, wait_s=1))
    assert held is not None and calls["n"] >= 2  # it tried again and took a real slot
    assert _rows(db_path) == 1


def test_two_names_for_the_same_local_server_share_its_slots(db_path: Path) -> None:
    providers = {
        "ollama": {"type": "ollama", "models": [{"id": "big", "tier": 1}]},
        "small": {"type": "ollama", "base_url": "http://127.0.0.1:11434/",
                  "models": [{"id": "tiny", "tier": 1}]},
    }  # fmt: skip
    config = Config.model_validate({"version": 1, "providers": providers})
    first = ProviderSlots(config, machine=_machine(db_path, (1, 1.0)))
    second = ProviderSlots(config, machine=_machine(db_path, (2, 2.0)))

    async def both() -> None:
        async with first("ollama"):
            with pytest.raises(TimeoutError):
                await second("small").acquire(wait_s=0.05)

    asyncio.run(both())


def test_a_chief_tool_moves_on_when_the_local_model_is_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from orkestra.chief import call
    from orkestra.errors import NoProviderAvailable

    class Busy:
        async def acquire(self, wait_s: float | None = None) -> None:
            assert wait_s == call.LOCAL_WAIT_S  # a short wait, not forever
            raise TimeoutError

        def release(self) -> None:
            raise AssertionError("never acquired")

    class BusySlots:
        def __call__(self, provider: str) -> Busy:
            return Busy()

    config = Config.model_validate({"version": 1, "providers": {"ollama": PROVIDERS["ollama"]}})
    from orkestra.state import consent

    with closing(db.connect()) as conn:
        consent.grant(conn, "ollama", config.providers["ollama"], db.local_now())
    with pytest.raises(NoProviderAvailable):
        asyncio.run(
            call.query_chief_model(
                config, tier=1, system="s", user="u", work="summary", slots=cast(Any, BusySlots())
            )
        )
