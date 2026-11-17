"""``orkestra find <pattern>``: search the project, give back pointers (Faz 13i-b, D-090).

The project's files are searched the way ``map`` walks them (``.gitignore``,
``.orkestraignore``, binary files and Orkestra's own folders are left out), for a literal
text or (``--regex``) a regular expression, case-sensitive like grep. No model is needed:
up to ``find.max_hits`` hits come back one by one as ``file:line: text``; more are grouped
per file, with the file's summary from the project index (``map``) and its first hits.
With ``--ask "<question>"`` a chat worker reads the hits with a few lines around each and
answers with checked pointers. Like grep, no hit is exit code 1.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from orkestra.chief import pointers as ptr
from orkestra.chief import reader, repomap
from orkestra.config.schema import Config, FindCfg
from orkestra.errors import ConfigError, UsageError
from orkestra.i18n import t
from orkestra.tasks.context import glob_regex

TEXT_CHARS = 160
FIRST_HITS = 3  # per file, when hits are grouped
AROUND = 2  # lines around each hit that a worker reads (--ask)
ASK_HITS = 120
MAX_HITS = 5000  # the search stops there (``truncated``)
MAX_FILE_BYTES = 2_000_000  # larger files are not searched

ASK_SYSTEM = (
    "You answer a programmer's question about search hits in their project, so that they "
    "do not have to read them. Write at most 8 short lines. Back every statement with a "
    "pointer path:line, using the paths and line numbers shown. If the hits do not answer "
    "the question, say so in one line."
)


@dataclass(frozen=True)
class Hit:
    file: str
    line: int
    text: str

    @property
    def pointer(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass
class Group:
    file: str
    count: int
    summary: str | None
    first: list[Hit]


@dataclass
class FindResult:
    pattern: str
    hits: list[Hit]
    max_hits: int
    groups: list[Group] = field(default_factory=list)
    answer: str | None = None
    pointers: list[ptr.Pointer] = field(default_factory=list)
    model: str | None = None
    cached: bool = False
    truncated: bool = False

    @property
    def files(self) -> int:
        return len({h.file for h in self.hits})


def find(
    pattern: str,
    *,
    cwd: Path,
    config: Config | None,
    regex: bool = False,
    globs: Sequence[str] = (),
    max_hits: int | None = None,
    question: str | None = None,
    no_cache: bool = False,
    config_problem: str | None = None,
    now: datetime | None = None,
    environ: Mapping[str, str] | None = None,
) -> FindResult:
    if config_problem:
        # Its ignore file and its keys are unknown: searching anyway could show what the
        # user keeps out (D-091).
        raise ConfigError(config_problem)
    try:
        matcher = re.compile(pattern if regex else re.escape(pattern))
    except re.error as exc:
        raise UsageError(t("find.error.pattern", pattern=pattern, error=exc)) from exc
    settings = config.find if config is not None else FindCfg()
    limit = max_hits or settings.max_hits
    here = cwd.resolve()
    root = repomap.project_root(here)
    ignore = config.security.ignore_file if config is not None else ".orkestraignore"
    files = repomap.collect_repo_files(root, None, ignore_file=ignore).files
    wanted = [glob_regex(g) for g in globs]
    redact = reader.redactor(config, environ)
    hits: list[Hit] = []
    per_file: dict[str, list[Hit]] = {}
    texts: dict[str, list[str]] = {}  # only for --ask: the worker reads around each hit
    for path in files:
        rel = ptr.relative(path, here)
        if wanted and not any(w.fullmatch(rel) for w in wanted):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue  # a log or a data dump: not source to search
            lines = ptr.lines(path.read_bytes().decode("utf-8-sig", errors="replace"))
        except OSError:
            continue
        found = [
            Hit(rel, number, _clip(redact(line.strip())))
            for number, line in enumerate(lines, start=1)
            if matcher.search(line)
        ]
        if not found:
            continue
        hits.extend(found)
        per_file[rel] = found
        if question:
            texts[rel] = [redact(line) for line in lines]
        if len(hits) >= MAX_HITS:
            break
    result = FindResult(pattern, hits, limit, truncated=len(hits) >= MAX_HITS)
    if len(hits) > limit:
        result.groups = _groups(per_file, root, here)
    if question and hits:
        if config is None:
            raise UsageError(t("find.error.no_config"))
        user = _ask_prompt(question, pattern, hits, texts)
        answer, label, cached = reader.ask(
            config, user, system=ASK_SYSTEM, no_cache=no_cache, now=now, environ=environ
        )
        result.answer, result.model, result.cached = answer, label, cached
        result.pointers = ptr.check(answer, texts)  # texts are already masked
    return result


def _clip(text: str) -> str:
    return text if len(text) <= TEXT_CHARS else text[: TEXT_CHARS - 1] + "…"


def _groups(per_file: dict[str, list[Hit]], root: Path, here: Path) -> list[Group]:
    """Hits per file, most first, with the file's summary from the project index."""
    index = {ptr.relative(root / f.path, here): f.summary for f in repomap.read_index(root)}
    ordered = sorted(per_file.items(), key=lambda item: -len(item[1]))
    return [
        Group(name, len(found), index.get(name) or None, found[:FIRST_HITS])
        for name, found in ordered
    ]


def _ask_prompt(question: str, pattern: str, hits: list[Hit], texts: dict[str, list[str]]) -> str:
    parts = [f"Question: {question}", f"Search: {pattern} ({len(hits)} hits)"]
    for hit in hits[:ASK_HITS]:
        lines = texts[hit.file]
        start, end = max(1, hit.line - AROUND), min(len(lines), hit.line + AROUND)
        around = "\n".join(f"{n:>5}| {lines[n - 1]}" for n in range(start, end + 1))
        parts.append(f"{hit.pointer}\n{around}")
    if len(hits) > ASK_HITS:
        parts.append(f"({len(hits) - ASK_HITS} more hits not shown)")
    return "\n\n".join(parts)


def render(result: FindResult) -> str:
    lines = [t("find.header", count=len(result.hits), files=result.files, pattern=result.pattern)]
    if result.groups:
        for group in result.groups:
            about = f" — {group.summary}" if group.summary else ""
            lines.append(f"{group.file}: {group.count}{about}")
            lines.append("  " + ", ".join(h.pointer for h in group.first))
    else:
        lines += [f"{h.pointer}: {h.text}" for h in result.hits]
    if result.answer is not None:
        lines += ["", result.answer]
        if result.pointers:
            lines += [t("read.pointers"), *reader.render_pointers(result.pointers)]
    return "\n".join(lines)


def to_dict(result: FindResult) -> dict[str, Any]:
    shown = result.hits[: result.max_hits]
    return {
        "pattern": result.pattern, "total": len(result.hits), "files": result.files,
        "hits": [{"pointer": h.pointer, "file": h.file, "line": h.line, "text": h.text}
                 for h in shown],
        "groups": [{"file": g.file, "count": g.count, "summary": g.summary,
                    "first": [h.pointer for h in g.first]} for g in result.groups],
        "answer": result.answer, "pointers": reader.pointers_json(result.pointers),
        "model": result.model, "cached": result.cached, "truncated": result.truncated,
    }  # fmt: skip
