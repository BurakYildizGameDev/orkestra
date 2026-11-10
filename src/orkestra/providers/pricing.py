"""Model prices for budget estimates.

A ``daily_usd`` limit can only be enforced before a request if its cost can be estimated.
Prices are taken from, in order:

1. ``price_per_mtok`` in the config
2. the provider's ``/models`` listing (OpenRouter publishes per-token prices there), cached
   for 24 hours in ``~/.orkestra/cache/prices.json`` (a failed fetch is retried after 1 hour)
3. the highest cost per token seen in this model's past usage

Only providers that have a ``daily_usd`` limit and an unpriced model are ever fetched.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx

from orkestra import paths
from orkestra.config.schema import Config, ModelSpec, OpenAICompatProvider, Provider

PRICES_TTL = timedelta(hours=24)
FAILED_RETRY = timedelta(hours=1)
FETCH_TIMEOUT_S = 5.0

PriceSource = Literal["config", "provider", "history"]


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float
    source: PriceSource

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.input_per_mtok + completion_tokens * self.output_per_mtok
        ) / 1_000_000


def _cache_path() -> Path:
    return paths.cache_dir() / "prices.json"


def load_cache() -> dict[str, Any]:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(cache: dict[str, Any]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(json.dumps(cache, indent=2, sort_keys=True).encode("utf-8"))
    os.replace(tmp, path)


def needs_price(config: Provider) -> bool:
    """Provider has a USD limit and at least one model without a configured price."""
    return (
        isinstance(config, OpenAICompatProvider)
        and config.budget.daily_usd is not None
        and any(not m.price_per_mtok for m in config.models)
    )


def _is_fresh(entry: Mapping[str, Any], base_url: str, now: datetime) -> bool:
    if entry.get("base_url") != base_url:
        return False
    try:
        fetched = datetime.fromisoformat(entry["fetched_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return now - fetched < (PRICES_TTL if entry.get("ok") else FAILED_RETRY)


def _parse_prices(payload: Any) -> dict[str, dict[str, float]]:
    """OpenRouter: ``{"data": [{"id": …, "pricing": {"prompt": "0.000001", …}}]}`` (USD/token)."""
    prices: dict[str, dict[str, float]] = {}
    for item in payload.get("data", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict) or not isinstance(item.get("pricing"), dict):
            continue
        try:
            prompt = float(item["pricing"]["prompt"])
            completion = float(item["pricing"]["completion"])
        except (KeyError, TypeError, ValueError):
            continue
        if prompt < 0 or completion < 0:  # OpenRouter uses -1 for "variable" pricing
            continue
        prices[str(item["id"])] = {"input": prompt * 1_000_000, "output": completion * 1_000_000}
    return prices


async def _fetch(config: OpenAICompatProvider, environ: Mapping[str, str]) -> dict[str, Any]:
    headers = dict(config.extra_headers)
    key = environ.get(config.api_key_env, "").strip() if config.api_key_env else ""
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S) as client:
            response = await client.get(f"{config.base_url.rstrip('/')}/models", headers=headers)
        response.raise_for_status()
        return {"ok": True, "prices": _parse_prices(response.json())}
    except (httpx.HTTPError, ValueError):
        return {"ok": False, "prices": {}}


async def refresh(
    config: Config,
    now: datetime,
    *,
    environ: Mapping[str, str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Fetch stale price lists for providers that need them; returns the cache."""
    env = os.environ if environ is None else environ
    cache = load_cache()
    changed = False
    for name, provider in config.providers.items():
        if not isinstance(provider, OpenAICompatProvider) or not needs_price(provider):
            continue
        entry = cache.get(name, {})
        if not force and _is_fresh(entry, provider.base_url, now):
            continue
        result = await _fetch(provider, env)
        cache[name] = {"base_url": provider.base_url, "fetched_at": now.isoformat(), **result}
        changed = True
    if changed:
        # Prices are an optimisation; never fail a run because of the cache file.
        with contextlib.suppress(OSError):
            _save_cache(cache)
    return cache


def _from_history(conn: sqlite3.Connection, provider: str, model: str) -> Price | None:
    row = conn.execute(
        "SELECT MAX(cost_usd * 1.0 / (prompt_tokens + completion_tokens)) FROM usage "
        "WHERE provider = ? AND model = ? AND kind = 'actual' AND cost_usd > 0 "
        "AND (prompt_tokens + completion_tokens) > 0",
        (provider, model),
    ).fetchone()
    rate = row[0] if row else None
    if not rate:
        return None
    return Price(rate * 1_000_000, rate * 1_000_000, "history")


def resolve(
    provider: str,
    config: Provider,
    model: ModelSpec,
    *,
    conn: sqlite3.Connection,
    cache: Mapping[str, Any],
) -> Price | None:
    """Price of one model: config > provider listing > past usage > unknown."""
    if model.price_per_mtok:
        return Price(
            model.price_per_mtok.get("input", 0.0),
            model.price_per_mtok.get("output", 0.0),
            "config",
        )
    entry = cache.get(provider, {})
    base_url = getattr(config, "base_url", None)
    if entry.get("base_url") == base_url:
        listed = entry.get("prices", {}).get(model.id)
        if isinstance(listed, dict):
            return Price(float(listed["input"]), float(listed["output"]), "provider")
    return _from_history(conn, provider, model.id)
