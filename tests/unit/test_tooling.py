from __future__ import annotations

import asyncio

_ran: list[str] = []


async def test_async_tests_actually_run() -> None:
    # Without asyncio_mode = "auto" this coroutine is never awaited and pytest only warns.
    await asyncio.sleep(0)
    _ran.append("async")


def test_async_test_above_ran() -> None:
    assert _ran == ["async"]
