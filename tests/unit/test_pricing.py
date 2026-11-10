from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from orkestra.config.schema import Config, ModelSpec
from orkestra.providers import pricing
from orkestra.state import budget, db

BASE = "https://router.test/api/v1"
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone(timedelta(hours=3)))
FAKE_KEY = "sk-or-v1-PRICINGTESTKEY000000000000000"


def _config(daily_usd: float | None = 1.0, **model: Any) -> Config:
    router: dict[str, Any] = {
        "type": "openai_compat",
        "base_url": BASE,
        "api_key_env": "ROUTER_KEY",
        "models": [{"id": "vendor/model", "tier": 2, **model}],
    }
    if daily_usd is not None:
        router["budget"] = {"daily_usd": daily_usd}
    return Config.model_validate(
        {
            "version": 1,
            "providers": {
                "router": router,
                "ollama": {"type": "ollama", "models": [{"id": "m", "tier": 1}]},
            },
        }
    )


def _listing(prompt: str = "0.000002", completion: str = "0.000008") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                {"id": "vendor/model", "pricing": {"prompt": prompt, "completion": completion}},
                {"id": "other/variable", "pricing": {"prompt": "-1", "completion": "-1"}},
                {"id": "no/pricing"},
            ]
        },
    )


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "state.db")) as connection:
        yield connection


def _model(cfg: Config) -> ModelSpec:
    return cfg.providers["router"].models[0]  # type: ignore[union-attr]


@respx.mock
async def test_prices_fetched_cached_and_resolved(conn: sqlite3.Connection) -> None:
    route = respx.get(f"{BASE}/models").mock(return_value=_listing())
    cfg = _config()
    cache = await pricing.refresh(cfg, NOW, environ={"ROUTER_KEY": FAKE_KEY})
    assert route.call_count == 1
    assert route.calls.last.request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    price = pricing.resolve("router", cfg.providers["router"], _model(cfg), conn=conn, cache=cache)
    assert price == pricing.Price(2.0, 8.0, "provider")
    assert "other/variable" not in cache["router"]["prices"]  # -1 = variable price, ignored

    await pricing.refresh(cfg, NOW + timedelta(hours=23), environ={})
    assert route.call_count == 1  # still fresh
    await pricing.refresh(cfg, NOW + timedelta(hours=25), environ={})
    assert route.call_count == 2  # stale after 24h
    assert FAKE_KEY not in (Path(pricing.paths.cache_dir()) / "prices.json").read_text(
        encoding="utf-8"
    )


@respx.mock
async def test_only_providers_that_need_prices_are_fetched() -> None:
    route = respx.get(f"{BASE}/models").mock(return_value=_listing())
    await pricing.refresh(_config(daily_usd=None), NOW, environ={})
    await pricing.refresh(_config(price_per_mtok={"input": 1.0, "output": 1.0}), NOW, environ={})
    assert route.call_count == 0


@respx.mock
async def test_failed_fetch_is_retried_after_an_hour() -> None:
    route = respx.get(f"{BASE}/models").mock(side_effect=httpx.ConnectError("offline"))
    cfg = _config()
    cache = await pricing.refresh(cfg, NOW, environ={})
    assert cache["router"]["ok"] is False
    await pricing.refresh(cfg, NOW + timedelta(minutes=30), environ={})
    assert route.call_count == 1  # offline: do not slow every run down
    await pricing.refresh(cfg, NOW + timedelta(minutes=61), environ={})
    assert route.call_count == 2


@respx.mock
async def test_changed_base_url_invalidates_cached_prices(conn: sqlite3.Connection) -> None:
    respx.get(f"{BASE}/models").mock(return_value=_listing())
    cache = await pricing.refresh(_config(), NOW, environ={})
    moved = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "router": {
                    "type": "openai_compat",
                    "base_url": "https://elsewhere.test/v1",
                    "models": [{"id": "vendor/model", "tier": 2}],
                }
            },
        }
    )
    assert (
        pricing.resolve("router", moved.providers["router"], _model(moved), conn=conn, cache=cache)
        is None
    )


def test_config_price_wins(conn: sqlite3.Connection) -> None:
    cfg = _config(price_per_mtok={"input": 3.0, "output": 4.0})
    cache = {"router": {"base_url": BASE, "prices": {"vendor/model": {"input": 9, "output": 9}}}}
    price = pricing.resolve("router", cfg.providers["router"], _model(cfg), conn=conn, cache=cache)
    assert price == pricing.Price(3.0, 4.0, "config")


def test_history_fallback_uses_highest_rate(conn: sqlite3.Connection) -> None:
    cfg = _config()
    model = _model(cfg)
    assert pricing.resolve("router", cfg.providers["router"], model, conn=conn, cache={}) is None
    for tokens, cost in ((1000, 0.001), (1000, 0.004)):  # 1 and 4 USD per 1M tokens
        rid = budget.reserve(
            conn, provider="router", model="vendor/model", run_id="r",
            budget=cfg.providers["router"].budget, amount=budget.Amount(requests=1), now=NOW,
        )  # fmt: skip
        budget.settle(
            conn, rid, prompt_tokens=tokens, completion_tokens=0, cost_usd=cost,
            estimated=False, now=NOW,
        )  # fmt: skip
    price = pricing.resolve("router", cfg.providers["router"], model, conn=conn, cache={})
    assert price is not None
    assert price.source == "history"
    assert price.input_per_mtok == pytest.approx(4.0)
    assert price.output_per_mtok == pytest.approx(4.0)
