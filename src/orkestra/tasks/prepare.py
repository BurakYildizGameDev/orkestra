"""Before a task runs (Mimari §8, steps 1-2): options, run ids, provider slots, the
prepared prompt and context, routing, ``--dry-run`` and cost estimates (düzeltme-fable b,
D-106: moved out of ``runner.py``; ``runner`` re-exports the public names).

The underscore names here (``_prepare``, ``_route``, ``_Prepared``, ``_cannot_do`` …) are
internal to ``tasks.runner`` / ``tasks.run_record`` / this module, not file-local: change
their callers there too.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import sqlite3
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import get_args

import pathspec

from orkestra import paths
from orkestra.config.schema import CliAgentProvider, Config, EditFormat, resolve_edit_format
from orkestra.envelope import (
    ResultEnvelope,
)
from orkestra.errors import (
    InternalError,
    OrkestraError,
)
from orkestra.i18n import t
from orkestra.providers import pricing
from orkestra.providers.base import (
    estimate_tokens,
)
from orkestra.routing.router import (
    Candidate,
    Route,
    Snapshot,
    TaskNeeds,
    route,
    scope,
    take_snapshot,
)
from orkestra.security.redact import Redactor, configured_secrets
from orkestra.security.secrets_scan import Finding, blocking, scan_text
from orkestra.state import budget, consent, db
from orkestra.state.slots import MachineSlots, server_key
from orkestra.tasks import edit_format as ef
from orkestra.tasks.context import Context, collect_context
from orkestra.tasks.prompts import (
    build_agent_prompt,
    build_ask_messages,
    edit_body,
    edit_rules,
    load_prompt,
)
from orkestra.tasks.spec import ForbidPaths, ProtectPaths, TaskSpec, effective_verifiers
from orkestra.verify import Verifier, build_verifiers
from orkestra.verify.schema import JsonSchemaCheck
from orkestra.workspace import git_worktree as gw

Sleep = Callable[[float], Awaitable[None]]

PROMPT_SOURCE = "<prompt>"  # where a finding in the prompt text itself is reported
CANNOT_DO = "CANNOT_DO:"  # worker protocol (prompts/worker_system.md, Mimari §8.1)
VERIFICATION_FAILED = "VerificationFailed"  # failover "error" when answers kept failing checks
SCOPE_CHECK = "workspace_scope"  # verification entry: an agent wrote outside its worktree
SCOPE_FILES = 10  # changed files named in that check
AGENT_CONTINUE = (
    "Your changes from the previous attempt are still in the working tree. "
    "Fix them; do not start over."
)
OUTPUT_TRUNCATED = "OutputTruncated"  # failover "error" when an edit answer was cut off
TOP_TIER = 3
IGNORED_WARNINGS = 5  # more skipped files than this are reported as one count
SUMMARY_FILES = 5  # changed files named in an edit summary
NOTE_CHARS = 200  # characters of the worker's note in an edit summary (Mimari §8)


_ISSUED: set[str] = set()  # run ids handed out by this process (a batch starts several a second)


def new_run_id(now: datetime | None = None, token: str | None = None) -> str:
    """``YYYYMMDD-HHMMSS-<4 hex>``: sortable and collision free within this process.

    A random token that was already handed out, or whose run directory exists, is drawn
    again; ``token`` (tests) is used as given.
    """
    moment = datetime.now() if now is None else now
    if token is not None:
        return f"{moment:%Y%m%d-%H%M%S}-{token}"
    while True:
        run_id = f"{moment:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        if run_id not in _ISSUED and not paths.run_dir(run_id).exists():
            _ISSUED.add(run_id)
            return run_id


class ProviderSlots:
    """Requests in flight per provider, at most its ``concurrency`` (Mimari §12).

    One instance is shared by all tasks of a batch; a single run gets its own. For a
    ``local`` provider the limit holds across processes too (``state.slots``, Faz 13l): one
    heavy local model at a time on this computer, whoever asks.
    """

    def __init__(self, config: Config, machine: MachineSlots | None = None) -> None:
        self._limits = {name: provider.concurrency for name, provider in config.providers.items()}
        # Local providers share the machine's slots of their server (``state.slots``).
        self._servers = {
            name: server_key(name, provider)
            for name, provider in config.providers.items()
            if provider.local
        }
        self._slots: dict[str, asyncio.Semaphore] = {}
        self._machine = machine or MachineSlots()
        self.prices = asyncio.Lock()  # price list fetches, one task at a time

    def __call__(self, provider: str) -> Slot:
        if provider not in self._slots:
            self._slots[provider] = asyncio.Semaphore(self._limits.get(provider, 1))
        server = self._servers.get(provider)
        machine = self._machine if server is not None else None
        return Slot(self._slots[provider], machine, server or provider,
                    self._limits.get(provider, 1))  # fmt: skip


class Slot:
    """One request's place: the process's semaphore, then (local providers) the machine's.
    Used as ``async with`` or with ``acquire()`` / ``release()`` on the same object."""

    def __init__(
        self, semaphore: asyncio.Semaphore, machine: MachineSlots | None, key: str,
        limit: int,
    ) -> None:  # fmt: skip
        self._semaphore = semaphore
        self._machine = machine
        self._key = key
        self._limit = limit
        self._held: int | None = None

    async def acquire(self, wait_s: float | None = None) -> None:
        """``wait_s``: give up after that long on the machine's slot (``TimeoutError``); the
        process's own place is given back then."""
        await self._semaphore.acquire()
        if self._machine is None:
            return
        try:
            self._held = await self._machine.acquire(self._key, self._limit, wait_s=wait_s)
        except BaseException:  # timed out or cancelled: give the process's place back
            self._semaphore.release()
            raise

    def release(self) -> None:
        if self._machine is not None:
            held, self._held = self._held, None
            self._machine.release(held)
        self._semaphore.release()

    async def __aenter__(self) -> Slot:
        await self.acquire()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.release()


