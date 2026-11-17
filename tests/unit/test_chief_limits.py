"""The chief's own quota (Faz 13k, D-094): Claude Code's status line hands over
``rate_limits``; Orkestra keeps a few readings, forecasts the end and, past the threshold,
a hook asks Claude once per window to bring the handoff file up to date."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from orkestra.chief import limits
from orkestra.config.schema import Config

TZ = timezone(timedelta(hours=3))
NOON = datetime(2026, 11, 18, 12, 0, tzinfo=TZ)
RESETS = NOON + timedelta(hours=3)


def _payload(five: float | None = None, seven: float | None = None, **extra: Any) -> str:
    rate: dict[str, Any] = {}
    if five is not None:
        rate["five_hour"] = {"used_percentage": five, "resets_at": int(RESETS.timestamp())}
    if seven is not None:
        week = NOON + timedelta(days=3)
        rate["seven_day"] = {"used_percentage": seven, "resets_at": int(week.timestamp())}
    return json.dumps({"session_id": "s", "rate_limits": rate, **extra})


def _config(**handoff: Any) -> Config:
    return Config.model_validate({"version": 1, "providers": {}, "handoff": handoff})


# --- reading what Claude Code sends -------------------------------------------------------


def test_parse_reads_both_windows() -> None:
    readings = limits.parse(json.loads(_payload(72.4, 40)))

    assert [(r.name, r.used) for r in readings] == [("five_hour", 72.4), ("seven_day", 40)]
    assert readings[0].resets_at == RESETS


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"rate_limits": None},
        {"rate_limits": {"five_hour": {"used_percentage": "lots"}}},
        {"rate_limits": {"five_hour": "x"}},
        {"rate_limits": {"five_hour": {"used_percentage": float("nan")}}},
    ],
)
def test_parse_skips_what_it_cannot_read(payload: dict[str, Any]) -> None:
    assert limits.parse(payload) == []


def test_a_window_without_a_reset_time_is_still_read() -> None:
    readings = limits.parse({"rate_limits": {"five_hour": {"used_percentage": 10}}})
    assert [(r.name, r.used, r.resets_at) for r in readings] == [("five_hour", 10, None)]


# --- forecast from the readings -----------------------------------------------------------


def _state(*points: tuple[datetime, float]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for at, used in points:
        reading = limits.Reading("five_hour", used, RESETS)
        state = limits.record(state, [reading], at)
    return state


def test_the_pace_of_the_readings_gives_the_time_left() -> None:
    state = _state((NOON - timedelta(minutes=30), 60), (NOON, 70))

    [window] = limits.windows(state, NOON)

    assert window.used == 70
    assert window.eta_s == pytest.approx(1.5 * 3600)  # 30 % left at 20 % an hour


def test_too_short_a_span_has_no_pace_yet() -> None:
    state = _state((NOON - timedelta(minutes=2), 60), (NOON, 70))
    assert limits.windows(state, NOON)[0].eta_s is None


def test_a_window_that_resets_first_has_no_time_left() -> None:
    state = _state((NOON - timedelta(hours=1), 10), (NOON, 20))
    # 80 % left at 10 % an hour: 8 hours, but the window resets in 3.
    assert limits.windows(state, NOON)[0].eta_s is None


def test_a_new_window_starts_its_readings_again() -> None:
    state = _state((NOON - timedelta(minutes=30), 90))
    later = limits.Reading("five_hour", 5, RESETS + timedelta(hours=5))
    state = limits.record(state, [later], NOON)

    [window] = limits.windows(state, NOON)
    assert window.used == 5 and window.eta_s is None


def test_readings_are_kept_short() -> None:
    points = [(NOON - timedelta(minutes=m), 50.0) for m in range(200, -1, -1)]
    state = _state(*points)
    assert len(state["windows"]["five_hour"]["samples"]) <= limits.MAX_SAMPLES


def test_old_readings_are_not_shown() -> None:
    state = _state((NOON, 70))
    assert limits.windows(state, NOON + limits.FRESH + timedelta(seconds=1)) == []


def test_a_window_whose_reset_passed_is_not_shown() -> None:
    state = _state((NOON, 70))
    assert limits.windows(state, RESETS + timedelta(seconds=1)) == []


# --- when to ask for the handoff file -------------------------------------------------


def test_past_the_threshold_it_is_due_once_per_window(tmp_path: Path) -> None:
    marks = tmp_path / "marks"
    state = _state((NOON, 86))
    config = _config()

    due = limits.due(state, config, NOON, marks)
    assert due is not None and due.name == "five_hour"

    assert limits.claim(marks, due) is True
    assert limits.claim(marks, due) is False  # a second hook at the same time loses
    assert limits.due(state, config, NOON, marks) is None
    renewed = limits.record(
        state, [limits.Reading("five_hour", 88, RESETS + timedelta(hours=5))], NOON
    )
    assert limits.due(renewed, config, NOON, marks) is not None  # the next window asks again


def test_a_status_line_write_does_not_undo_the_hooks_mark(tmp_path: Path) -> None:
    """Code review #34: the status line read the file before the hook marked it and then
    wrote its old copy back, so the note came again."""
    path = tmp_path / "q.json"
    limits.statusline(_payload(90), config=_config(), now=NOON, path=path, extra=lambda: [])
    stale = limits.load(path)  # the status line has read the file ...
    event = json.dumps({"hook_event_name": "PostToolUse"})
    assert limits.hook(event, config=_config(), now=NOON, path=path) is not None
    later = NOON + timedelta(seconds=1)  # ... and writes its copy after the hook marked it
    limits.save(path, limits.record(stale, limits.parse(json.loads(_payload(90))), later))

    assert limits.hook(event, config=_config(), now=later, path=path) is None


def test_without_a_reset_time_a_new_window_is_asked_about_again(tmp_path: Path) -> None:
    """Code review #34: with no ``resets_at`` every window had the same key, so after the
    first note no window was ever asked about again."""
    marks = tmp_path / "marks"

    def read(state: dict[str, Any], used: float, at: datetime) -> dict[str, Any]:
        return limits.record(state, [limits.Reading("five_hour", used, None)], at)

    state = read({}, 90, NOON)
    first = limits.due(state, _config(), NOON, marks)
    assert first is not None and limits.claim(marks, first)

    later = NOON + timedelta(days=2)
    state = read(read(state, 10, later), 95, later + timedelta(minutes=1))  # it was reset
    assert limits.due(state, _config(), later + timedelta(minutes=1), marks) is not None


def test_a_pace_of_almost_nothing_does_not_overflow() -> None:
    """Code review #34: ``last_at + timedelta(eta)`` went past the year 9999."""
    state = _state((NOON - timedelta(minutes=10), 50.0), (NOON, 50.0000000001))
    [window] = limits.windows(state, NOON)
    assert window.eta_s is None


