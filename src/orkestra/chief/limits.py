"""The chief's own quota (Faz 13k, D-094): ``orkestra statusline`` and its hook.

Claude Code runs a status line command after each message and hands it a JSON object; its
``rate_limits`` field has the usage windows of the subscription (``five_hour``,
``seven_day``: ``used_percentage`` 0-100, ``resets_at`` in epoch seconds), each of which may
be missing. ``statusline`` prints one short line and keeps the last hour of readings in
``~/.orkestra/chief_quota.json``, so the pace gives the time left.

Only the chief knows what it is doing, so Orkestra cannot write the handoff summary for it.
Instead, once a window passes ``handoff.prepare_at_percent`` (or would run out within
``forecast.warn_within_s``), the ``statusline hook`` command, run by Claude Code on
``UserPromptSubmit`` and ``PostToolUse``, adds one note to the chief's context: update the
handoff file now. It says so once per window: the mark is a file of its own, created
atomically (``chief_quota.prompted/``), so two hooks at once give one note and the status line,
which rewrites ``chief_quota.json`` on every message, cannot undo it. When the quota then runs
out, the user only types ``orkestra handoff to agy``.

Nothing here may fail the status line or the hook: bad input, a broken state file or a
broken config give a shorter line, never an error.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from orkestra import paths
from orkestra.config.schema import Config
from orkestra.errors import OrkestraError
from orkestra.i18n import t
from orkestra.state import forecast, health

STATE_FILE = "chief_quota.json"
MARKS_DIR = "chief_quota.prompted"  # one file per window the hook has spoken about
WINDOWS = ("five_hour", "seven_day")
FRESH = timedelta(minutes=15)  # older readings are not shown: the session is over
SAMPLE_SPAN = timedelta(hours=1)  # the pace is read over this span
MIN_SPAN = timedelta(minutes=5)  # shorter spans give no pace yet
MAX_SAMPLES = 60
HOOK_EVENTS = ("UserPromptSubmit", "PostToolUse")  # the events whose hooks may add context
CHIEF_ENV = "ORKESTRA_CHIEF"
STATUSLINE_COMMAND = "orkestra statusline"
HOOK_COMMAND = "orkestra statusline hook"

# Read by the chief, like a worker prompt: English (AGENTS.md).
HOOK_CONTEXT = (
    "Orkestra: your {label} usage limit is at {used}%{eta}{resets}. Before you go on, bring "
    "the handoff file ({file}) up to date so another chief can take over if the limit runs "
    'out: `orkestra handoff update --chief {chief} --section status --set "..."` and '
    '`--section in_progress --set "..."` (`--section done --add "..."` for finished '
    "steps); run `orkestra handoff init` first if the file does not exist. Commit finished "
    "work. Then tell the user that `orkestra handoff to {next_chief}` continues the work. "
    "This note comes once per limit window."
)


@dataclass(frozen=True)
class Reading:
    name: str  # five_hour | seven_day
    used: float  # percent
    resets_at: datetime | None


@dataclass(frozen=True)
class Window:
    name: str
    used: float
    resets_at: datetime | None
    eta_s: float | None  # seconds until 100 % at the recent pace; None: no pace, or resets first
    started: datetime | None = None  # first reading of this window

    @property
    def label(self) -> str:
        return t(f"limits.window.{self.name}")

    @property
    def key(self) -> str:
        """Which window this is: its reset time, else when its readings began (a window
        without a reset time is new once its use went down)."""
        if self.resets_at is not None:
            return self.resets_at.isoformat()
        return "start " + (self.started.isoformat() if self.started else "-")


def state_path() -> Path:
    return paths.orkestra_home() / STATE_FILE


# --- reading Claude Code's JSON -----------------------------------------------------------


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def parse(payload: Any) -> list[Reading]:
    """The usage windows in a status line payload; anything unreadable is skipped."""
    if not isinstance(payload, dict):
        return []
    rate = payload.get("rate_limits")
    if not isinstance(rate, dict):
        return []
    found: list[Reading] = []
    for name in WINDOWS:
        entry = rate.get(name)
        if not isinstance(entry, dict):
            continue
        used = _number(entry.get("used_percentage"))
        if used is None:
            continue
        stamp = _number(entry.get("resets_at"))
        resets = None
        if stamp is not None:
            with contextlib.suppress(OverflowError, OSError, ValueError):
                resets = datetime.fromtimestamp(stamp, tz=UTC).astimezone()
        found.append(Reading(name, used, resets))
    return found


# --- the readings kept between calls ------------------------------------------------------


def load(path: Path) -> dict[str, Any]:
    """The saved readings; a missing or broken file is an empty start."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(path: Path, state: Mapping[str, Any]) -> bool:
    """Write atomically (two sessions may write at once); False when it cannot be written."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".",
                                                 suffix=".tmp")  # fmt: skip
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(state, handle)
            os.replace(temporary, path)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise
    except OSError:
        return False
    return True


def _windows_of(state: Mapping[str, Any]) -> dict[str, Any]:
    windows = state.get("windows")
    return windows if isinstance(windows, dict) else {}


def _samples(entry: Any) -> list[tuple[datetime, float]]:
    found: list[tuple[datetime, float]] = []
    raw = entry.get("samples") if isinstance(entry, dict) else None
    for item in raw if isinstance(raw, list) else []:
        try:
            found.append((datetime.fromisoformat(item[0]), float(item[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return found


def record(state: Mapping[str, Any], readings: list[Reading], now: datetime) -> dict[str, Any]:
    """``state`` with ``readings`` added: a window keeps its last hour of readings, and starts
    again (a new ``started``) when its reset time changes or its use goes down."""
    windows = dict(_windows_of(state))
    for reading in readings:
        key = reading.resets_at.isoformat() if reading.resets_at else None
        old = windows.get(reading.name)
        samples = _samples(old)
        same = isinstance(old, dict) and old.get("resets_at") == key
        started = old.get("started") if same and isinstance(old, dict) else None
        if not same or (samples and reading.used < samples[-1][1]) or not started:
            samples, started = [], now.isoformat()
        samples.append((now, reading.used))
        samples = [s for s in samples if s[0] >= now - SAMPLE_SPAN][-MAX_SAMPLES:]
        windows[reading.name] = {
            "used": reading.used,
            "resets_at": key,
            "started": started,
            "samples": [[at.isoformat(), used] for at, used in samples],
        }
    return {"windows": windows}


def _eta(samples: list[tuple[datetime, float]], resets: datetime | None) -> float | None:
    if len(samples) < 2:
        return None
    (first_at, first_used), (last_at, last_used) = samples[0], samples[-1]
    span = (last_at - first_at).total_seconds()
    if span < MIN_SPAN.total_seconds() or last_used <= first_used:
        return None
    eta = (100.0 - last_used) / ((last_used - first_used) / span)
    # Compared as numbers: at a pace of almost nothing a datetime would overflow.
    if resets is not None and eta >= (resets - last_at).total_seconds():
        return None  # the window resets before the pace uses it up
    return eta


def windows(state: Mapping[str, Any], now: datetime) -> list[Window]:
    """The windows read in the last 15 minutes whose reset is still ahead."""
    found: list[Window] = []
    saved = _windows_of(state)
    for name in WINDOWS:
        entry = saved.get(name)
        samples = _samples(entry)
        if not samples or now - samples[-1][0] > FRESH or not isinstance(entry, dict):
            continue
        resets, started = _when(entry.get("resets_at")), _when(entry.get("started"))
        if resets is not None and resets <= now:
            continue
        found.append(Window(name, samples[-1][1], resets, _eta(samples, resets), started))
    return found


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _pressing(window: Window, config: Config) -> bool:
    if window.used >= config.handoff.prepare_at_percent:
        return True
    return window.eta_s is not None and window.eta_s <= config.forecast.warn_within_s


def due(
    state: Mapping[str, Any], config: Config, now: datetime, marks: Path | None = None
) -> Window | None:
    """The first window past the threshold (or running out soon) not yet asked about (no
    mark in ``marks``)."""
    for window in windows(state, now):
        if _pressing(window, config) and (marks is None or not _mark(marks, window).exists()):
            return window
    return None


def _mark(marks: Path, window: Window) -> Path:
    digest = hashlib.sha256(window.key.encode("utf-8")).hexdigest()[:16]
    return marks / f"{window.name}-{digest}"


def claim(marks: Path, window: Window) -> bool:
    """Mark ``window`` as asked about; False when it already was (another hook was first)
    or the mark cannot be written (then no note: it would come again on every call)."""
    target = _mark(marks, window)
    try:
        marks.mkdir(parents=True, exist_ok=True)
        os.close(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except OSError:  # FileExistsError included
        return False
    for old in marks.glob(f"{window.name}-*"):  # earlier windows of the same kind
        if old != target:
            with contextlib.suppress(OSError):
                old.unlink()
    return True


def marks_dir(path: Path) -> Path:
    return path.with_name(MARKS_DIR)


# --- text ---------------------------------------------------------------------------------


def window_text(window: Window) -> str:
    """``5h 72%``, with the time left when there is a pace: ``5h 72% (~40 min)``."""
    text = f"{window.label} {window.used:.0f}%"
    return f"{text} ({forecast.eta_text(window.eta_s)})" if window.eta_s is not None else text


def current_chief(config: Config, environ: Mapping[str, str]) -> str:
    return environ.get(CHIEF_ENV, "").strip() or config.defaults.chief


def next_chief(config: Config, environ: Mapping[str, str]) -> str:
    """The chief to hand over to: the first configured one that is not the current one."""
    current = current_chief(config, environ)
    return next((name for name in config.chiefs if name != current), current)


def statusline(
    text: str,
    *,
    config: Config,
    now: datetime,
    path: Path | None,
    extra: Callable[[], list[str]],
    environ: Mapping[str, str] | None = None,
) -> str:
    """One line: Claude's windows, what Orkestra has to say (``extra``), and past the
    threshold the handoff command. Saves the readings for ``status`` and the hook (not
    without a ``path``: no home folder)."""
    env = os.environ if environ is None else environ
    try:
        payload = json.loads(text) if text.strip() else None
    except ValueError:
        payload = None
    readings = parse(payload)
    shown: list[Window] = []
    if readings:
        state = record(load(path) if path is not None else {}, readings, now)
        if path is not None:
            save(path, state)
        names = {r.name for r in readings}
        shown = [w for w in windows(state, now) if w.name in names]
    head = t("statusline.claude")
    if shown:
        head += " " + " · ".join(window_text(w) for w in shown)
    parts = [head]
    notes = extra()
    if notes:
        parts.append(t("statusline.orkestra", text=", ".join(notes)))
    if any(_pressing(w, config) for w in shown):
        command = f"orkestra handoff to {next_chief(config, env)}"
        parts.append(t("statusline.handoff", command=command))
    return " | ".join(parts)


def hook(
    text: str,
    *,
    config: Config,
    now: datetime,
    path: Path,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """The hook's JSON for Claude Code when a window is due, else None (print nothing)."""
    env = os.environ if environ is None else environ
    try:
        payload = json.loads(text) if text.strip() else None
    except ValueError:
        return None
    event = payload.get("hook_event_name") if isinstance(payload, dict) else None
    if event not in HOOK_EVENTS:
        return None
    marks = marks_dir(path)
    window = due(load(path), config, now, marks)
    if window is None or not claim(marks, window):
        return None
    eta = f", {forecast.eta_text(window.eta_s)} left" if window.eta_s is not None else ""
    resets = f", resets {window.resets_at:%Y-%m-%d %H:%M}" if window.resets_at else ""
    context = HOOK_CONTEXT.format(
        label=window.label, used=f"{window.used:.0f}", eta=eta, resets=resets,
        file=config.handoff.file, chief=current_chief(config, env),
        next_chief=next_chief(config, env),
    )  # fmt: skip
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}
    )