@dataclass(frozen=True)
class RunOptions:
    """Command line choices that are not part of the task itself."""

    profile: str | None = None
    allow_secrets: bool = False
    no_cache: bool = False  # --no-cache: never answer an ask task from the cache (Faz 8a)


@dataclass(frozen=True)
class TaskOutcome:
    envelope: ResultEnvelope
    output: str | None
    exit_code: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DryRun:
    route: Route
    warnings: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        return 0 if self.route.candidates else self.route.error().exit_code


def _scan(prompt: str, context: Context, known: Sequence[str]) -> list[Finding]:
    """The prompt counts as much as the context: ``ask "$(cat .env)"`` must not leak either."""
    findings = scan_text(PROMPT_SOURCE, prompt, known)
    for f in context.files:
        findings.extend(scan_text(f.display, f.text, known))
    return findings


def _cannot_do(text: str) -> str | None:
    """The worker's reason when it answered ``CANNOT_DO: <reason>``, else ``None``."""
    stripped = text.strip()
    if not stripped.startswith(CANNOT_DO):
        return None
    return stripped[len(CANNOT_DO) :].strip().splitlines()[0] if stripped != CANNOT_DO else ""


@dataclass(frozen=True)
class _EditPlan:
    """What an edit answer may touch (Mimari §8.2)."""

    editable: frozenset[str]  # context files, as the worker sees their paths
    forbidden: tuple[str, ...]  # forbid_paths patterns: rejected before anything is written
    protected: tuple[str, ...]  # protect_paths patterns: told to the worker, checked after
    lines: int  # lines of the largest context file (router: max_api_edit_lines)


def _line_count(text: str) -> int:
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def _is_utf8(path: Path) -> bool:
    try:
        path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return True


def _edit_plan(task: TaskSpec, context: Context, base: Path) -> tuple[_EditPlan, list[str]]:
    """Which context files the worker may rewrite, and warnings for the ones it may not.

    Read-only: files matching protect/forbid patterns (reference only), files that are not
    UTF-8 (the worker saw them with replacement characters; rewriting them would damage every
    other line) and files git ignores (a change to them could never be applied). Only the
    editable files count for ``max_api_edit_lines``.
    """
    checks = effective_verifiers(task)
    forbidden = tuple(p for v in checks if isinstance(v, ForbidPaths) for p in v.paths)
    protected = tuple(p for v in checks if isinstance(v, ProtectPaths) for p in v.paths)
    guarded = pathspec.GitIgnoreSpec.from_lines([*protected, *forbidden])
    files: dict[str, str] = {}  # editable path -> text
    warnings: list[str] = []
    for f in context.files:
        rel = ef.normalize_path(f.display)
        if rel is None or guarded.match_file(rel):
            continue
        if not _is_utf8(f.path):
            warnings.append(t("edit.warning.not_utf8", path=rel))
            continue
        files[rel] = f.text
    for rel in sorted(gw.ignored(base, sorted(files))):
        warnings.append(t("edit.warning.ignored", path=rel))
        del files[rel]
    plan = _EditPlan(
        editable=frozenset(files),
        forbidden=forbidden,
        protected=protected,
        lines=max((_line_count(text) for text in files.values()), default=0),
    )
    return plan, warnings


