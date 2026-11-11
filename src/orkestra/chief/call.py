"""Chief model invocation helper (Mimari §19).

Queries candidate models through the router: respects tier, privacy, secrets scanning,
budget reservations, health checks, and concurrency slots.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from orkestra import paths
from orkestra.config.schema import CliAgentProvider, Config
from orkestra.errors import (
    BudgetExhausted,
    OrkestraError,
    ProviderError,
    ProviderTimeout,
)
from orkestra.providers.base import (
    AgentRequest,
    CompletionRequest,
    estimate_tokens,
)
from orkestra.providers.cli_agent import create_agent
from orkestra.providers.registry import (
    create_chat_provider,
    request_timeout,
)
from orkestra.routing.router import (
    Candidate,
    TaskNeeds,
    route,
    take_snapshot,
)
from orkestra.security.redact import configured_secrets
from orkestra.security.secrets_scan import blocking, scan_text
from orkestra.state import budget, db, health
from orkestra.tasks.runner import ProviderSlots, new_run_id


def prompt_has_secrets(
    config: Config, text: str, *, environ: Mapping[str, str] | None = None
) -> bool:
    """Whether ``text`` holds a key or token that must not reach a remote provider."""
    return bool(blocking(scan_text("chief", text, configured_secrets(config, environ))))


async def query_chief_model(
    config: Config,
    *,
    tier: int,
    system: str,
    user: str,
    privacy: str = "normal",
    json_mode: bool = False,
    run_id: str | None = None,
    slots: ProviderSlots | None = None,
    conn: sqlite3.Connection | None = None,
    now: datetime | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Query a candidate model chosen by the router for a chief tool.

    Returns ``(answer_text, provider_model_label)``. Candidates are tried in the router's
    order; when all of them fail, the last provider (or budget) error is raised, and when
    none could be tried, the router's own error (``NoProviderAvailable``,
    ``ConsentRequired``) (D-062).
    """
    env = os.environ if environ is None else environ
    current_time = db.local_now() if now is None else now
    effective_run_id = run_id or new_run_id(current_time)
    provider_slots = slots or ProviderSlots(config)

    needs = TaskNeeds(
        kind="ask",
        tier=tier,
        privacy="local_only" if privacy == "local_only" else "normal",
        prompt_chars=len(system) + len(user),
        has_secrets=prompt_has_secrets(config, system + "\n" + user, environ=env),
        allow_secrets=False,
    )

    should_close_conn = False
    if conn is None:
        conn = db.connect()
        should_close_conn = True

    try:
        snapshot = take_snapshot(conn, config, current_time, environ=env)
        route_result = route(needs, config, snapshot, profile=None)
        last_error: OrkestraError | None = None
        for candidate in route_result.candidates:
            if health.get(conn, candidate.provider).is_open(current_time):
                continue
            try:
                answer = await _try_candidate(
                    candidate=candidate,
                    config=config,
                    conn=conn,
                    system=system,
                    user=user,
                    json_mode=json_mode,
                    run_id=effective_run_id,
                    slots=provider_slots,
                    current_time=current_time,
                    env=env,
                )
            except (ProviderError, BudgetExhausted) as exc:
                last_error = exc
                continue
            if answer is not None:
                return answer, candidate.label
        if last_error is not None:
            raise last_error
        raise route_result.error()
    finally:
        if should_close_conn:
            conn.close()


async def _try_candidate(
    candidate: Candidate,
    config: Config,
    conn: sqlite3.Connection,
    system: str,
    user: str,
    json_mode: bool,
    run_id: str,
    slots: ProviderSlots,
    current_time: datetime,
    env: Mapping[str, str],
) -> str | None:
    """The candidate's answer; ``None`` when another task paused it while this one waited.

    A provider error is recorded in its health and raised; a success closes the failure
    streak (D-062). ``BudgetExhausted`` means nothing was sent.
    """
    slot = slots(candidate.provider)
    await slot.acquire()
    try:
        if health.get(conn, candidate.provider).is_open(current_time):
            return None

        prompt_chars = len(system) + len(user)
        max_output = candidate.model.max_output_tokens or config.defaults.max_output_tokens
        amount = budget.estimate(prompt_chars, max_output, candidate.price, runs=1)
        reservation = budget.reserve(
            conn,
            provider=candidate.provider,
            model=candidate.model.id,
            run_id=run_id,
            budget=candidate.config.budget,
            amount=amount,
            now=current_time,
        )
        try:
            if isinstance(candidate.config, CliAgentProvider):
                agent = create_agent(candidate.provider, candidate.config, env)
                output_file = paths.run_dir(run_id) / "agent_output.md"
                output_file.parent.mkdir(parents=True, exist_ok=True)
                agent_req = AgentRequest(
                    prompt=f"{system}\n\n{user}",
                    workdir=Path.cwd(),
                    sandbox="read-only",
                    timeout_s=candidate.config.timeout_s or config.defaults.timeout_s,
                    model=candidate.model.id,
                    output_file=output_file,
                )
                # A non-zero exit or an empty answer is a ProviderBadOutput (CliAgent.run).
                agent_res = await agent.run(agent_req)
                result_text = agent_res.final_message
                budget.settle(
                    conn,
                    reservation,
                    prompt_tokens=estimate_tokens(prompt_chars),
                    completion_tokens=estimate_tokens(len(result_text)),
                    cost_usd=0.0,
                    estimated=True,
                    now=current_time,
                )
            else:
                provider = create_chat_provider(candidate.provider, candidate.config, env)
                comp_req = CompletionRequest(
                    model=candidate.model.id,
                    system=system,
                    user=user,
                    json_mode=json_mode,
                    timeout_s=request_timeout(candidate.config, config.defaults),
                    max_output_tokens=max_output,
                )
                res = await provider.complete(comp_req)
                result_text = res.text
                prompt_toks = res.usage.prompt_tokens or estimate_tokens(prompt_chars)
                compl_toks = res.usage.completion_tokens or estimate_tokens(len(result_text))
                cost = res.usage.cost_usd
                if cost is None and candidate.price is not None:
                    cost = candidate.price.cost(prompt_toks, compl_toks)
                budget.settle(
                    conn,
                    reservation,
                    prompt_tokens=prompt_toks,
                    completion_tokens=compl_toks,
                    cost_usd=cost,
                    estimated=res.usage.cost_usd is None,
                    now=current_time,
                )
        except ProviderError as exc:
            if isinstance(exc, ProviderTimeout):
                budget.settle_as_reserved(conn, reservation, now=current_time)
            else:
                budget.settle(
                    conn,
                    reservation,
                    prompt_tokens=0,
                    completion_tokens=0,
                    cost_usd=0.0,
                    estimated=False,
                    now=current_time,
                )
            health.record_failure(conn, candidate.provider, exc, current_time)
            raise
        except BaseException:
            budget.release(conn, reservation)
            raise
        health.record_success(conn, candidate.provider)
        return result_text
    finally:
        slot.release()
