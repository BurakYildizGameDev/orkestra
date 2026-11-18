"""Chief model invocation helper (Mimari §19).

Queries candidate models through the router: respects tier, privacy, secrets scanning,
budget reservations, health checks, and concurrency slots.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from orkestra import paths
from orkestra.config.schema import CliAgentProvider, Config, WorkKind
from orkestra.errors import (
    BudgetExhausted,
    NoProviderAvailable,
    OrkestraError,
    ProviderError,
    ProviderTimeout,
)
from orkestra.i18n import t
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

# A chief tool waits this long for a local model another process is using (Faz 13l, D-097),
# then the next candidate gets the work: a summary must not wait behind a 30-minute task.
LOCAL_WAIT_S = 2.0


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
    agents: bool = True,
    work: WorkKind,
    providers: Sequence[str] | None = None,
    exclude: Collection[str] = (),
) -> tuple[str, str]:
    """Query a candidate model chosen by the router for a chief tool.

    Returns ``(answer_text, provider_model_label)``. Candidates are tried in the router's
    order; when all of them fail, the last provider (or budget) error is raised, and when
    none could be tried, the router's own error (``NoProviderAvailable``,
    ``ConsentRequired``) (D-062). ``agents=False`` leaves code agents out: summarising text
    does not need a whole agent run (``exec``, D-088). ``work`` names the kind of work for
    ``routing.by_kind`` (Faz 13l, D-096): every tool passes its own. ``providers``: only
    these, in this order; ``exclude``: never these (a cross-review, Faz 13m, D-098).
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
        work=work,
    )

    should_close_conn = False
    if conn is None:
        conn = db.connect()
        should_close_conn = True

    try:
        snapshot = take_snapshot(conn, config, current_time, environ=env)
        route_result = route(needs, config, snapshot, profile=None)
        last_error: OrkestraError | None = None
        candidates = [
            c for c in route_result.candidates
            if (agents or not isinstance(c.config, CliAgentProvider))
            and c.provider not in exclude
            and (providers is None or c.provider in providers)
        ]  # fmt: skip
        if providers is not None:
            order = {name: index for index, name in enumerate(providers)}
            candidates.sort(key=lambda c: order[c.provider])  # stable: router order inside
        if route_result.candidates and not candidates and (providers is not None or exclude):
            raise NoProviderAvailable(t("chief.error.no_reviewer"), details=[
                e.reason for e in route_result.eliminated
                if providers is None or e.provider in providers
            ])  # fmt: skip
        if route_result.candidates and not candidates:
            # Why the chat models are out (paused, no consent, …) says more than "none".
            chat = [
                e.reason for e in route_result.eliminated
                if not isinstance(config.providers.get(e.provider), CliAgentProvider)
            ]  # fmt: skip
            raise NoProviderAvailable(t("chief.error.no_chat_model"), details=chat)
        for candidate in candidates:
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
    try:
        # A local model busy with another process's task: the next candidate, not a wait.
        await slot.acquire(wait_s=LOCAL_WAIT_S)
    except TimeoutError:
        return None
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
