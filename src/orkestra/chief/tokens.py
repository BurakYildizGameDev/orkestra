"""Where a Claude Code session's tokens go (Faz 13h, D-086): ``orkestra tokens``.

Claude Code writes every session to ``<claude home>/projects/<project>/<session>.jsonl``. Each
API request is an ``assistant`` message with its ``usage`` (written once per content block,
so the same message id appears several times and is counted once, with its last usage); tool
results come back in ``user`` entries as ``tool_result`` blocks.

What a tool call costs is more than its size: its result is written to the prompt cache once
and then read again with every later request, until the session ends or is compacted. So a
call's estimated cost is ``tokens * cache_write + tokens * cache_read * rereads`` (raw:
``tokens * (1 + rereads)``). Sizes are estimates (4 characters ≈ 1 token); the session totals
are the measured ``usage``. Unknown entries and fields are skipped, unreadable lines counted,
so a newer transcript format degrades instead of failing. Nothing here costs any quota.

Labels never carry personal paths: files are shown relative to the session's working
directory (else by name), commands with the working directory as ``.`` and home as ``~``.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from orkestra.config import loader
from orkestra.config.schema import TokensCfg, TokenWeights
from orkestra.errors import UsageError
from orkestra.i18n import t

CHARS_PER_TOKEN = 4
LABEL_CHARS = 60
SHORT_LINES = 10  # "what if this result were 10 lines"
REBUILD_MIN = 2000  # tokens no longer read from the cache that count as a cache miss
MIN_SCALE, MAX_SCALE = 0.25, 4.0  # calibration limits
GROWTH_POINTS = 5

CATEGORIES: dict[str, tuple[str, ...]] = {
    "read": ("Read", "Grep", "Glob", "LS", "NotebookRead", "WebFetch", "WebSearch"),
    "command": ("Bash", "PowerShell", "BashOutput", "Monitor", "KillShell"),
    "write": ("Edit", "Write", "MultiEdit", "NotebookEdit"),
    "agent": ("Agent", "Task", "Skill", "SendMessage"),
}
_CATEGORY = {tool: kind for kind, tools in CATEGORIES.items() for tool in tools}
_INPUT_COUNTS = ("write", "agent")  # what these send (file contents, prompts) stays in context
KINDS = (
    "read", "command", "write", "agent", "other", "replies", "messages", "output", "baseline",
    "rebuild", "rest",
)  # fmt: skip
ITEM_KINDS = ("replies", "messages")  # context that is not a tool call: not in the top list
_PATH_KEYS = ("file_path", "notebook_path", "path")
_TEXT_KEYS = {
    "Grep": "pattern", "Glob": "pattern", "Agent": "description", "Task": "description",
    "Skill": "skill", "WebFetch": "url", "WebSearch": "query",
}  # fmt: skip


@dataclass
class Usage:
    input: int = 0
    cache_write: int = 0
    cache_read: int = 0
    output: int = 0

    @property
    def context(self) -> int:
        """What the request sent: the size of the context at that point."""
        return self.input + self.cache_write + self.cache_read

    @property
    def raw(self) -> int:
        return self.context + self.output

    def weighted(self, w: TokenWeights) -> float:
        return (self.input * w.input + self.cache_write * w.cache_write
                + self.cache_read * w.cache_read + self.output * w.output)  # fmt: skip

    def add(self, other: Usage) -> None:
        self.input += other.input
        self.cache_write += other.cache_write
        self.cache_read += other.cache_read
        self.output += other.output


@dataclass
class Call:
    id: str
    tool: str
    label: str
    turn: int  # the request that asked for it
    category: str
    input_chars: int = 0
    result_chars: int = 0
    lines: int = 0
    sent: bool = False  # a later request carried its result
    rereads: int = 0  # later requests that read it from the cache
    scale: float = 1.0  # the session's measured / estimated new context (calibration)

    @property
    def tokens(self) -> int:
        chars = self.result_chars + (self.input_chars if self.category in _INPUT_COUNTS else 0)
        return round(chars / CHARS_PER_TOKEN * self.scale)

    def raw(self, w: TokenWeights) -> int:
        return self.tokens * (1 + self.rereads) if self.sent else 0

    def weighted(self, w: TokenWeights) -> float:
        return self._cost(self.tokens, w)

    def weighted_if_lines(self, w: TokenWeights, lines: int = SHORT_LINES) -> float:
        """The same call if its result had been ``lines`` lines long."""
        if self.lines <= lines:
            return self.weighted(w)
        return self._cost(self.tokens * lines / self.lines, w)

    def _cost(self, tokens: float, w: TokenWeights) -> float:
        if not self.sent:
            return 0.0
        return tokens * w.cache_write + tokens * w.cache_read * self.rereads


@dataclass
class Subagents:
    runs: int = 0
    total: Usage = field(default_factory=Usage)


@dataclass
class Session:
    id: str
    turns: list[Usage] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    items: list[Call] = field(default_factory=list)  # Claude's replies, later messages
    versions: list[str] = field(default_factory=list)
    compactions: int = 0
    skipped_lines: int = 0
    subagents: Subagents = field(default_factory=Subagents)
    rebuilds: list[int] = field(default_factory=list)  # tokens written again on a cache miss
    scale: float = 1.0

    @property
    def total(self) -> Usage:
        total = Usage()
        for turn in self.turns:
            total.add(turn)
        return total


@dataclass
class Report:
    sessions: list[Session]
    weights: TokenWeights
    total: Usage
    top: list[Call]
    by_category: dict[str, float]
    growth: list[int]  # context size per request, newest session
    subagents: Subagents


# --- finding transcripts ---------------------------------------------------------------


def claude_home(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = env.get("CLAUDE_CONFIG_DIR")
    return Path(configured) if configured else Path.home() / ".claude"


def project_folder(project: Path, home: Path) -> Path:
    """Claude Code's folder for a project: every character but letters and digits is ``-``."""
    return home / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(project))


