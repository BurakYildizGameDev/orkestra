"""The terminal interface and its wizard, driven by Textual's pilot (Faz 11b, Mimari §22)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from textual.widgets import DataTable, Input, Select, Static, TabbedContent

from orkestra import i18n
from orkestra.cli import app as cli_app
from orkestra.config import loader
from orkestra.i18n import t, t_in
from orkestra.tui import detect
from orkestra.tui.app import OrkestraApp, QuestionScreen

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

BASE = """\
# my global config
version: 1
language: en   # keep it English
providers:
  local:
    type: ollama          # the box under my desk
    models:
      - id: qwen2.5-coder:7b
        tier: 1
    budget:
      daily_requests: 100   # be gentle
  codex:
    type: cli_agent
    command: codex
"""


def _found(*, keys: tuple[str, ...] = ()) -> detect.Detection:
    return detect.Detection(
        ollama=detect.OllamaFound(detect.OLLAMA_URL, False, ()),
        agents=tuple(detect.AgentFound(name, None, None) for name in detect.AGENTS),
        keys=tuple(detect.KeyFound(api, api.env in keys) for api in detect.KNOWN_APIS),
    )


@pytest.fixture
def base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    path = tmp_path / "home" / "config.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(BASE.encode("utf-8"))
    return path


async def _question(pilot: object, app: OrkestraApp) -> QuestionScreen:
    """Wait until the wizard's next question is on screen and its input has the focus."""
    from textual.pilot import Pilot

    assert isinstance(pilot, Pilot)
    for _ in range(300):
        screen = app.screen
        mounted = isinstance(screen, QuestionScreen) and screen.query("#question-input")
        if mounted and app.focused is screen.query_one("#question-input"):
            assert isinstance(screen, QuestionScreen)
            return screen
        await pilot.pause(0.02)
    raise AssertionError("the wizard asked no question")


async def _answer(pilot: object, app: OrkestraApp, text: str) -> None:
    """Type ``text`` into the next question and press Enter, as a user would."""
    from textual.pilot import Pilot

    assert isinstance(pilot, Pilot)
    screen = await _question(pilot, app)
    screen.query_one(Input).value = text
    await pilot.press("enter")
    await pilot.pause(0.02)


async def _finished(pilot: object, app: OrkestraApp) -> None:
    from textual.pilot import Pilot

    assert isinstance(pilot, Pilot)
    for _ in range(300):
        if app.wizard_done:
            return
        await pilot.pause(0.02)
    raise AssertionError("the wizard did not finish")


# --- the wizard -----------------------------------------------------------------------------


async def test_the_wizard_with_only_openrouter_writes_no_ollama_and_keeps_comments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "home" / "config.yaml"
    app = OrkestraApp(config_flag=target, mode="wizard", found=_found(keys=("OPENROUTER_API_KEY",)))
    from orkestra.tui import wizard

    number = str(wizard.candidate_names().index("openrouter") + 1)
    async with app.run_test(size=(120, 40)) as pilot:
        for answer in ("en", number, "x/model", "", "", "n",  # language … project
                       "n",                                   # consent (after saving)
                       "n"):  # doctor  # fmt: skip
            await _answer(pilot, app, answer)
        await _finished(pilot, app)
    config = loader.load_config(target).config
    assert set(config.providers) == {"openrouter"}
    assert "ollama" not in target.read_text(encoding="utf-8").split("chiefs:")[0]
    assert target.read_text(encoding="utf-8").startswith("# Orkestra configuration.")
    assert app.wizard_error is None


async def test_escape_cancels_the_wizard_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "home" / "config.yaml"
    app = OrkestraApp(config_flag=target, mode="wizard", found=_found())
    async with app.run_test(size=(120, 40)) as pilot:
        await _question(pilot, app)
        await pilot.press("escape")
        await _finished(pilot, app)
    assert not target.exists()
    assert app.wizard_error == t("wizard.cancelled")


# --- orkestra ui ----------------------------------------------------------------------------


async def test_turning_a_provider_off_keeps_the_handwritten_comments(base: Path) -> None:
    app = OrkestraApp(config_flag=base, mode="ui")
    async with app.run_test(size=(140, 45)) as pilot:
        app.query_one(TabbedContent).active = "providers"
        await pilot.pause()
        table = app.query_one("#providers-table", DataTable)
        table.move_cursor(row=0)  # "local"
        await pilot.click("#provider-toggle")
        await pilot.pause()
    config = loader.load_config(base).config
    assert config.providers["local"].enabled is False
    text = base.read_text(encoding="utf-8")
    for comment in ("# my global config", "# keep it English", "# the box under my desk",
                    "# be gentle"):  # fmt: skip
        assert comment in text


