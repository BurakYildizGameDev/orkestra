"""``orkestra read <files…> "<question>"``: a worker reads, the chief gets pointers
(Faz 13i-b, D-090).

The files are read the way task context is (``.orkestraignore``, binary files and the size
limit apply; an ignored file is listed, never sent) and given to a chat worker with numbered
lines. Its short answer comes back with every ``file:line`` it names checked against the
files (``pointers``). The answer is cached by the question and the files' content: the same
question on unchanged files costs nothing; a changed file is read again.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from orkestra.cache import responses
from orkestra.chief import pointers as ptr
from orkestra.chief.call import query_chief_model
from orkestra.config.schema import CliAgentProvider, Config
from orkestra.errors import UsageError
from orkestra.i18n import t
from orkestra.security.redact import Redactor, configured_secrets, secret_env_values
from orkestra.state import db
from orkestra.tasks.context import collect_context

SYSTEM = (
    "You answer a programmer's question about the files below, so that they do not have to "
    "read them. Write at most 8 short lines. Back every statement with a pointer path:line or "
    "path:start-end, using the paths exactly as given and the line numbers shown. If the files "
    "do not answer the question, say so in one line. Quote at most 3 lines of code."
)


@dataclass
class ReadResult:
    answer: str
    pointers: list[ptr.Pointer]
    model: str | None
    cached: bool
    files: list[str]
    ignored: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # binary


def read(
    paths: Sequence[Path],
    question: str,
    *,
    config: Config,
    cwd: Path,
    no_cache: bool = False,
    now: datetime | None = None,
    environ: Mapping[str, str] | None = None,
) -> ReadResult:
    context = collect_context(
        paths, max_bytes=config.security.max_context_bytes, cwd=cwd,
        ignore_file=config.security.ignore_file,
    )  # fmt: skip
    ignored = [display for display, _ in context.skipped_ignored]
    if not context.files:
        raise UsageError(t("read.error.nothing"), details=[*ignored, *context.skipped_binary])
    texts = {ptr.relative(f.path, cwd): ptr.lines(f.text) for f in context.files}
    blocks = "\n\n".join(ptr.numbered(path, lines) for path, lines in texts.items())
    user = f"Question: {question}\n\n{blocks}"
    answer, label, cached = ask(config, user, no_cache=no_cache, now=now, environ=environ)
    found = ptr.check(answer, texts, redact=redactor(config, environ))
    return ReadResult(
        answer, found, label, cached, list(texts), ignored, list(context.skipped_binary)
    )


def redactor(config: Config | None, environ: Mapping[str, str] | None) -> Redactor:
    """Masks keys the config names and variables that look like keys (also in ``find``)."""
    secrets = configured_secrets(config, environ) if config is not None else []
    return Redactor([*secrets, *secret_env_values(environ)])


def _tier_models(config: Config, tier: int) -> list[str]:
    """The chat models that can answer on ``tier``: a cached answer is reused only while
    they are the same (another model may answer better)."""
    return sorted(
        f"{name}/{m.id}" for name, p in config.providers.items() if not isinstance(
            p, CliAgentProvider) for m in p.models if m.tier <= tier
    )  # fmt: skip


def ask(
    config: Config,
    user: str,
    *,
    system: str = SYSTEM,
    no_cache: bool = False,
    now: datetime | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str | None, bool]:
    """The worker's answer to ``user`` (``read``, ``find --ask``), from the answer cache when
    the same prompt was answered before: ``(answer, model label, cached)``."""
    current = db.local_now() if now is None else now
    use_cache = config.cache.enabled and not no_cache
    models = ",".join(_tier_models(config, config.read.tier))
    key = responses.make_key(
        "read", f"tier{config.read.tier}:{models}", system, user, json_mode=False
    )
    if use_cache:
        stored = responses.load(key, now=current, ttl_days=config.cache.ttl_days)
        if stored is not None:
            try:
                data = json.loads(stored)
                return str(data["answer"]), data.get("model"), True
            except (ValueError, KeyError, TypeError):
                pass  # an old or broken entry: ask again
    answer, label = asyncio.run(
        query_chief_model(
            config, tier=config.read.tier, system=system, user=user, environ=environ,
            agents=False, work="read",
        )
    )  # fmt: skip
    answer = answer.strip()
    if use_cache:
        record = json.dumps({"answer": answer, "model": label}, ensure_ascii=False)
        responses.store(key, record, now=current, provider="read", model=label)
    return answer, label, False


def render_pointers(found: list[ptr.Pointer]) -> list[str]:
    return [
        f"  {p.pointer}  {p.line}" if p.valid else f"  {p.pointer}  ({t('read.pointer.invalid')})"
        for p in found
    ]


def render(result: ReadResult) -> str:
    lines = [result.answer]
    if result.pointers:
        lines += ["", t("read.pointers"), *render_pointers(result.pointers)]
    if result.ignored:
        lines.append(t("read.ignored", files=", ".join(result.ignored)))
    origin = t("read.cached") if result.cached else (result.model or "-")
    lines.append(t("read.footer", files=len(result.files), model=origin))
    return "\n".join(lines)


def pointers_json(found: list[ptr.Pointer]) -> list[dict[str, Any]]:
    return [{"pointer": p.pointer, "valid": p.valid, "line": p.line} for p in found]


def to_dict(result: ReadResult) -> dict[str, Any]:
    return {
        "answer": result.answer, "pointers": pointers_json(result.pointers),
        "model": result.model, "cached": result.cached, "files": result.files,
        "ignored": result.ignored, "skipped_binary": result.skipped,
    }  # fmt: skip