def test_below_the_threshold_but_running_out_soon_is_due() -> None:
    state = _state((NOON - timedelta(minutes=30), 50), (NOON, 70))  # 30 % left at 40 %/h
    assert limits.due(state, _config(), NOON) is not None


def test_below_the_threshold_and_slow_is_not_due() -> None:
    state = _state((NOON - timedelta(minutes=30), 69), (NOON, 70))
    assert limits.due(state, _config(prepare_at_percent=90), NOON) is None


def test_the_threshold_comes_from_the_config() -> None:
    state = _state((NOON, 60))
    assert limits.due(state, _config(prepare_at_percent=50), NOON) is not None


# --- the status line and the hook -----------------------------------------------------


def test_the_status_line_shows_the_windows(tmp_path: Path) -> None:
    line = limits.statusline(_payload(72.4, 40), config=_config(), now=NOON,
                             path=tmp_path / "q.json", extra=lambda: [])  # fmt: skip
    assert line == "Claude 5h 72% · 7d 40%"
    assert (tmp_path / "q.json").exists()


def test_past_the_threshold_the_line_names_the_next_chief(tmp_path: Path) -> None:
    line = limits.statusline(_payload(91), config=_config(), now=NOON,
                             path=tmp_path / "q.json", extra=lambda: [])  # fmt: skip
    assert line == "Claude 5h 91% | handoff: orkestra handoff to agy"


def test_the_line_adds_what_orkestra_has_to_say(tmp_path: Path) -> None:
    line = limits.statusline(_payload(10), config=_config(), now=NOON,
                             path=tmp_path / "q.json", extra=lambda: ["agy ~20 min"])  # fmt: skip
    assert line == "Claude 5h 10% | orkestra: agy ~20 min"


