"""Task lifecycle (Mimari §8): ``ask`` tasks (``orkestra ask`` or a task file) and ``edit``
tasks answered by API workers with whole files (§8.2, Faz 5c).

1. Prepare: verifiers, context, secret scan, prompt.
2. Route (``routing/router.py``): ordered candidates; every left-out provider has a reason.
   ``--dry-run`` stops here.
3. Try the candidates in order. Per candidate, up to ``max_retries + 1`` answers:
   reserve budget → request → settle budget → verify. A failed check is sent back to the
   same model as feedback (``prompts/retry_feedback.md``) and it tries again. When its
   answers keep failing, or it says ``CANNOT_DO``, the run moves up to the next tier (same-
   tier candidates are skipped). Provider errors are retried with backoff or fail over to
   the next candidate (``routing/retry.py``). Every abandoned candidate is listed in the
   envelope's ``failovers`` (and in ``escalations`` when the next one is on a higher tier).
4. Result: ``ok``; ``failed`` (checks never passed); ``escalate`` (checks failed on tier 3,
   or the worker said it cannot do the task: the chief must take over); ``error``.

Edit tasks run in a worktree (``workspace/git_worktree.py``) that starts from the user's
current files. Every answer starts from that baseline: it is parsed and its paths checked
(``tasks/edit_format.py``; a bad answer is a failed ``edit_format`` check with feedback), its
files are written, then the verifiers run in the worktree. Afterwards only the answer's files
stay (no verifier leftovers). An answer cut off at the output limit means the file is too
large for that model: the run moves straight to tier 3. The user's checkout changes only on
``orkestra apply``; an interrupted run keeps its worktree.

Code agents (Faz 6, ``providers/cli_agent.py``) are candidates too, normally on tier 3. An
agent edits the worktree itself (``workspace-write`` sandbox) or reads the project for an
``ask`` task (``read-only``). Its change is the worktree diff against the baseline (its own
commits included); verifier leftovers are dropped the same way. The user's repository is
snapshotted around every agent run: if anything changed there, the ``workspace_scope``
check fails and the user is warned.

Every run gets ``runs/<run_id>/`` with ``task.yaml``, ``attempts/<n>/request.json``,
``attempts/<n>/response.txt``, ``attempts/<n>/verify.log``, ``output.md``, ``envelope.json``
and ``orkestra.log``, plus ``worktree.json`` and ``changes.patch`` for edit tasks (Mimari §3,
§14). Everything written there is redacted.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import secrets
import sqlite3
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, get_args

import pathspec

from orkestra import paths
from orkestra.cache import responses
from orkestra.config.loader import dump_yaml
from orkestra.config.schema import CliAgentProvider, Config, EditFormat, resolve_edit_format
from orkestra.envelope import (
    Changes,
    EnvelopeUsage,
    Escalation,
    Failover,
    ResultEnvelope,
    Status,
    summarize_text,
    to_json,
)
from orkestra.errors import (
    BudgetExhausted,
    ExitCode,
    InternalError,
    NoProviderAvailable,
    OrkestraError,
    ProviderError,
    ProviderTimeout,
    UsageError,
)
from orkestra.i18n import t
from orkestra.logging_setup import run_log
from orkestra.providers import pricing
from orkestra.providers.base import (
    AgentRequest,
    AgentResult,
    CompletionRequest,
    CompletionResult,
    Usage,
    estimate_tokens,
)
from orkestra.providers.cli_agent import create_agent
from orkestra.providers.registry import (
    ChatConfig,
    agent_timeout,
    create_chat_provider,
    request_timeout,
)
from orkestra.routing import retry
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
from orkestra.state import budget, consent, db, health
from orkestra.tasks import edit_format as ef
from orkestra.tasks.context import Context, collect_context
from orkestra.tasks.prompts import (
    build_agent_prompt,
    build_ask_messages,
    build_retry_message,
    edit_body,
    edit_rules,
    load_prompt,
)
from orkestra.tasks.spec import ForbidPaths, ProtectPaths, TaskSpec, effective_verifiers
from orkestra.verify import CheckResult, Verifier, VerifyContext, build_verifiers, run_verifiers
from orkestra.verify.base import FileChange, Message, failed, passed
from orkestra.verify.schema import JsonSchemaCheck
from orkestra.workspace import git_worktree as gw
from orkestra.workspace import service as workspaces

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


async def _sleep(seconds: float) -> None:
    """Retry backoff wait; tests replace it so they never really wait."""
    await asyncio.sleep(seconds)


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

    One instance is shared by all tasks of a batch; a single run gets its own.
    """

    def __init__(self, config: Config) -> None:
        self._limits = {name: provider.concurrency for name, provider in config.providers.items()}
        self._slots: dict[str, asyncio.Semaphore] = {}
        self.prices = asyncio.Lock()  # price list fetches, one task at a time

    def __call__(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._slots:
            self._slots[provider] = asyncio.Semaphore(self._limits.get(provider, 1))
        return self._slots[provider]


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
        names=scope(needs, prep.config), extra_model=extra,
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


async def run_task(
    task: TaskSpec,
    config: Config,
    options: RunOptions | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    now: db.Clock = db.local_now,
    conn: sqlite3.Connection | None = None,
    sleep: Sleep | None = None,
    rand: Callable[[], float] = random.random,
    policy: retry.RetryPolicy | None = None,
    slots: ProviderSlots | None = None,
    batch_id: str | None = None,
    on_start: Callable[[str], object] | None = None,
) -> TaskOutcome:
    """Run one task. A batch passes shared ``slots``, its ``batch_id`` and ``on_start``
    (called with the run id once the run is recorded) (Faz 7a)."""
    env = os.environ if environ is None else environ
    prep = _prepare(task, options or RunOptions(), config, env, cwd)
    state = db.connect() if conn is None else conn
    try:
        started_at = now()
        lock = slots.prices if slots is not None else None
        planned = await _route(prep, state, started_at, fetch_prices=True, price_lock=lock)
        if not planned.candidates:
            raise planned.error()
        runner = _TaskRun(prep, state, planned, started_at, now, clock, sleep or _sleep, rand,
                          policy or retry.RetryPolicy(),
                          slots=slots, batch_id=batch_id, on_start=on_start)  # fmt: skip
        return await runner.run()
    finally:
        if conn is None:
            state.close()


@dataclass(frozen=True)
class _Scope:
    """The user's repository and its state before a code agent ran."""

    repo: Path | None
    before: dict[str, str] | None


def _repo_of(path: Path) -> Path | None:
    try:
        return gw.repo_root(path)
    except UsageError:
        return None


@dataclass(frozen=True)
class _Answer:
    """An answer that came back but did not pass its checks."""

    candidate: Candidate
    text: str
    checks: list[CheckResult]
    result: CompletionResult


class _TaskRun:
    def __init__(
        self,
        prep: _Prepared,
        conn: sqlite3.Connection,
        planned: Route,
        started_at: datetime,
        now: db.Clock,
        clock: Callable[[], float],
        sleep: Sleep,
        rand: Callable[[], float],
        policy: retry.RetryPolicy,
        *,
        slots: ProviderSlots | None = None,
        batch_id: str | None = None,
        on_start: Callable[[str], object] | None = None,
    ) -> None:
        self.on_start = on_start
        self.prep = prep
        self.task = prep.task
        self.conn = conn
        self.route = planned
        self.started_at = started_at
        self.now = now
        self.clock = clock
        self.sleep = sleep
        self.rand = rand
        self.policy = policy
        self.slots = slots or ProviderSlots(prep.config)
        self.batch_id = batch_id
        self.run_id = new_run_id(started_at.replace(tzinfo=None))
        self.run_dir = paths.run_dir(self.run_id)
        self.attempts = 0
        retries = prep.task.limits.max_retries
        self.max_answers = 1 + (prep.config.defaults.max_retries if retries is None else retries)
        # daily_runs is per provider: one run each, however many requests it takes there.
        self.run_counted: set[str] = set()
        self.escalate_reason: str | None = None  # CANNOT_DO or a cut-off edit: for the chief
        self.rejected: _Answer | None = None  # last answer that failed its checks
        self.rejected_patch: bytes | None = None  # edit tasks: that answer's change
        self.last_problem: str | None = None  # "escalate" | "checks": which came last
        self.wt: gw.Worktree | None = None  # edit tasks
        self.workdir = prep.base_dir  # where verifiers run (inside the worktree for edits)
        self.note = ""  # the last edit answer's note
        self.edit_format: EditFormat | None = None  # the current chat candidate's answer format
        self.failovers: list[Failover] = []
        self.escalations: list[Escalation] = []
        self.used: list[Usage] = []  # every answered request of the run (envelope usage)
        self.cache_key: str | None = None  # ask tasks: the first prompt's key (Faz 8a)
        self.cache_hit = False  # the answer being judged came from the cache
        self.log = logging.getLogger("orkestra")
        self.started = clock()

    def _write(self, path: Path, text: str, *, answer: bool = False) -> None:
        """Write a run record, redacted. ``answer``: the worker's output (secrets only)."""
        redact = self.prep.redact_output if answer else self.prep.redact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(redact(text).encode("utf-8"))  # bytes: no newline translation

    def _max_output(self, candidate: Candidate) -> int:
        return candidate.model.max_output_tokens or self.prep.config.defaults.max_output_tokens

    def _completion(self, candidate: Candidate, config: ChatConfig, user: str) -> CompletionRequest:
        timeout = self.task.limits.timeout_s or request_timeout(config, self.prep.config.defaults)
        edit_format = self.prep.edit_format(candidate)
        return CompletionRequest(
            model=candidate.model.id,
            system=self.prep.messages(edit_format)[0],
            user=user,
            max_output_tokens=self._max_output(candidate),
            # SEARCH/REPLACE blocks are plain text; only whole-file edits are JSON.
            json_mode=self.task.output.format == "json" or edit_format == "whole",
            timeout_s=timeout,
        )

    async def run(self) -> TaskOutcome:
        db.record_run_start(
            self.conn, run_id=self.run_id, task_id=self.task.id, kind=self.task.kind,
            started_at=self.started_at, tags=self.task.tags, batch_id=self.batch_id,
        )  # fmt: skip
        if self.on_start is not None:
            self.on_start(self.run_id)  # a batch keeps it even if the run crashes later
        with run_log(self.run_dir, self.prep.redact) as log:
            self.log = log
            try:
                return await self._run()
            except BaseException as exc:
                # Ctrl+C or a bug: still close the run row and leave an envelope behind.
                self._crashed(exc)
                raise

    async def _run(self) -> TaskOutcome:
        self._write_task()
        if self.prep.edit is not None:
            self._open_worktree()
        self.log.info(
            "route: profile=%s tiers=%s-%s candidates=%s eliminated=%d",
            self.route.profile, *self.route.tier_range,
            [c.label for c in self.route.candidates], len(self.route.eliminated),
        )  # fmt: skip
        remaining = list(self.route.candidates)
        skipped_providers: set[str] = set()
        previous: Candidate | None = None
        while remaining:
            candidate = remaining.pop(0)
            if candidate.provider in skipped_providers:
                continue
            if health.get(self.conn, candidate.provider).is_open(self.now()):
                # Paused during this run (e.g. by our own failed retries).
                self.log.info("skipping %s: provider paused", candidate.label)
                skipped_providers.add(candidate.provider)
                continue
            if previous is not None and candidate.tier > previous.tier and self.failovers:
                last = self.failovers[-1]
                self.escalations.append(
                    Escalation(provider=last.provider, model=last.model, tier=last.tier,
                               reason=last.reason)
                )  # fmt: skip
            previous = candidate
            outcome = await self._try(candidate)
            if isinstance(outcome, TaskOutcome):
                return outcome
            action = outcome
            if action is retry.Action.SKIP_PROVIDER:
                skipped_providers.add(candidate.provider)
            elif action is retry.Action.BIGGER_CONTEXT:
                window = candidate.model.context_window
                remaining = [c for c in remaining if c.model.context_window > window]
            elif action is retry.Action.ESCALATE:
                remaining = [c for c in remaining if c.tier > candidate.tier]
            elif action is retry.Action.TOP_TIER:
                remaining = [c for c in remaining if c.tier >= TOP_TIER]
        if self.last_problem == "checks" and self.rejected is not None:
            if self.wt is not None and self.rejected_patch is not None:
                # A later candidate (e.g. an agent that crashed) may have changed the
                # worktree: the envelope must describe the answer it reports.
                gw.reset(self.wt)
                gw.restore(self.wt, self.rejected_patch)
            return self._checks_failed(self.rejected)
        if self.last_problem == "escalate":
            return self._escalate()
        return self._all_failed()

    def _open_worktree(self) -> None:
        """The edit task's worktree, starting from the user's current files (Mimari §9)."""
        wt = gw.create(self.prep.base_dir, self.run_id)
        workspaces.attach_worktree(self.conn, self.run_id, wt)
        self.wt = wt
        try:
            self.workdir = wt.path / self.prep.base_dir.relative_to(wt.repo)
        except ValueError:
            self.workdir = wt.path
        self.prep.warnings.extend(wt.warnings)
        self.log.info("worktree %s (baseline %s)", wt.path, wt.baseline[:12])

    def _write_task(self) -> None:
        data = self.task.model_dump(mode="json", by_alias=True)
        data["context"]["resolved_files"] = [f.display for f in self.prep.context.files]
        data["profile"] = self.route.profile
        self._write(self.run_dir / "task.yaml", dump_yaml(data))

    async def _try(self, candidate: Candidate) -> TaskOutcome | retry.Action:
        """One candidate: answers, checks and feedback retries, plus transport retries.

        Returns the outcome when an answer passed, otherwise what to do next.
        """
        self.cache_key = None  # set per candidate, so no other candidate's key is reused
        config = candidate.config
        if isinstance(config, CliAgentProvider):
            return await self._try_agent(candidate, config)
        provider = create_chat_provider(candidate.provider, config, self.prep.env)
        if config.budget.daily_usd is not None and candidate.price is None:
            self.prep.warnings.append(
                t("budget.warning.no_price", provider=candidate.provider, model=candidate.model.id)
            )
        self.edit_format = self.prep.edit_format(candidate)
        base_user = self.prep.messages(self.edit_format)[1]
        user = base_user
        tries = 0  # requests sent to this candidate
        transport = 0  # failed requests in a row (backoff counter)
        answers = 0
        while True:
            completion = self._completion(candidate, config, user)
            if user is base_user:  # only the task's own prompt; feedback retries are not cached
                self.cache_key = self._cache_key(candidate, completion)
                cached = self._cached(candidate, completion)
                if cached is not None:
                    # A cached answer is not one of the worker's answers (max_retries): if it
                    # fails the checks now, it is dropped and the worker is asked.
                    attempt_dir = self._cache_attempt(candidate)
                    verdict = await self._answered(
                        candidate, cached, attempt_dir, tries, answers, completion, base_user
                    )
                    self.cache_hit = False
                    if isinstance(verdict, TaskOutcome):
                        return verdict
                    responses.forget(self.cache_key or "")
                    self.log.info("cached answer failed its checks; dropped")
                    if not isinstance(verdict, str):
                        verdict = base_user  # nothing to feed back: ask the task itself
                    user = verdict
                    continue
            prompt_chars = len(completion.system) + len(completion.user)
            amount = budget.estimate(
                prompt_chars, completion.max_output_tokens, candidate.price,
                runs=0 if candidate.provider in self.run_counted else 1,
            )  # fmt: skip
            # Wait for the provider (its concurrency) before reserving budget, and check its
            # health again after the wait: another task may have paused it meanwhile (D-054).
            slot = self.slots(candidate.provider)
            await slot.acquire()
            backoff: float | None = None
            result: CompletionResult | None = None
            try:
                paused = self._paused(candidate, tries)
                if paused is not None:
                    return paused
                try:
                    reservation = budget.reserve(
                        self.conn, provider=candidate.provider, model=candidate.model.id,
                        run_id=self.run_id, budget=candidate.config.budget, amount=amount,
                        now=self.now(),
                    )  # fmt: skip
                except BudgetExhausted as exc:  # nothing was sent: not an attempt
                    return self._fail(candidate, exc, tries, retry.Action.NEXT)
                self.run_counted.add(candidate.provider)
                self.attempts += 1
                tries += 1
                attempt_dir = self.run_dir / "attempts" / str(self.attempts)
                self._write(
                    attempt_dir / "request.json",
                    json.dumps({"provider": candidate.provider, **asdict(completion)}, indent=2),
                )
                self.log.info(
                    "attempt %d: %s (try %d%s)", self.attempts, candidate.label, tries,
                    f", edit_format {self.edit_format}" if self.edit_format else "",
                )  # fmt: skip
                try:
                    result = await provider.complete(completion)
                except ProviderError as exc:
                    if isinstance(exc, ProviderTimeout):
                        # The provider may have processed (and billed) it: keep the estimate.
                        budget.settle_as_reserved(self.conn, reservation, now=self.now())
                    else:
                        budget.settle(
                            self.conn, reservation, prompt_tokens=0, completion_tokens=0,
                            cost_usd=0.0, estimated=False, now=self.now(),
                        )  # fmt: skip
                    state = health.record_failure(self.conn, candidate.provider, exc, self.now())
                    self.log.warning(
                        "attempt %d failed: %s %s (failures in a row: %d)",
                        self.attempts, type(exc).__name__, exc.message,
                        state.consecutive_failures,
                    )  # fmt: skip
                    transport += 1
                    action = retry.classify(exc)
                    if action is retry.Action.RETRY and not state.is_open(self.now()):
                        backoff = retry.delay(transport, exc, self.policy, self.rand)
                    if backoff is None:
                        if action is retry.Action.RETRY:
                            action = retry.give_up(exc)
                        return self._fail(candidate, exc, tries, action)
                except BaseException:
                    budget.release(self.conn, reservation)  # interrupted: nothing to pay for
                    self.log.warning("interrupted; reservation released")
                    raise
            finally:
                slot.release()
            if backoff is not None:
                self.log.info("retrying %s in %.2fs", candidate.label, backoff)
                await self.sleep(backoff)  # the slot is free for other tasks meanwhile
                continue
            assert result is not None
            transport = 0
            usage = self._actual_usage(prompt_chars, candidate, result)
            budget.settle(
                self.conn, reservation, prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens, cost_usd=usage.cost_usd,
                estimated=usage.estimated, now=self.now(),
            )  # fmt: skip
            health.record_success(self.conn, candidate.provider)
            self.used.append(usage)
            answers += 1
            verdict = await self._answered(
                candidate, result, attempt_dir, tries, answers, completion, base_user
            )
            if not isinstance(verdict, str):
                return verdict
            user = verdict

    async def _answered(
        self,
        candidate: Candidate,
        result: CompletionResult,
        attempt_dir: Path,
        tries: int,
        answers: int,
        completion: CompletionRequest,
        base_user: str,
    ) -> TaskOutcome | retry.Action | str:
        """A chat worker's answer (sent or from the cache): refusal, cut-off, checks."""
        self._write(attempt_dir / "response.txt", result.text, answer=True)
        reason = _cannot_do(result.text)
        if reason is None and self.edit_format == "whole":
            # JSON mode: {"cannot_do": "..."}. SEARCH/REPLACE answers hold raw code, where
            # such a literal is content, not a refusal.
            reason = ef.cannot_do(result.text)
        if reason is not None:
            self.escalate_reason = t("ask.cannot_do", reason=reason or "-")
            self.last_problem = "escalate"
            return self._fail(candidate, None, tries, retry.Action.ESCALATE, reason=reason)
        if self.prep.edit is not None and result.raw_finish_reason == "length":
            # Whole files did not fit into the output limit: feedback cannot fix that.
            message = t("edit.truncated", tokens=completion.max_output_tokens)
            self.escalate_reason, self.last_problem = message, "escalate"
            return self._fail(candidate, None, tries, retry.Action.TOP_TIER, reason=message,
                              error=OUTPUT_TRUNCATED)  # fmt: skip
        checks = await self._verify(result.text, attempt_dir)
        return await self._judge(
            candidate, result, checks, tries, answers, completion.max_output_tokens, base_user
        )

    # --- answer cache (Faz 8a, Mimari §19) -------------------------------------------------

    def _cache_key(self, candidate: Candidate, completion: CompletionRequest) -> str | None:
        """The key of this prompt, when answers of this task may be cached at all. The checks
        are part of it: an answer that passed one task's checks says nothing about another's."""
        settings = self.prep.config.cache
        if self.task.kind != "ask" or not settings.enabled or self.prep.options.no_cache:
            return None
        checks = self.task.model_dump(mode="json", include={"verify", "verify_defaults"})
        return responses.make_key(
            candidate.provider, candidate.model.id, completion.system, completion.user,
            json_mode=completion.json_mode, checks=checks,
        )  # fmt: skip

    def _cached(
        self, candidate: Candidate, completion: CompletionRequest
    ) -> CompletionResult | None:
        if self.cache_key is None:
            return None
        ttl = self.prep.config.cache.ttl_days
        text = responses.load(self.cache_key, now=self.now(), ttl_days=ttl)
        if text is None:
            return None
        self.log.info("answer for %s from the cache", candidate.label)
        self.cache_hit = True
        self.used.append(Usage(0, 0, 0.0))  # nothing was sent: nothing used, nothing paid
        return CompletionResult(text, Usage(0, 0, 0.0), "stop")

    def _cache_attempt(self, candidate: Candidate) -> Path:
        """The records of a cached answer: an attempt that sent nothing."""
        self.attempts += 1
        attempt_dir = self.run_dir / "attempts" / str(self.attempts)
        record = {"provider": candidate.provider, "cached": True}
        self._write(attempt_dir / "request.json", json.dumps(record, indent=2))
        return attempt_dir

    def _remember(self, candidate: Candidate, text: str) -> None:
        """Store an answer that passed its checks: a chat worker's answer to this candidate's
        own key, never one that came from the cache or from a code agent."""
        if (
            self.cache_key is None
            or self.cache_hit
            or isinstance(candidate.config, CliAgentProvider)
        ):
            return
        responses.store(
            self.cache_key, self.prep.redact_output(text), now=self.now(),
            provider=candidate.provider, model=candidate.model.id,
        )  # fmt: skip

    async def _judge(
        self,
        candidate: Candidate,
        result: CompletionResult,
        checks: list[CheckResult],
        tries: int,
        answers: int,
        limit: int,
        base_prompt: str,
    ) -> TaskOutcome | retry.Action | str:
        """Success, giving up on the candidate, or the next prompt (with feedback)."""
        if all(c.result.ok for c in checks):
            return await self._succeed(candidate, limit, result, checks)

        self.rejected = _Answer(candidate, result.text, checks, result)
        self.last_problem = "checks"
        if self.wt is not None:
            self.rejected_patch = gw.diff(self.wt).patch
        failures = [c.feedback for c in checks if not c.result.ok]
        self.log.info("attempt %d failed checks: %s", self.attempts, failures)
        if answers >= self.max_answers:
            names = ", ".join(c.result.type for c in checks if not c.result.ok)
            message = t("verify.failed", checks=names)
            return self._fail(candidate, None, tries, retry.Action.ESCALATE, reason=message,
                              error=VERIFICATION_FAILED)  # fmt: skip
        # Feedback goes to a model: mask everything secret, as in the records. An API worker's
        # answer is undone before the retry; a code agent continues from its change instead
        # (``AGENT_CONTINUE``), so only chat workers are told their change was discarded.
        api_edit = self.prep.edit is not None and not isinstance(candidate.config, CliAgentProvider)
        return build_retry_message(
            base_prompt,
            self.prep.redact_output(result.text),
            [self.prep.redact(f) for f in failures],
            edit=api_edit,
        )

    async def _try_agent(
        self, candidate: Candidate, cfg: CliAgentProvider
    ) -> TaskOutcome | retry.Action:
        """A code agent: runs, checks and feedback runs (no transport retries)."""
        try:
            agent = create_agent(candidate.provider, cfg, self.prep.env)
        except ProviderError as exc:  # not installed
            return self._fail(candidate, exc, 0, retry.classify(exc))
        timeout = self.task.limits.timeout_s or agent_timeout(cfg, self.prep.config.defaults)
        repo = self.wt.repo if self.wt is not None else _repo_of(self.prep.base_dir)
        prompt = self.prep.agent_user
        tries = answers = 0
        while True:
            amount = budget.estimate(
                len(prompt), 0, None, runs=0 if candidate.provider in self.run_counted else 1
            )
            # As for chat workers: the slot first, then health and budget (D-054).
            async with self.slots(candidate.provider):
                paused = self._paused(candidate, tries)
                if paused is not None:
                    return paused
                try:
                    reservation = budget.reserve(
                        self.conn, provider=candidate.provider, model=candidate.model.id,
                        run_id=self.run_id, budget=cfg.budget, amount=amount, now=self.now(),
                    )  # fmt: skip
                except BudgetExhausted as exc:
                    return self._fail(candidate, exc, tries, retry.Action.NEXT)
                self.run_counted.add(candidate.provider)
                self.attempts += 1
                tries += 1
                attempt_dir = self.run_dir / "attempts" / str(self.attempts)
                attempt_dir.mkdir(parents=True, exist_ok=True)
                req = AgentRequest(
                    prompt=prompt,
                    workdir=self.workdir,
                    model=self.task.model or cfg.model,
                    sandbox="workspace-write" if self.wt is not None else "read-only",
                    timeout_s=timeout,
                    output_file=attempt_dir / "agent_output.md",
                )
                self._write(
                    attempt_dir / "request.json",
                    json.dumps({"provider": candidate.provider, "kind": cfg.kind,
                                **asdict(req)}, indent=2, default=str),
                )  # fmt: skip
                self.log.info(
                    "attempt %d: %s (agent, try %d)", self.attempts, candidate.label, tries
                )
                if self.wt is not None and tries == 1:
                    gw.reset(self.wt)  # a new candidate starts from the user's files
                before = gw.status_snapshot(repo) if repo is not None else None
                scope = _Scope(repo, before)
                try:
                    result = await agent.run(req)
                except ProviderError as exc:
                    if isinstance(exc, ProviderTimeout):
                        budget.settle_as_reserved(self.conn, reservation, now=self.now())
                    else:
                        budget.settle(
                            self.conn, reservation, prompt_tokens=0, completion_tokens=0,
                            cost_usd=0.0, estimated=False, now=self.now(),
                        )  # fmt: skip
                    health.record_failure(self.conn, candidate.provider, exc, self.now())
                    self.log.warning("attempt %d failed: %s %s", self.attempts,
                                     type(exc).__name__, exc.message)  # fmt: skip
                    self._scope_checks(scope)  # a crashed agent may still have written outside
                    action = retry.classify(exc)
                    if action is retry.Action.RETRY:
                        action = retry.give_up(exc)
                    return self._fail(candidate, exc, tries, action)
                except BaseException:
                    budget.release(self.conn, reservation)  # interrupted: nothing to pay for
                    self.log.warning("interrupted; reservation released")
                    raise
            usage = self._agent_usage(len(prompt), result)
            budget.settle(
                self.conn, reservation, prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens, cost_usd=None,
                estimated=True, now=self.now(),
            )  # fmt: skip
            health.record_success(self.conn, candidate.provider)
            self.used.append(usage)
            text = result.final_message
            self._write(attempt_dir / "response.txt", text, answer=True)
            reason = _cannot_do(text)
            if reason is not None:
                self._scope_checks(scope)
                self.escalate_reason = t("ask.cannot_do", reason=reason or "-")
                self.last_problem = "escalate"
                return self._fail(candidate, None, tries, retry.Action.ESCALATE, reason=reason)
            answers += 1
            checks = await self._verify(text, attempt_dir, scope)
            verdict = await self._judge(
                candidate, CompletionResult(text, usage, None), checks, tries, answers,
                self._max_output(candidate), self.prep.agent_user,
            )  # fmt: skip

            if not isinstance(verdict, str):
                return verdict
            # Feedback runs continue from the agent's change (restored after the checks).
            prompt = f"{verdict}\n\n{AGENT_CONTINUE}" if self.wt is not None else verdict

    def _agent_usage(self, prompt_chars: int, result: AgentResult) -> Usage:
        reported = result.usage
        prompt = reported.prompt_tokens
        completion = reported.completion_tokens
        return Usage(
            prompt if prompt is not None else estimate_tokens(prompt_chars),
            completion if completion is not None else estimate_tokens(len(result.final_message)),
            None,
            estimated=True,
        )

    def _scope_checks(self, scope: _Scope | None) -> list[CheckResult]:
        """Did the agent write into the user's repository? (Snapshots around the run.)"""
        if scope is None or scope.repo is None or scope.before is None:
            return []
        after = gw.status_snapshot(scope.repo)
        keys = scope.before.keys() | after.keys()
        changed = sorted(k for k in keys if scope.before.get(k) != after.get(k))
        if not changed:
            return [passed(SCOPE_CHECK)]
        shown = ", ".join(changed[:SCOPE_FILES]) + (", …" if len(changed) > SCOPE_FILES else "")
        self.prep.warnings.append(t("agent.warning.outside", repo=scope.repo, files=shown))
        self.log.warning("files outside the worktree changed: %s", shown)
        return [failed(SCOPE_CHECK, Message("agent.error.outside", {"files": shown}))]

    async def _verify(
        self, text: str, attempt_dir: Path, scope: _Scope | None = None
    ) -> list[CheckResult]:
        """``scope`` is set for code agents (they write themselves; see ``_scope_checks``)."""
        if self.wt is not None and scope is not None:
            checks = await self._check_agent_edit(self.wt, text, scope)
        elif self.wt is not None:
            checks = await self._check_edit(self.wt, text)
        else:
            checks = self._scope_checks(scope)
            if self.prep.checks:
                ctx = VerifyContext(workdir=self.prep.base_dir, output=text)
                checks += await run_verifiers(self.prep.checks, ctx)
            if not checks:
                return []
        log = "\n".join(
            f"== {c.result.type}: {'ok' if c.result.ok else 'FAIL'} ==\n{c.log or c.result.detail}"
            for c in checks
        )
        self._write(attempt_dir / "verify.log", log + "\n")
        return checks

    async def _check_edit(self, wt: gw.Worktree, text: str) -> list[CheckResult]:
        """Write an edit answer into the worktree (from the baseline) and verify it."""
        assert self.prep.edit is not None
        gw.reset(wt)  # every answer starts from the user's files, not the last answer
        blocks: ef.ReplaceAnswer | None = None
        try:
            if self.edit_format == "replace":
                blocks = ef.parse_replace(text, known=self.prep.edit.editable)
                answer = ef.paths_only(blocks)  # paths are checked before any file is read
            else:
                answer = ef.parse(text)
        except ef.EditFormatError as exc:
            return [failed(ef.FORMAT_CHECK, exc.problem)]
        rels = [rel for e in answer.files if (rel := ef.normalize_path(e.path)) is not None]
        problems = ef.check_paths(
            answer, self.workdir, editable=self.prep.edit.editable,
            allow_new=self.task.allow_new_files, forbidden=self.prep.edit.forbidden,
            protected=self.prep.edit.protected, ignored=gw.ignored(self.workdir, rels),
        )  # fmt: skip
        if problems:
            return [failed(ef.FORMAT_CHECK, problems)]
        try:
            if blocks is not None:
                answer = ef.resolve_replace(blocks, self.workdir)  # whole files, in memory
            ef.write(answer, self.workdir)
        except ef.EditFormatError as exc:
            return [failed(ef.FORMAT_CHECK, exc.problem)]
        self.note = answer.note
        ctx = VerifyContext(workdir=self.workdir, output=text, changes=self._changes(wt))
        checks = await run_verifiers(self.prep.checks, ctx) if self.prep.checks else []
        # Verifier commands leave files behind (__pycache__, build output): keep the answer only.
        gw.reset(wt)
        ef.write(answer, self.workdir)
        return checks

    async def _check_agent_edit(
        self, wt: gw.Worktree, text: str, scope: _Scope
    ) -> list[CheckResult]:
        """Verify what an agent changed in the worktree; keep only its change afterwards."""
        outside = self._scope_checks(scope)
        change = gw.diff(wt)  # against the baseline, so the agent's own commits count too
        self.note = text
        ctx = VerifyContext(workdir=self.workdir, output=text, changes=self._changes(wt, change))
        checks = await run_verifiers(self.prep.checks, ctx) if self.prep.checks else []
        gw.reset(wt)  # drop what the verifiers left behind
        gw.restore(wt, change.patch)
        return [*outside, *checks]

    def _relative(self, wt: gw.Worktree, path: str) -> str:
        """A repository path as the task sees it (relative to its base directory)."""
        if self.workdir == wt.path:
            return path
        return Path(os.path.relpath(wt.path / path, self.workdir)).as_posix()

    def _changes(
        self, wt: gw.Worktree, change: gw.ChangeSet | None = None
    ) -> tuple[FileChange, ...]:
        files = (change or gw.diff(wt)).files
        return tuple(replace(c, path=self._relative(wt, c.path)) for c in files)

    def _edit_result(self, wt: gw.Worktree) -> tuple[Changes, str]:
        """The envelope's ``changes`` (``changes.patch`` written) and the rule-based summary."""
        change = gw.diff(wt)
        patch_path: str | None = None
        if change.patch:
            path = self.run_dir / workspaces.PATCH_FILE
            self._write(path, change.patch.decode("utf-8", errors="replace"), answer=True)
            patch_path = str(path)
        insertions = sum(c.insertions for c in change.files)
        deletions = sum(c.deletions for c in change.files)
        names = [self._relative(wt, c.path) for c in change.files]
        shown = ", ".join(names[:SUMMARY_FILES]) + (", …" if len(names) > SUMMARY_FILES else "")
        summary = t("edit.summary", count=len(names), insertions=insertions,
                    deletions=deletions, files=shown or "-")  # fmt: skip
        note = " ".join(self.prep.redact(self.note).split())[:NOTE_CHARS]
        changes = Changes(files=len(names), insertions=insertions, deletions=deletions,
                          patch_path=patch_path)  # fmt: skip
        return changes, f"{summary} — {note}" if note else summary

    def _actual_usage(
        self, prompt_chars: int, candidate: Candidate, result: CompletionResult
    ) -> Usage:
        """What the request used, for the budget and the envelope.

        Tokens the provider did not report are estimated from the text; a cost it did not
        report is priced with the model's resolved price (config, price list or history).
        """
        reported = result.usage
        estimated = reported.estimated
        prompt = reported.prompt_tokens
        completion = reported.completion_tokens
        if prompt is None:
            prompt, estimated = estimate_tokens(prompt_chars), True
        if completion is None:
            completion, estimated = estimate_tokens(len(result.text)), True
        cost = reported.cost_usd
        if cost is None and candidate.price is not None:
            cost = candidate.price.cost(prompt, completion)
            estimated = estimated or candidate.price.source == "history"
        return Usage(prompt, completion, cost, estimated)

    def _paused(self, candidate: Candidate, tries: int) -> retry.Action | None:
        """Give up on a provider that another task paused while this one waited for a slot."""
        state = health.get(self.conn, candidate.provider)
        if state.open_until is None or not state.is_open(self.now()):
            return None
        reason = t(
            "select.reason.circuit_open", name=candidate.provider,
            until=state.open_until.strftime("%H:%M"), error=state.last_error or "-",
        )  # fmt: skip
        return self._fail(candidate, None, tries, retry.Action.NEXT, reason=reason,
                          error="CircuitOpen")  # fmt: skip

    def _fail(
        self,
        candidate: Candidate,
        exc: ProviderError | BudgetExhausted | None,
        tries: int,
        action: retry.Action,
        *,
        reason: str | None = None,
        error: str = "CannotDo",
    ) -> retry.Action:
        """Record an abandoned candidate. Without ``exc``: CANNOT_DO or failed checks."""
        name = type(exc).__name__ if exc is not None else error
        if exc is not None:
            message = exc.message
        elif error == "CannotDo":
            message = t("ask.cannot_do", reason=reason or "-")
        else:
            message = reason or "-"
        self.failovers.append(
            Failover(
                provider=candidate.provider,
                model=candidate.model.id,
                tier=candidate.tier,
                error=name,
                reason=self.prep.redact(message),
                attempts=tries,
            )
        )
        self.log.warning("giving up on %s: %s → %s", candidate.label, name, action.value)
        return action

    def _base(self, candidate: Candidate | None) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task.id,
            "edit_format": self.prep.edit_format(candidate) if candidate else None,
            "provider": candidate.provider if candidate else None,
            "model": candidate.model.id if candidate else None,
            "tier": candidate.tier if candidate else None,
            "attempts": self.attempts,
            "escalations": self.escalations,
            "failovers": self.failovers,
        }

    def _answer_envelope(
        self, answer: _Answer, status: Status, completion_limit: int
    ) -> tuple[ResultEnvelope, str]:
        """Envelope for an answer that is kept (passed, or the last one that failed)."""
        # Files and the terminal get the answer with real secrets masked; checks saw the
        # answer itself, so masking can never break valid JSON.
        text = self.prep.redact_output(answer.text)
        output_path = self.run_dir / "output.md"
        self._write(output_path, text, answer=True)
        if answer.result.raw_finish_reason == "length":
            self.prep.warnings.append(t("ask.warning.truncated", tokens=completion_limit))
            self.log.warning("output hit max_output_tokens=%d", completion_limit)
        changes: Changes | None = None
        if self.wt is not None:
            changes, summary = self._edit_result(self.wt)
            if not changes.files:
                self._drop_worktree()
        else:
            summary = summarize_text(self.prep.redact(text), str(output_path))
        envelope = ResultEnvelope(
            **self._base(answer.candidate),
            status=status,
            summary=summary,
            changes=changes,
            # Command output can echo secrets from the environment: mask like the records.
            verification=[
                c.result.model_copy(update={"detail": self.prep.redact(c.result.detail)})
                for c in answer.checks
            ],
            output_path=str(output_path),
            usage=self._total_usage(),
            duration_s=self._duration(),
        )
        return envelope, text

    async def _succeed(
        self,
        candidate: Candidate,
        limit: int,
        result: CompletionResult,
        checks: list[CheckResult],
    ) -> TaskOutcome:
        answer = _Answer(candidate, result.text, checks, result)
        envelope, text = self._answer_envelope(answer, "ok", limit)
        if self.cache_hit:
            envelope = envelope.model_copy(update={"cached": True})
        self._remember(candidate, result.text)
        if (
            self.prep.config.review.auto
            and self.wt is not None
            and envelope.changes is not None
            and envelope.changes.files > 0
        ):
            try:
                from orkestra.chief import review
                from orkestra.envelope import EnvelopeReview

                report = await review.review_run(self.run_id, self.prep.config)
                envelope = envelope.model_copy(
                    update={
                        "review": EnvelopeReview(risk=report.risk, flags_count=len(report.flags))
                    }
                )
            except Exception as exc:
                self.log.warning("automatic review failed: %s", exc)
        return self._finish(envelope, text, 0)

    def _checks_failed(self, answer: _Answer) -> TaskOutcome:
        """No answer passed. On tier 3 there is nothing left to try: the chief takes over."""
        status: Status = "escalate" if answer.candidate.tier >= TOP_TIER else "failed"
        limit = self._max_output(answer.candidate)
        envelope, text = self._answer_envelope(answer, status, limit)
        return self._finish(envelope, text, int(ExitCode.TASK_FAILED))

    def _total_usage(self) -> EnvelopeUsage:
        """Everything the run's answers used: retries and earlier candidates are paid too."""
        if not self.used:
            return EnvelopeUsage()
        costs = [u.cost_usd for u in self.used if u.cost_usd is not None]
        return EnvelopeUsage(
            prompt_tokens=sum(u.prompt_tokens or 0 for u in self.used),
            completion_tokens=sum(u.completion_tokens or 0 for u in self.used),
            cost_usd=sum(costs) if costs else None,
        )

    def _duration(self) -> float:
        return round(self.clock() - self.started, 3)

    def _drop_worktree(self) -> None:
        """An edit run that ends without a change keeps no worktree (best effort)."""
        if self.wt is None:
            return
        try:
            gw.remove(self.wt)
            gw.save_record(self.run_dir, self.wt, state="discarded")
        except (OrkestraError, OSError) as exc:
            self.log.warning("could not remove the worktree %s: %s", self.wt.path, exc)

    def _escalate(self) -> TaskOutcome:
        """CANNOT_DO or a cut-off edit, and no higher tier was left (or answered): exit code 1."""
        self._drop_worktree()  # a rejected answer may be in it; the envelope reports none
        reason = self.escalate_reason or t("ask.cannot_do", reason="-")
        envelope = ResultEnvelope(
            **self._base(None),
            status="escalate",
            summary=self.prep.redact(reason),
            duration_s=self._duration(),
        )
        return self._finish(envelope, None, int(ExitCode.TASK_FAILED))

    def _all_failed(self) -> TaskOutcome:
        self._drop_worktree()
        error = NoProviderAvailable(t("route.all_failed", count=len(self.failovers)))
        envelope = ResultEnvelope(
            **self._base(None),
            status="error",
            error=error.message,
            duration_s=self._duration(),
        )
        return self._finish(envelope, None, int(error.exit_code))

    def _crashed(self, exc: BaseException) -> None:
        """Best effort after an interrupt or a bug; never hides the original exception."""
        detail = (
            t("ask.interrupted")
            if isinstance(exc, KeyboardInterrupt | asyncio.CancelledError)
            else f"{type(exc).__name__}: {str(exc)[:300]}"
        )
        envelope = ResultEnvelope(
            **self._base(None), status="error", error=detail, duration_s=self._duration()
        )
        try:
            self._finish(envelope, None, int(ExitCode.INTERNAL))
        except Exception:  # the database or disk may be what failed
            self.log.exception("could not record the failed run")

    def _finish(self, envelope: ResultEnvelope, output: str | None, code: int) -> TaskOutcome:
        text = to_json(envelope)
        self._write(self.run_dir / "envelope.json", text)
        db.record_run_end(
            self.conn,
            self.run_id,
            status=envelope.status,
            provider=envelope.provider,
            model=envelope.model,
            tier=envelope.tier,
            attempts=envelope.attempts,
            finished_at=self.now(),
            duration_s=envelope.duration_s,
            worker_output_tokens=envelope.usage.completion_tokens,
            envelope_chars=len(text),
        )
        self.log.info(
            "finished status=%s exit=%s attempts=%d", envelope.status, code, self.attempts
        )
        return TaskOutcome(envelope, output, code, tuple(self.prep.warnings))