def select_sessions(
    folder: Path, *, session: str | None = None, since: datetime | None = None
) -> list[Path]:
    """One session by id (or id prefix), those changed since a time, or the latest."""
    files = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise UsageError(t("tokens.error.none", folder=folder.name))
    if session is not None:
        chosen = [p for p in files if p.stem.startswith(session)]
        if not chosen:
            raise UsageError(t("tokens.error.session", session=session))
        return chosen[:1]
    if since is not None:
        stamp = since.timestamp()
        chosen = [p for p in files if p.stat().st_mtime >= stamp]
        if not chosen:
            raise UsageError(t("tokens.error.since"))
        return chosen
    return files[:1]


def settings(config_flag: Path | None = None) -> TokensCfg:
    """The ``tokens`` settings; the defaults when Orkestra has no config yet (it needs none)."""
    if not loader.find_sources(config_flag):
        return TokensCfg()
    return loader.load_config(config_flag).config.tokens


def collect(
    *,
    project: Path,
    session: str | None = None,
    since: datetime | None = None,
    top: int | None = None,
    config_flag: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Report:
    """``orkestra tokens``: read the chosen sessions of ``project`` and rank what they cost."""
    cfg = settings(config_flag)
    folder = project_folder(project, claude_home(environ))
    paths = select_sessions(folder, session=session, since=since)
    return analyse([read_session(p) for p in paths], cfg.weights, top=top or cfg.top)


# --- reading one session ---------------------------------------------------------------


def _entries(path: Path, session: Session) -> Iterable[dict[str, Any]]:
    with path.open("rb") as f:
        for raw in f:
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                session.skipped_lines += 1
                continue
            if isinstance(entry, dict):
                yield entry


def _usage(data: Any) -> Usage:
    if not isinstance(data, dict):
        return Usage()

    def number(key: str) -> int:
        value = data.get(key)
        return value if isinstance(value, int) else 0

    return Usage(number("input_tokens"), number("cache_creation_input_tokens"),
                 number("cache_read_input_tokens"), number("output_tokens"))  # fmt: skip


def _text_size(content: Any) -> tuple[int, int]:
    """Characters and lines of a tool result (a string or a list of blocks)."""
    if isinstance(content, str):
        return len(content), len(content.splitlines())
    if isinstance(content, list):
        chars = lines = 0
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                chars += len(block["text"])
                lines += len(block["text"].splitlines())
            elif isinstance(block, dict):
                chars += len(json.dumps(block, default=str))  # images and other blocks
        return chars, lines
    return 0, 0


def read_session(path: Path, *, calibrate: bool = True) -> Session:
    session = Session(path.stem)
    ids: dict[str, int] = {}
    calls: dict[str, Call] = {}
    replies: dict[int, Call] = {}
    boundaries: list[int] = []
    cwd: str | None = None
    for entry in _entries(path, session):
        kind = entry.get("type")
        if cwd is None and isinstance(entry.get("cwd"), str):
            cwd = entry["cwd"]
        version = entry.get("version")
        if isinstance(version, str) and version not in session.versions:
            session.versions.append(version)
        message = entry.get("message")
        if kind == "system" and entry.get("subtype") == "compact_boundary":
            session.compactions += 1
            boundaries.append(len(session.turns))
        elif kind == "assistant" and isinstance(message, dict) and not entry.get("isSidechain"):
            msg_id = str(message.get("id") or f"#{len(ids)}")
            if msg_id not in ids:
                ids[msg_id] = len(session.turns)
                session.turns.append(Usage())
            turn = ids[msg_id]
            session.turns[turn] = _usage(message.get("usage"))  # the last block's usage wins
            for block in _blocks(message):
                if block.get("type") == "tool_use" and isinstance(block.get("id"), str):
                    call = _call(block, turn, cwd)
                    calls[call.id] = call
                    session.calls.append(call)
                    if call.category not in _INPUT_COUNTS:  # its input is part of the reply
                        _item(session, replies, "replies", turn).result_chars += call.input_chars
                elif block.get("type") == "text" and isinstance(block.get("text"), str):
                    _item(session, replies, "replies", turn).result_chars += len(block["text"])
        elif kind == "user" and isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and session.turns:
                _item(session, {}, "messages", len(session.turns) - 1).result_chars += len(content)
            for block in _blocks(message):
                if block.get("type") == "tool_result":
                    call = calls.get(str(block.get("tool_use_id")))
                    if call is not None:
                        call.result_chars, call.lines = _text_size(block.get("content"))
                elif block.get("type") == "text" and session.turns:
                    chars = _text_size([block])[0]
                    _item(session, {}, "messages", len(session.turns) - 1).result_chars += chars
        elif kind == "attachment" and session.turns:
            chars = len(json.dumps(entry.get("attachment"), default=str))
            _item(session, {}, "messages", len(session.turns) - 1).result_chars += chars
    _place(session, boundaries)
    session.rebuilds = _rebuilds(session, boundaries)
    if calibrate:
        _calibrate(session)
    session.subagents = _subagents(path.with_suffix("") / "subagents")
    return session


def _item(session: Session, by_turn: dict[int, Call], kind: str, turn: int) -> Call:
    """The context item (one per request for replies) that more characters are added to.
    Thinking is left out: Claude Code does not send old thinking again."""
    item = by_turn.get(turn)
    if item is None:
        item = Call(f"{kind}:{len(session.items)}", "-", "", turn, kind)
        session.items.append(item)
        by_turn[turn] = item
    return item


def _blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _call(block: dict[str, Any], turn: int, cwd: str | None) -> Call:
    tool = str(block.get("name") or "?")
    data = block.get("input") if isinstance(block.get("input"), dict) else {}
    assert isinstance(data, dict)
    chars = sum(len(v) if isinstance(v, str) else len(json.dumps(v, default=str))
                for v in data.values())  # fmt: skip
    return Call(str(block["id"]), tool, label(tool, data, cwd), turn,
                _CATEGORY.get(tool, "other"), input_chars=chars)  # fmt: skip


def _place(session: Session, boundaries: list[int]) -> None:
    """When each result was sent and how many later requests read it again."""
    count = len(session.turns)
    for call in [*session.calls, *session.items]:
        written = call.turn + 1
        call.sent = written < count
        end = next((b for b in boundaries if b > written), count)
        call.rereads = max(0, end - written - 1) if call.sent else 0


def _rebuilds(session: Session, boundaries: list[int]) -> list[int]:
    """Cache misses: a request that read much less from the cache than the last one sent
    (the cache expired after a pause, or the model changed), so the context was written again.
    A compaction shrinks the context on purpose and is not one."""
    found: list[int] = []
    for turn in range(1, len(session.turns)):
        lost = session.turns[turn - 1].context - session.turns[turn].cache_read
        if lost >= REBUILD_MIN and turn not in boundaries:
            found.append(lost)
    return found


def _calibrate(session: Session) -> None:
    """Scale the size estimates so that they add up to the new context Claude Code measured
    (``input + cache_write`` of every request, without the start and the cache misses)."""
    items = [c for c in [*session.calls, *session.items] if c.sent]
    estimated = sum(c.tokens for c in items)
    if not session.turns or estimated == 0:
        return
    measured = sum(t.input + t.cache_write for t in session.turns)
    new = measured - session.turns[0].context - sum(session.rebuilds)
    if new <= 0:
        return
    session.scale = min(max(new / estimated, MIN_SCALE), MAX_SCALE)
    for call in [*session.calls, *session.items]:
        call.scale = session.scale


def _subagents(folder: Path) -> Subagents:
    found = Subagents()
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        sub = Session(path.stem)
        last: dict[str, Usage] = {}
        for entry in _entries(path, sub):
            message = entry.get("message")
            if entry.get("type") == "assistant" and isinstance(message, dict):
                last[str(message.get("id") or len(last))] = _usage(message.get("usage"))
        found.runs += 1
        for usage in last.values():
            found.total.add(usage)
    return found


# --- labels without personal paths ----------------------------------------------------


def label(tool: str, data: Mapping[str, Any], cwd: str | None) -> str:
    for key in _PATH_KEYS:
        if isinstance(data.get(key), str):
            return _short_path(data[key], cwd)
    if tool in ("Bash", "PowerShell") and isinstance(data.get("command"), str):
        return _clip(scrub(data["command"], cwd))
    key = _TEXT_KEYS.get(tool)
    if key and isinstance(data.get(key), str):
        return _clip(scrub(data[key], cwd))
    return ""


def _short_path(raw: str, cwd: str | None) -> str:
    """Relative to the working directory when inside it; else only the file's name."""
    path = raw.replace("\\", "/")
    if cwd:
        base = cwd.replace("\\", "/").rstrip("/") + "/"
        if path.lower().startswith(base.lower()):
            return path[len(base) :] or "."
    absolute = path.startswith("/") or re.match(r"^[A-Za-z]:", path) is not None
    return path.rsplit("/", 1)[-1] if absolute or path.startswith("~") else path


def scrub(text: str, cwd: str | None) -> str:
    """The working directory as ``.``, the home directory as ``~`` (any slash, any case)."""
    for place, short in ((cwd, "."), (str(Path.home()), "~")):
        if place:
            parts = [re.escape(p) for p in re.split(r"[\\/]+", place.rstrip("\\/")) if p]
            pattern = r"[\\/]+".join(parts)
            if place.startswith(("/", "\\")):
                pattern = r"[\\/]+" + pattern
            text = re.sub(pattern, lambda _m, s=short: s, text, flags=re.IGNORECASE)
    return text


def _clip(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= LABEL_CHARS else flat[: LABEL_CHARS - 1] + "…"


# --- the report ------------------------------------------------------------------------


def analyse(sessions: Sequence[Session], weights: TokenWeights, *, top: int = 10) -> Report:
    total = Usage()
    subagents = Subagents()
    by_category: dict[str, float] = dict.fromkeys(KINDS, 0.0)
    calls: list[Call] = []
    for session in sessions:
        total.add(session.total)
        subagents.runs += session.subagents.runs
        subagents.total.add(session.subagents.total)
        calls.extend(session.calls)
        for call in [*session.calls, *session.items]:
            by_category[call.category] += call.weighted(weights)
    by_category["output"] = total.output * weights.output
    by_category["baseline"] = sum(_baseline(s, weights) for s in sessions)
    # A miss writes again what would have been read: the difference is its extra cost.
    extra = weights.cache_write - weights.cache_read
    by_category["rebuild"] = sum(sum(s.rebuilds) for s in sessions) * extra
    counted = sum(by_category.values())
    by_category["rest"] = max(0.0, total.weighted(weights) - counted)  # messages, replies
    ranked = sorted(calls, key=lambda c: c.weighted(weights), reverse=True)[:top]
    growth = [turn.context for turn in sessions[0].turns] if sessions else []
    return Report(list(sessions), weights, total, ranked, by_category, growth, subagents)


def _baseline(session: Session, w: TokenWeights) -> float:
    """The fixed start: the first request's context (system prompt, tools, CLAUDE.md, memory)
    is written once and read again by every later request."""
    if not session.turns:
        return 0.0
    start = session.turns[0].context
    return start * w.cache_write + start * w.cache_read * (len(session.turns) - 1)


def _int(value: float) -> int:
    return round(value)


def to_dict(report: Report) -> dict[str, Any]:
    w = report.weights
    return {
        "sessions": [
            {"id": s.id, "requests": len(s.turns), "versions": s.versions,
             "compactions": s.compactions, "skipped_lines": s.skipped_lines,
             "scale": round(s.scale, 2), "cache_misses": len(s.rebuilds),
             "cache_miss_tokens": sum(s.rebuilds),
             "weighted": _int(s.total.weighted(w))}
            for s in report.sessions
        ],
        "weights": w.model_dump(),
        "total": {"input": report.total.input, "cache_write": report.total.cache_write,
                  "cache_read": report.total.cache_read, "output": report.total.output,
                  "raw": report.total.raw, "weighted": _int(report.total.weighted(w))},
        "by_category": {k: _int(v) for k, v in report.by_category.items()},
        "top": [
            {"tool": c.tool, "label": c.label, "category": c.category, "tokens": c.tokens,
             "lines": c.lines, "rereads": c.rereads, "raw": c.raw(w),
             "weighted": _int(c.weighted(w)), "if_10_lines": _int(c.weighted_if_lines(w))}
            for c in report.top
        ],
        "growth": report.growth,
        "subagents": {"runs": report.subagents.runs,
                      "weighted": _int(report.subagents.total.weighted(w))},
        "estimate": {"chars_per_token": CHARS_PER_TOKEN},
    }  # fmt: skip


def _n(value: float) -> str:
    return f"{_int(value):,}"


def render(report: Report) -> str:
    w = report.weights
    total = report.total
    versions = sorted({v for s in report.sessions for v in s.versions}) or ["?"]
    weighted = total.weighted(w)
    lines = [
        t("tokens.header", sessions=len(report.sessions),
          requests=sum(len(s.turns) for s in report.sessions), versions=", ".join(versions)),
        t("tokens.totals", input=_n(total.input), cache_write=_n(total.cache_write),
          cache_read=_n(total.cache_read), output=_n(total.output), raw=_n(total.raw),
          weighted=_n(weighted)),
        t("tokens.weights", output=w.output, cache_write=w.cache_write, cache_read=w.cache_read),
        "",
        t("tokens.by_kind.header"),
    ]  # fmt: skip
    for kind, value in sorted(report.by_category.items(), key=lambda kv: -kv[1]):
        if value > 0:
            share = 100 * value / weighted if weighted else 0
            lines.append(t("tokens.by_kind.line", kind=t(f"tokens.kind.{kind}"),
                           value=_n(value), percent=f"{share:.0f}"))  # fmt: skip
    if report.top:
        lines += ["", t("tokens.top.header")]
        for call in report.top:
            lines.append(t("tokens.top.line", tool=call.tool, label=call.label or "-",
                           tokens=_n(call.tokens), lines=call.lines, rereads=call.rereads,
                           weighted=_n(call.weighted(w))))  # fmt: skip
            short = call.weighted_if_lines(w)
            if call.lines > SHORT_LINES and short < call.weighted(w):
                lines.append(t("tokens.top.if_lines", count=SHORT_LINES, value=_n(short),
                               saved=_n(call.weighted(w) - short)))  # fmt: skip
    if report.growth:
        lines += ["", t("tokens.growth", points=" → ".join(_n(p) for p in _sample(report.growth)))]
    if report.subagents.runs:
        lines.append(t("tokens.subagents", runs=report.subagents.runs,
                       weighted=_n(report.subagents.total.weighted(w))))  # fmt: skip
    misses = [r for s in report.sessions for r in s.rebuilds]
    if misses:
        lines.append(t("tokens.rebuilds", count=len(misses), tokens=_n(sum(misses))))
    compactions = sum(s.compactions for s in report.sessions)
    if compactions:
        lines.append(t("tokens.compactions", count=compactions))
    skipped = sum(s.skipped_lines for s in report.sessions)
    if skipped:
        lines.append(t("tokens.skipped", count=skipped))
    scales = [s.scale for s in report.sessions if s.turns]
    low, high = (min(scales), max(scales)) if scales else (1.0, 1.0)
    shown = f"{low:.2f}" if round(low, 2) == round(high, 2) else f"{low:.2f}-{high:.2f}"
    lines.append(t("tokens.estimate_note", chars=CHARS_PER_TOKEN, scale=shown))
    return "\n".join(lines)


def _sample(values: list[int], points: int = GROWTH_POINTS) -> list[int]:
    if len(values) <= points:
        return values
    step = (len(values) - 1) / (points - 1)
    return [values[round(i * step)] for i in range(points)]