@pytest.mark.parametrize("text", ["", "not json", "[1, 2]", '{"rate_limits": 3}'])
def test_the_status_line_never_fails(tmp_path: Path, text: str) -> None:
    line = limits.statusline(text, config=_config(), now=NOON, path=tmp_path / "q.json",
                             extra=lambda: [])  # fmt: skip
    assert line == "Claude"


def test_a_broken_state_file_starts_over(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text("{broken", encoding="utf-8")
    assert limits.statusline(_payload(30), config=_config(), now=NOON, path=path,
                             extra=lambda: []) == "Claude 5h 30%"  # fmt: skip


def test_the_hook_asks_once_then_stays_quiet(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    limits.statusline(_payload(90), config=_config(), now=NOON, path=path, extra=lambda: [])
    event = json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": str(tmp_path)})

    first = limits.hook(event, config=_config(), now=NOON, path=path)
    second = limits.hook(event, config=_config(), now=NOON, path=path)

    assert first is not None and second is None
    output = json.loads(first)["hookSpecificOutput"]
    assert output["hookEventName"] == "UserPromptSubmit"
    context = output["additionalContext"]
    assert "90%" in context and "orkestra handoff update" in context
    assert "orkestra handoff to agy" in context


@pytest.mark.parametrize("event", ["PostToolUse", "UserPromptSubmit"])
def test_the_hook_answers_the_events_that_take_context(tmp_path: Path, event: str) -> None:
    path = tmp_path / "q.json"
    limits.statusline(_payload(90), config=_config(), now=NOON, path=path, extra=lambda: [])
    found = limits.hook(json.dumps({"hook_event_name": event}), config=_config(), now=NOON,
                        path=path)  # fmt: skip
    assert found is not None and json.loads(found)["hookSpecificOutput"]["hookEventName"] == event


@pytest.mark.parametrize("text", ['{"hook_event_name": "Stop"}', "", "nope"])
def test_the_hook_says_nothing_for_other_events_or_bad_input(tmp_path: Path, text: str) -> None:
    path = tmp_path / "q.json"
    limits.statusline(_payload(90), config=_config(), now=NOON, path=path, extra=lambda: [])
    assert limits.hook(text, config=_config(), now=NOON, path=path) is None


def test_the_hook_without_readings_says_nothing(tmp_path: Path) -> None:
    event = json.dumps({"hook_event_name": "UserPromptSubmit"})
    assert limits.hook(event, config=_config(), now=NOON, path=tmp_path / "none.json") is None


def test_an_unknown_home_never_breaks_the_line_or_the_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Code review #34: ``Path.home()`` raises RuntimeError when no home can be found."""
    from orkestra import paths

    def no_home() -> Path:
        raise RuntimeError("Could not determine home directory.")

    def broken() -> Config:
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(paths, "orkestra_home", no_home)
    line = limits.run_statusline(_payload(40), load_config=broken, connect=_no_db, now=NOON)
    assert line.startswith("Claude")
    event = json.dumps({"hook_event_name": "UserPromptSubmit"})
    assert limits.run_hook(event, load_config=_config, now=NOON) is None


def test_bad_rows_in_the_database_leave_out_orkestras_part(tmp_path: Path) -> None:
    import sqlite3

    from orkestra.state import db

    def connect() -> sqlite3.Connection:
        conn = db.connect(tmp_path / "s.db")
        conn.execute("INSERT INTO health (provider, open_until, open_reason) "
                     "VALUES ('agy', 'not a time', 'quota')")  # fmt: skip
        conn.commit()
        return conn

    line = limits.run_statusline(_payload(40), load_config=_config, connect=connect, now=NOON)
    assert line.startswith("Claude")


def _no_db() -> Any:
    raise OSError("no database")


def test_the_line_is_translated() -> None:
    from orkestra import i18n

    window = limits.Window("five_hour", 72, RESETS, None)
    i18n.set_language("tr")
    assert limits.window_text(window) == "5sa 72%"
    i18n.set_language("en")
    assert limits.window_text(window) == "5h 72%"


def test_the_settings_snippet_wires_the_line_and_the_hooks() -> None:
    snippet = json.loads(limits.settings_snippet())
    assert snippet["statusLine"] == {"type": "command", "command": "orkestra statusline"}
    for event in ("UserPromptSubmit", "PostToolUse"):
        [entry] = snippet["hooks"][event]
        assert entry["hooks"] == [{"type": "command", "command": "orkestra statusline hook"}]
