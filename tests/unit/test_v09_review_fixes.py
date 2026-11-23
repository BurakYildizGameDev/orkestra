"""Code review of the v0.9 break-test fixes (PR #67, 2026-11-23, D-142)."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx

from orkestra.config.schema import Config, OpenAICompatProvider
from orkestra.providers import pricing
from orkestra.routing.router import (
    Elimination,
    ProviderState,
    Route,
    Snapshot,
    TaskNeeds,
    route,
)
from tests.unit.test_pricing import BASE, NOW, _config, _listing
from tests.unit.test_router import NOW as ROUTER_NOW
from tests.unit.test_router import _config as _router_config
from tests.unit.test_router import _granted

# --- no_price only when the price list was really read ----------------------------------


def _labels(snapshot: Snapshot) -> tuple[list[str], dict[str, str]]:
    result = route(TaskNeeds(), _router_config(), snapshot)
    return [c.label for c in result.candidates], {e.label: e.code for e in result.eliminated}


def test_unpriced_model_is_kept_when_the_price_list_was_not_read() -> None:
    """No list, a stale one or a failed fetch: the run goes on as before (reported cost)."""
    unpriced = {("router", "r1"): None, ("router", "r2"): None}
    labels, eliminated = _labels(Snapshot(ROUTER_NOW, _granted(), unpriced))
    assert "router/r1" in labels
    assert "router/r1" not in eliminated


def test_unpriced_model_is_dropped_when_the_read_list_does_not_price_it() -> None:
    unpriced = {("router", "r1"): None, ("router", "r2"): None}
    snapshot = Snapshot(ROUTER_NOW, _granted(), unpriced, price_lists=frozenset({"router"}))
    labels, eliminated = _labels(snapshot)
    assert "router/r1" not in labels
    assert eliminated["router/r1"] == "no_price"


def test_a_price_list_counts_only_when_fresh_and_read() -> None:
    entry = {"base_url": BASE, "fetched_at": NOW.isoformat(), "ok": True, "prices": {}}
    assert pricing.list_is_current(entry, BASE, NOW)
    assert not pricing.list_is_current({**entry, "ok": False}, BASE, NOW)
    assert not pricing.list_is_current(entry, "https://other.test/v1", NOW)
    assert not pricing.list_is_current({}, BASE, NOW)


@respx.mock
async def test_an_explicit_unlisted_model_gets_its_price_list_fetched() -> None:
    fetched = respx.get(f"{BASE}/models").mock(return_value=_listing())
    priced = _config(price_per_mtok={"input": 1.0, "output": 1.0})  # nothing to fetch for
    await pricing.refresh(priced, NOW, only={"router"}, environ={})
    assert fetched.call_count == 0
    await pricing.refresh(priced, NOW, only={"router"}, environ={}, extra=("router", "x/y"))
    assert fetched.call_count == 1


# --- consent heading ----------------------------------------------------------------


def _error(*codes: tuple[str, bool]) -> type:
    elims = tuple(Elimination(f"p{i}", None, code, code, consent) for i, (code, consent)
                  in enumerate(codes))  # fmt: skip
    return type(Route("balanced", (1, 3), 10, (), elims).error())


def test_consent_is_named_unless_the_task_itself_rules_providers_out() -> None:
    from orkestra.errors import ConsentRequired, NoProviderAvailable

    assert _error(("tier_out_of_range", False), ("consent_none", True)) is ConsentRequired
    assert _error(("paused", False), ("consent_none", True)) is ConsentRequired
    assert _error(("secrets_remote", False), ("consent_none", True)) is NoProviderAvailable
    assert _error(("not_local", False), ("consent_none", True)) is NoProviderAvailable
    assert _error(("disabled", False)) is NoProviderAvailable


# --- consent describe: odd addresses ---------------------------------------------------


@pytest.mark.parametrize(
    ("url", "hint"),
    [("http://[::1:8000/v1", False), ("http://127.example.test/v1", False),
     ("http://127.0.0.2:8000/v1", True)],
)  # fmt: skip
def test_loopback_hint_survives_odd_addresses(url: str, hint: bool) -> None:
    from orkestra.state import consent

    cfg = OpenAICompatProvider.model_validate(
        {"type": "openai_compat", "base_url": url, "models": [{"id": "m", "tier": 1}]}
    )
    assert ("local: true" in "\n".join(consent.describe("lm", cfg))) is hint


# --- model names on one line -----------------------------------------------------------


@pytest.mark.parametrize("name", [f"m{chr(0x2028)}x", f"m{chr(0x2029)}x", "m\u0085x", "m\x7fx"])
def test_model_name_line_breaks_of_any_kind_are_refused(name: str) -> None:
    from orkestra.chief import team
    from orkestra.errors import UsageError

    with pytest.raises(UsageError):
        team._model_name(name)  # pyright: ignore[reportPrivateUsage]


# --- backups: none is deleted ----------------------------------------------------------


def test_an_init_force_backup_survives_later_edits(tmp_path: Path) -> None:
    from orkestra.config import writer

    path = tmp_path / "config.yaml"
    path.write_text("version: 1\n", encoding="utf-8")
    (tmp_path / "config.yaml.bak").write_text("first\n", encoding="utf-8")
    (tmp_path / "config.yaml.bak.1").write_text("before init --force\n", encoding="utf-8")
    for n in range(8):
        doc = writer.load_document(path)
        doc["language"] = "en" if n % 2 else "tr"
        writer.save(path, doc)
    assert (tmp_path / "config.yaml.bak.1").read_text(encoding="utf-8") == "before init --force\n"


def test_config_import_is_used() -> None:  # keeps the shared helpers honest
    assert isinstance(_router_config(), Config)
    assert ProviderState().consent != "granted"
