"""A run's state and its records: the envelope, usage, duration, the worktree's change and
how a run ends (``ok`` / ``failed`` / ``escalate`` / ``error`` / crashed). ``runner._TaskRun``
adds the attempts on top (düzeltme-fable b, D-106: moved out of ``runner.py``).

Shared with ``runner`` and ``prepare`` despite the underscore: ``_Answer`` and the
``_Prepared`` / ``_cannot_do`` names it imports. Change them together.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from orkestra import paths
from orkestra.cache import responses
from orkestra.config.schema import CliAgentProvider, EditFormat
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
    ExitCode,
    NoProviderAvailable,
    OrkestraError,
)
from orkestra.i18n import t
from orkestra.providers.base import (
    CompletionRequest,
    CompletionResult,
    Usage,
)
from orkestra.routing import retry
from orkestra.routing.router import (
    Candidate,
    Route,
)
from orkestra.state import db
from orkestra.tasks.prepare import (
    NOTE_CHARS,
    SUMMARY_FILES,
    TOP_TIER,
    ProviderSlots,
    Sleep,
    TaskOutcome,
    _Prepared,
    new_run_id,
)
from orkestra.verify import CheckResult
from orkestra.verify.base import FileChange
from orkestra.workspace import git_worktree as gw
from orkestra.workspace import service as workspaces


@dataclass(frozen=True)
class _Answer:
    """An answer that came back but did not pass its checks."""

    candidate: Candidate
    text: str
    checks: list[CheckResult]
    result: CompletionResult


class RunRecord:
    """State shared by every step of one run, and the code that writes its results."""

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
        self.last_failures: frozenset[tuple[int, str, str]] | None = None  # Faz 13r-b2
        self.partial_dropped = False  # Faz 13r-b3
        self.continuation_note: str | None = None  # Faz 13r-b3
        self.last_verify_failures: list[str] = []  # masked; continuation note (D-135)
        self.log = logging.getLogger("orkestra")
        self.started = clock()

    def _write(self, path: Path, text: str, *, answer: bool = False) -> None:
        """Write a run record, redacted. ``answer``: the worker's output (secrets only)."""
        redact = self.prep.redact_output if answer else self.prep.redact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(redact(text).encode("utf-8"))  # bytes: no newline translation

    def _max_output(self, candidate: Candidate) -> int:
        return candidate.model.max_output_tokens or self.prep.config.defaults.max_output_tokens

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

    def _base(self, candidate: Candidate | None) -> dict[str, Any]:
        base: dict[str, Any] = {
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
        if self.prep.envelope_warnings:
            base["warnings"] = list(self.prep.envelope_warnings)
        if self.partial_dropped:
            base["partial_dropped"] = True
        return base

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

    async def _auto_review(self, envelope: ResultEnvelope) -> ResultEnvelope:
        """``review.auto``: review the change with this run's provider slots; the run stays
        ``ok`` without a review when that fails, and its duration includes it (D-062)."""
        from orkestra.chief import review  # review imports tasks.runner, which imports this

        try:
            report = await review.review_run(
                self.run_id, self.prep.config, slots=self.slots, conn=self.conn,
                author=envelope.provider,
            )  # fmt: skip
        except OrkestraError as exc:
            self.log.warning("automatic review failed: %s %s", type(exc).__name__, exc.message)
            return envelope.model_copy(update={"duration_s": self._duration()})
        found = review.envelope_review(report)
        return envelope.model_copy(update={"review": found, "duration_s": self._duration()})

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
