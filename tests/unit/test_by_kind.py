"""Faz 13l: ``routing.by_kind`` — which model each kind of work prefers (D-096)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from orkestra.config.schema import Config
from orkestra.routing.router import ProviderState, Snapshot, TaskNeeds, route

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone(timedelta(hours=3)))
PROVIDERS: dict[str, Any] = {
    "local": {
        "type": "ollama",
        "models": [
            {"id": "qwen2.5-coder:14b", "tier": 1},
            {"id": "qwen2.5:1.5b", "tier": 1},
            {"id": "big", "tier": 2},
        ],
    },
    "router": {
        "type": "openai_compat",
        "base_url": "https://router.test/v1",
        "models": [{"id": "meta/llama:free", "tier": 1}, {"id": "paid", "tier": 1}],
    },
}


def _order(by_kind: dict[str, Any], needs: TaskNeeds, **states: ProviderState) -> list[str]:
    config = Config.model_validate(
        {"version": 1, "providers": PROVIDERS, "routing": {"by_kind": by_kind}}
    )
    granted = {n: ProviderState(consent="granted") for n in PROVIDERS} | states
    found = route(needs, config, Snapshot(NOW, granted), profile="balanced")
    return [c.label for c in found.candidates]


DEFAULT = ["local/qwen2.5-coder:14b", "local/qwen2.5:1.5b", "router/meta/llama:free",
           "router/paid", "local/big"]  # fmt: skip


def test_without_by_kind_the_order_is_unchanged() -> None:
    assert _order({}, TaskNeeds(work="summary")) == DEFAULT


def test_a_kind_prefers_its_models_in_the_order_written() -> None:
    by_kind = {"summary": {"prefer": ["router/*:free", "local/qwen2.5:1.5b"]}}
    assert _order(by_kind, TaskNeeds(work="summary")) == [
        "router/meta/llama:free", "local/qwen2.5:1.5b", "local/qwen2.5-coder:14b",
        "router/paid", "local/big",
    ]  # fmt: skip


def test_other_kinds_are_not_affected() -> None:
    by_kind = {"summary": {"prefer": ["local/qwen2.5:1.5b"]}}
    assert _order(by_kind, TaskNeeds(work="read")) == DEFAULT


def test_a_task_without_a_work_kind_uses_its_task_kind() -> None:
    by_kind = {"edit": {"prefer": ["router"]}}
    assert _order(by_kind, TaskNeeds(kind="edit"))[:2] == ["router/meta/llama:free", "router/paid"]


def test_a_preference_never_crosses_tiers() -> None:
    by_kind = {"summary": {"prefer": ["local/big"]}}
    assert _order(by_kind, TaskNeeds(work="summary"))[-1] == "local/big"


def test_running_low_still_comes_before_a_preference() -> None:
    by_kind = {"summary": {"prefer": ["router"]}}
    low = ProviderState(consent="granted", quota_low=True)
    assert _order(by_kind, TaskNeeds(work="summary"), router=low)[:2] == [
        "local/qwen2.5-coder:14b", "local/qwen2.5:1.5b",
    ]  # fmt: skip


def test_unknown_kinds_are_refused() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate(
            {"version": 1, "routing": {"by_kind": {"summaries": {"prefer": ["x"]}}}}
        )


def test_the_dry_run_description_names_the_preference() -> None:
    from orkestra.routing.router import describe_candidates

    routing = {"by_kind": {"read": {"prefer": ["router"]}}}
    config = Config.model_validate({"version": 1, "providers": PROVIDERS, "routing": routing})
    granted = {n: ProviderState(consent="granted") for n in PROVIDERS}
    found = route(TaskNeeds(work="read"), config, Snapshot(NOW, granted), profile="cheap")
    ranks = {d["model"]: d["prefer_rank"] for d in describe_candidates(found.candidates)}
    assert ranks["meta/llama:free"] == 0 and ranks["qwen2.5:1.5b"] is None


@pytest.mark.parametrize(
    ("module", "work"),
    [("execute", "summary"), ("reader", "read"), ("repomap", "map"), ("review", "review"),
     ("plan", "plan")],
)  # fmt: skip
def test_every_chief_tool_names_its_work(module: str, work: str) -> None:
    """Each tool's ``query_chief_model`` call passes its own kind (read from the code, not
    its text: formatting does not matter, a comment does not count)."""
    import ast
    import importlib
    import inspect

    tree = ast.parse(inspect.getsource(importlib.import_module(f"orkestra.chief.{module}")))
    found = [
        kw.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", None)) == "query_chief_model"
        for kw in node.keywords
        if kw.arg == "work" and isinstance(kw.value, ast.Constant)
    ]
    assert found == [work]


def test_a_literal_id_with_brackets_matches_itself() -> None:
    providers = {"local": {"type": "ollama", "models": [
        {"id": "a", "tier": 1}, {"id": "foo[beta]", "tier": 1}]}}  # fmt: skip
    routing = {"by_kind": {"read": {"prefer": ["local/foo[beta]"]}}}
    config = Config.model_validate({"version": 1, "providers": providers, "routing": routing})
    snapshot = Snapshot(NOW, {"local": ProviderState(consent="granted")})
    found = route(TaskNeeds(work="read"), config, snapshot, profile="cheap")
    assert [c.label for c in found.candidates] == ["local/foo[beta]", "local/a"]


def test_patterns_that_name_nothing_are_reported() -> None:
    from orkestra.routing.router import unmatched_preferences

    config = Config.model_validate({"version": 1, "providers": PROVIDERS, "routing": {"by_kind": {
        "summary": {"prefer": ["ollama/qwen2.5:1.5b", "router/*:free", "local"]},
        "edit": {"prefer": ["codex"]},
    }}})  # fmt: skip
    assert unmatched_preferences(config) == [("summary", "ollama/qwen2.5:1.5b"), ("edit", "codex")]


def test_query_chief_model_routes_with_the_work_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    from orkestra.chief import call
    from orkestra.errors import NoProviderAvailable

    seen: list[str | None] = []

    def fake_route(needs: TaskNeeds, *args: Any, **kwargs: Any) -> Any:
        seen.append(needs.work)
        raise NoProviderAvailable("stop")

    monkeypatch.setattr(call, "route", fake_route)
    config = Config.model_validate({"version": 1, "providers": PROVIDERS})
    with pytest.raises(NoProviderAvailable):
        asyncio.run(call.query_chief_model(config, tier=1, system="s", user="u", work="summary"))
    assert seen == ["summary"]


def test_doctor_warns_about_a_pattern_that_names_nothing(tmp_path: Any) -> None:
    from orkestra import doctor, hardware

    config_file = tmp_path / "c.yaml"
    config_file.write_text(
        "version: 1\nproviders:\n  local:\n    type: ollama\n    models: [{id: a, tier: 1}]\n"
        "routing:\n  by_kind:\n    summary: {prefer: [ollama/a]}\n",
        encoding="utf-8",
    )
    report = asyncio.run(doctor.run_doctor(config_flag=config_file, which=lambda name: None,
                                           machine=hardware.Machine(None, None)))  # fmt: skip
    [check] = [c for c in report.checks if c.data.get("by_kind")]
    assert check.status == "warn" and "ollama/a" in check.message
