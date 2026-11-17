"""Faz 13l: a local provider's ``concurrency`` holds across processes (D-096), so a batch in
one terminal and ``orkestra exec`` in another never load two heavy local models at once."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

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
        conn.execute("INSERT INTO local_slots (provider, pid, created, acquired_at) "
                     "VALUES ('ollama', 999999, 1.0, '2026-11-18T12:00:00+03:00')")  # fmt: skip
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