@dataclass
class _Prepared:
    task: TaskSpec
    options: RunOptions
    config: Config
    env: Mapping[str, str]
    base_dir: Path
    checks: list[Verifier]
    context: Context
    redact: Redactor  # records and logs: everything that looks secret
    redact_output: Redactor  # the answer: secrets only, so "password: changeme" stays intact
    findings: list[Finding]
    warnings: list[str]
    system: str
    user: str  # edit tasks: the context and the task only; the rules depend on the format
    edit: _EditPlan | None = None
    agent_user: str = ""  # the prompt for code agents
    # edit tasks: the answer format's rules, appended to ``user`` (the context is rendered once)
    edit_rules: Mapping[EditFormat, str] = field(default_factory=dict)

    def messages(self, edit_format: EditFormat | None) -> tuple[str, str]:
        """``(system, user)`` for a chat worker; an edit task needs its answer format."""
        if self.edit is None:
            return self.system, self.user
        if edit_format is None:
            raise InternalError("an API edit needs an answer format")
        return self.system, f"{self.user}\n\n{self.edit_rules[edit_format]}"

    def edit_format(self, candidate: Candidate) -> EditFormat | None:
        """How this candidate answers an edit task; ``None``: not an API edit.

        The router writes it into the candidate; a candidate made elsewhere is resolved the
        same way, so the prompt, JSON mode and parser always agree.
        """
        if self.edit is None or isinstance(candidate.config, CliAgentProvider):
            return None
        return candidate.edit_format or resolve_edit_format(
            self.task.edit_format, candidate.model.edit_format,
            lines=self.edit.lines, limit=self.config.security.max_api_edit_lines,
        )  # fmt: skip

    def needs(self) -> TaskNeeds:
        rules = max((len(r) for r in self.edit_rules.values()), default=0)
        prompt_chars = len(self.system) + len(self.user) + rules
        return TaskNeeds(
            kind=self.task.kind,
            tier=self.task.tier,
            privacy=self.task.privacy,
            provider=self.task.provider,
            model=self.task.model,
            prompt_chars=prompt_chars,
            has_secrets=bool(blocking(self.findings)),
            allow_secrets=self.options.allow_secrets,
            edit_lines=self.edit.lines if self.edit else 0,
            edit_format=self.task.edit_format,
        )


def _warnings(context: Context, findings: Sequence[Finding]) -> list[str]:
    warnings = [t("context.warning.binary", path=p) for p in context.skipped_binary]
    ignored = context.skipped_ignored
    if len(ignored) > IGNORED_WARNINGS:  # one line instead of a screenful
        names = ", ".join(sorted({f for _, f in ignored}))
        warnings.append(t("context.warning.ignored_many", count=len(ignored), files=names))
    else:
        warnings += [t("context.warning.ignored", path=p, file=f) for p, f in ignored]
    warnings += [
        t("secrets.warning.found_prompt", line=f.line, kind=f.kind)
        if f.path == PROMPT_SOURCE
        else t("secrets.warning.found", path=f.path, line=f.line, kind=f.kind)
        for f in findings
    ]
    return warnings


def _prepare(
    task: TaskSpec, options: RunOptions, config: Config, env: Mapping[str, str], cwd: Path | None
) -> _Prepared:
    base = task.base_dir(Path.cwd() if cwd is None else cwd)
    if task.kind == "edit":
        gw.check_repo(base)  # no repository or no commit: a usage error before anything starts
    checks = build_verifiers(task, base_dir=base)
    context = collect_context(
        [Path(f) for f in task.context.files], globs=task.context.globs, cwd=base,
        max_bytes=config.security.max_context_bytes, ignore_file=config.security.ignore_file,
    )  # fmt: skip
    known = configured_secrets(config, env)
    findings = _scan(task.prompt, context, known)
    edit: _EditPlan | None = None
    warnings = _warnings(context, findings)
    json_output = task.output.format == "json"
    # The model is told the schema it is checked against (loaded once, by the verifier).
    schema = next((c.schema for c in checks if isinstance(c, JsonSchemaCheck) and c.schema), None)
    if task.kind == "edit":
        edit, read_only = _edit_plan(task, context, base)
        warnings += read_only
        guarded = [*edit.protected, *edit.forbidden]
        rules: dict[EditFormat, str] = {
            fmt: edit_rules(
                editable=sorted(edit.editable),
                allow_new=task.allow_new_files,
                protected=guarded,
                edit_format=fmt,
            )
            for fmt in get_args(EditFormat)
        }
        system, user = load_prompt("worker_system.md").strip(), edit_body(task.prompt, context)
        agent_user = build_agent_prompt(
            task.prompt, context, edit=True, editable=sorted(edit.editable),
            allow_new=task.allow_new_files, protected=guarded,
        )  # fmt: skip
    else:
        rules = {}
        system, user = build_ask_messages(task.prompt, context, schema, json_output=json_output)
        agent_user = build_agent_prompt(
            task.prompt, context, edit=False, schema=schema, json_output=json_output
        )
    return _Prepared(
        task, options, config, env, base, checks, context, Redactor(known),
        Redactor(known, passwords=False), findings, warnings, system, user, edit, agent_user,
        rules,
    )  # fmt: skip