def settings_snippet() -> str:
    """What goes into Claude Code's ``settings.json`` for the line and the hook."""
    hook_entry = [{"hooks": [{"type": "command", "command": HOOK_COMMAND}]}]
    return json.dumps(
        {
            "statusLine": {"type": "command", "command": STATUSLINE_COMMAND},
            "hooks": {event: hook_entry for event in HOOK_EVENTS},
        },
        indent=2,
    )


# --- the commands, with their own error handling -------------------------------------------


def orkestra_notes(conn: sqlite3.Connection, config: Config, now: datetime) -> list[str]:
    """Providers paused for quota and providers running low, shortest form."""
    notes = [
        t("status.health.quota_item", name=h.provider,
          until=health.until_text(h.open_until, now)) if h.open_until else h.provider
        for h in health.quota_paused(conn, now)
    ]  # fmt: skip
    low = forecast.low_now(conn, config, now, skip=health.paused_names(conn, now))
    return notes + [forecast.describe(f) for f in low]


# Everything the status line and the hook swallow: a broken config, state file or database,
# no home folder (``Path.home()`` raises RuntimeError), a bad row in state.db.
_SAFE = (OrkestraError, OSError, RuntimeError, ValueError, TypeError, sqlite3.Error)


def run_statusline(
    text: str, *, load_config: Callable[[], Config], connect: Callable[[], sqlite3.Connection],
    now: datetime,
) -> str:  # fmt: skip
    """``orkestra statusline``: never fails. A broken config gives the defaults; a database
    that cannot be read leaves out what Orkestra has to say; no home folder, no saving."""
    try:
        config = load_config()
    except _SAFE:
        config = Config.model_validate({"version": 1})
    try:
        path: Path | None = state_path()
    except _SAFE:
        path = None

    def notes() -> list[str]:
        try:
            conn = connect()
        except _SAFE:
            return []
        try:
            return orkestra_notes(conn, config, now)
        except _SAFE:
            return []
        finally:
            conn.close()

    try:
        return statusline(text, config=config, now=now, path=path, extra=notes)
    except _SAFE:
        return t("statusline.claude")


def run_hook(text: str, *, load_config: Callable[[], Config], now: datetime) -> str | None:
    """``orkestra statusline hook``: never fails; a broken config means no note."""
    try:
        return hook(text, config=load_config(), now=now, path=state_path())
    except _SAFE:
        return None


def status_windows(now: datetime) -> list[Window]:
    """For ``status``: the chief's windows from the last status line readings (none when
    they cannot be read)."""
    try:
        return windows(load(state_path()), now)
    except _SAFE:
        return []