async def test_an_invalid_budget_is_not_saved_and_the_error_is_in_the_chosen_language(
    base: Path,
) -> None:  # fmt: skip
    i18n.set_language("tr")
    before = base.read_bytes()
    app = OrkestraApp(config_flag=base, mode="ui")
    async with app.run_test(size=(140, 45)) as pilot:
        app.query_one(TabbedContent).active = "budgets"
        await pilot.pause()
        app.query_one("#budget-provider", Select).value = "local"
        app.query_one("#budget-field", Select).value = "daily_requests"
        app.query_one("#budget-value", Input).value = "-5"
        await pilot.click("#budget-save")
        await pilot.pause()
        message = str(app.query_one("#budget-message", Static).render())
    assert base.read_bytes() == before
    assert message.startswith(t_in("tr", "config.error.invalid", sources=base))
    i18n.set_language("en")


async def test_changing_the_language_changes_the_interface_at_once(base: Path) -> None:
    app = OrkestraApp(config_flag=base, mode="ui")
    async with app.run_test(size=(140, 45)) as pilot:
        app.query_one(TabbedContent).active = "settings"
        await pilot.pause()
        assert str(app.query_one("#settings-title", Static).render()) == t_in(
            "en", "ui.settings.title"
        )
        app.query_one("#settings-language", Select).value = "tr"
        await pilot.click("#settings-save")
        await pilot.pause()
        app.query_one(TabbedContent).active = "settings"
        await pilot.pause()
        title = str(app.query_one("#settings-title", Static).render())
    assert title == t_in("tr", "ui.settings.title")
    assert loader.load_config(base).config.language == "tr"
    assert "# keep it English" in base.read_text(encoding="utf-8")
    i18n.set_language("en")


async def test_the_status_tab_shows_the_status_report(base: Path) -> None:
    app = OrkestraApp(config_flag=base, mode="ui")
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        text = str(app.query_one("#status-text", Static).render())
    assert "local" in text


# --- the CLI side ---------------------------------------------------------------------------


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        cli_app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    return (
        (code if isinstance(code, int) else 0),
        _ANSI.sub("", captured.out),
        _ANSI.sub("", captured.err),
    )


@pytest.mark.parametrize("term", ["dumb", None])
def test_ui_without_a_usable_terminal_says_so_and_suggests_plain(
    term: str | None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    """``TERM=dumb`` (or no terminal, as under pytest) cannot show the interface."""
    if term is None:
        monkeypatch.delenv("TERM", raising=False)
    else:
        monkeypatch.setenv("TERM", term)
    code, _, err = _run(["ui"], capsys)
    assert code == 2
    assert t("ui.error.no_terminal") in err


async def test_consent_is_given_only_after_the_description_is_confirmed(base: Path) -> None:
    from orkestra.tui.app import ConfirmScreen

    app = OrkestraApp(config_flag=base, mode="ui")
    async with app.run_test(size=(140, 45)) as pilot:
        app.query_one(TabbedContent).active = "consent"
        await pilot.pause()
        app.query_one("#consent-table", DataTable).move_cursor(row=0)  # "local"
        await pilot.click("#consent-grant")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.click("#confirm-no")
        await pilot.pause()
        assert app.provider_rows()[0].consent == "missing"
        await pilot.click("#consent-grant")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        assert app.provider_rows()[0].consent == "granted"


def test_a_bare_init_under_term_dumb_asks_plain_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    import io

    from orkestra import cli, paths
    from orkestra.tui import app as tui_app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_at_terminal", lambda: True)
    monkeypatch.setattr(tui_app, "usable_terminal", lambda: False)
    monkeypatch.setattr(detect, "detect", lambda **kwargs: _found())
    from orkestra.tui import wizard

    number = str(wizard.candidate_names().index("codex") + 1)
    answers = ["en", number, "", "", "n", "n"]  # runs, project, consent, doctor
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(answers) + "\n"))
    code, out, err = _run(["init"], capsys)
    assert code == 0, err
    assert t("wizard.ask.providers") in out
    assert "codex" in loader.load_config(paths.orkestra_home() / "config.yaml").config.providers


async def test_the_provider_test_runs_that_providers_doctor_checks_only() -> None:
    """A disabled provider: its one doctor line, and no network or process at all."""
    from orkestra import doctor
    from orkestra.config.schema import CliAgentProvider, Config

    config = Config(version=1, providers={
        "codex": CliAgentProvider(type="cli_agent", command="codex", enabled=False),
    })  # fmt: skip
    checks = await doctor.check_one("codex", config)
    assert [(check.name, check.status) for check in checks] == [("provider:codex", "info")]
    lines = doctor.report_lines(doctor.DoctorReport(tuple(checks)))
    assert lines[-1] == t("doctor.summary.ok")