def _price_targets(prep: _Prepared, conn: sqlite3.Connection) -> set[str]:
    """Providers whose price list may be fetched: in scope, enabled, consented, remote allowed.

    The request carries the provider's API key, so it never goes to a provider the user has
    not enabled, nor to one this task cannot use anyway (D-037).
    """
    needs = prep.needs()
    targets: set[str] = set()
    for name in scope(needs, prep.config):
        cfg = prep.config.providers[name]
        if needs.privacy == "local_only" and not cfg.local:
            continue
        if cfg.enabled and consent.state(conn, name, cfg) == "granted":
            targets.add(name)
    return targets


async def _route(
    prep: _Prepared,
    conn: sqlite3.Connection,
    moment: datetime,
    *,
    fetch_prices: bool,
    price_lock: asyncio.Lock | None = None,
) -> Route:
    """``price_lock``: a batch's tasks fetch price lists one at a time, so the first fetch is
    cached for the others and no task overwrites another's cache."""
    needs = prep.needs()
    profile = prep.options.profile
    if needs.provider is not None and needs.provider not in prep.config.providers:
        return route(needs, prep.config, Snapshot(moment), profile=profile)  # raises
    if fetch_prices:
        async with price_lock or contextlib.nullcontext():
            cache = await pricing.refresh(
                prep.config, moment, only=_price_targets(prep, conn), environ=prep.env
            )
    else:  # --dry-run sends nothing: use whatever prices are cached
        cache = pricing.load_cache()
    extra = (needs.provider, needs.model) if needs.provider and needs.model else None
    snapshot = take_snapshot(
        conn, prep.config, moment, environ=prep.env, price_cache=cache,
        names=scope(needs, prep.config), extra_model=extra, tags=prep.task.tags,
    )  # fmt: skip
    return route(needs, prep.config, snapshot, profile=profile)


async def plan_task(
    task: TaskSpec,
    config: Config,
    options: RunOptions | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    now: db.Clock = db.local_now,
    conn: sqlite3.Connection | None = None,
) -> DryRun:
    """``--dry-run``: the route only, no request, no budget, no run directory."""
    env = os.environ if environ is None else environ
    prep = _prepare(task, options or RunOptions(), config, env, cwd)
    state = db.connect() if conn is None else conn
    try:
        planned = await _route(prep, state, now(), fetch_prices=False)
        return DryRun(planned, tuple(prep.warnings))
    finally:
        if conn is None:
            state.close()


@dataclass(frozen=True)
class Estimate:
    """``batch --estimate``: the first request to the first candidate (Mimari §19).

    ``cost_usd`` is ``None`` when the price is not known (a code agent, a remote model
    without a price); a local model without a price costs 0. Retries, feedback and
    escalation are not included, so a run can cost more.
    """

    candidate: Candidate | None
    prompt_tokens: int
    max_output_tokens: int | None  # None: a code agent (no output limit, no price)
    cost_usd: float | None
    error: OrkestraError | None = None  # no candidate: why
    warnings: tuple[str, ...] = ()


async def estimate_task(
    task: TaskSpec,
    config: Config,
    options: RunOptions | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    now: db.Clock = db.local_now,
    conn: sqlite3.Connection | None = None,
    fetch_prices: bool = False,
    price_lock: asyncio.Lock | None = None,
) -> Estimate:
    """Tokens and cost of the task's first request; nothing is sent to a worker.

    ``fetch_prices``: refresh price lists first (before a real run); ``--estimate`` alone
    uses the cached ones, like ``--dry-run``. A task that cannot even be prepared (bad
    context file, no repository) raises, as ``run`` would.
    """
    env = os.environ if environ is None else environ
    prep = _prepare(task, options or RunOptions(), config, env, cwd)
    state = db.connect() if conn is None else conn
    try:
        planned = await _route(prep, state, now(), fetch_prices=fetch_prices, price_lock=price_lock)
    finally:
        if conn is None:
            state.close()
    warnings = tuple(prep.warnings)
    if not planned.candidates:
        return Estimate(None, 0, None, None, error=planned.error(), warnings=warnings)
    first = planned.candidates[0]
    if isinstance(first.config, CliAgentProvider):
        tokens = estimate_tokens(len(prep.agent_user))
        return Estimate(first, tokens, None, None, warnings=warnings)
    system, user = prep.messages(prep.edit_format(first))
    max_output = first.model.max_output_tokens or config.defaults.max_output_tokens
    amount = budget.estimate(len(system) + len(user), max_output, first.price)
    if first.price is not None:
        cost: float | None = amount.cost_usd
    else:
        cost = 0.0 if first.config.local else None
    return Estimate(first, amount.tokens - max_output, max_output, cost, warnings=warnings)
