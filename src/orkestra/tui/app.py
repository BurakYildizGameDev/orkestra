"""The terminal interface: ``orkestra ui`` and the setup wizard of ``orkestra init`` (Faz 11b).

Screens hold no business logic (Mimari §22): config changes go through ``config.edits`` (one
value, the right file, comments kept, validated before writing), status and budgets come from
``chief.status`` and ``providers.registry``, consent from ``state.consent``, the brief from
``handoff.brief``. The wizard is the very same ``tui.wizard`` flow ``init --plain`` runs; here a
worker thread drives it and every question is a small screen (Escape cancels).

Every text is ``t()``; when the language is changed in Settings the whole interface is built
again in the new language at once.
"""

from __future__ import annotations

import asyncio
import os
import queue
import sys
from collections.abc import Callable, Mapping
from contextlib import closing
from pathlib import Path
from typing import Any, ClassVar, Literal, TextIO

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Header,
    Input,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from orkestra import doctor, i18n
from orkestra.chief import status
from orkestra.config import edits, loader
from orkestra.config.schema import Config
from orkestra.errors import ConfigError, OrkestraError, WizardCancelled
from orkestra.handoff import brief as handoff_brief
from orkestra.handoff import store as handoff_store
from orkestra.i18n import t
from orkestra.providers import display, registry
from orkestra.state import consent, db
from orkestra.tui import detect, wizard

Mode = Literal["ui", "wizard"]
BUDGET_FIELDS = ("daily_tokens", "daily_usd", "daily_requests", "daily_runs")
INTEGER_FIELDS = frozenset({"daily_tokens", "daily_requests", "daily_runs"})
ANSWER_POLL_S = 0.2  # how often a waiting question checks that the app still runs
TABS = ("status", "providers", "budgets", "profiles", "consent", "handoff", "settings")


def usable_terminal(
    environ: Mapping[str, str] | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> bool:
    """The interface needs a real terminal; ``TERM=dumb`` or a pipe cannot show it."""
    env = os.environ if environ is None else environ
    if env.get("TERM", "").strip().lower() == "dumb":
        return False
    return (stdin or sys.stdin).isatty() and (stdout or sys.stdout).isatty()


def error_text(exc: OrkestraError) -> str:
    return "\n".join([exc.message, *(f"  - {detail}" for detail in exc.details)])


# --- the wizard ------------------------------------------------------------------------------


class QuestionScreen(ModalScreen[str | None]):
    """One wizard question: Enter answers (an empty answer takes the default), Escape cancels."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", show=False)]
    AUTO_FOCUS = "#question-input"  # Enter must reach the answer
    DEFAULT_CSS = """
    QuestionScreen { align: center middle; }
    #question { width: 90%; height: auto; border: round $accent; padding: 1 2;
                background: $panel; }
    """

    def __init__(self, text: str, default: str | None) -> None:
        super().__init__()
        self._text = text
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="question"):
            yield Static(self._text, id="question-text", markup=False)
            yield Input(value=self._default or "", id="question-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class _ThreadPrompter:
    """The wizard's ``Prompter`` from a worker thread: each question waits for its screen."""

    def __init__(self, app: OrkestraApp) -> None:
        self._app = app

    def _running(self) -> None:
        if not self._app.is_running:  # Ctrl+Q while a question was open: stop, never hang
            raise WizardCancelled(t("wizard.cancelled"))

    def say(self, text: str) -> None:
        self._running()
        self._app.call_from_thread(self._app.wizard_say, text)

    def ask(self, text: str, default: str | None = None) -> str:
        self._running()
        answers: queue.Queue[str | None] = queue.Queue()
        self._app.call_from_thread(self._app.push_screen, QuestionScreen(text, default),
                                   answers.put)  # fmt: skip
        while True:
            try:
                answer = answers.get(timeout=ANSWER_POLL_S)
                break
            except queue.Empty:
                self._running()
        if answer is None:
            raise WizardCancelled(t("wizard.cancelled"))
        return default if not answer.strip() and default is not None else answer

    def confirm(self, text: str, default: bool = False) -> bool:
        return wizard.confirm_by_asking(self.ask, self.say, text, default)


# --- confirming consent ----------------------------------------------------------------------


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "no", show=False)]
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    #confirm { width: 90%; height: auto; border: round $warning; padding: 1 2;
               background: $panel; }
    """

    def __init__(self, lines: list[str]) -> None:
        super().__init__()
        self._lines = lines

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm"):
            yield Static("\n".join(self._lines), markup=False)
            yield Static(t("consent.confirm"), markup=False)
            with Horizontal():
                yield Button(t("ui.button.yes"), id="confirm-yes", variant="warning")
                yield Button(t("ui.button.no"), id="confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm-yes")

    def action_no(self) -> None:
        self.dismiss(False)


# --- the panes of ``orkestra ui`` ---------------------------------------------------------------


class _Pane(VerticalScroll):
    """A tab. ``reload`` reads fresh data; nothing here decides anything."""

    @property
    def orkestra(self) -> OrkestraApp:
        app = self.app
        assert isinstance(app, OrkestraApp)
        return app

    def on_mount(self) -> None:
        self.reload()

    def reload(self) -> None:
        """Read the data again (after a change)."""

    def message(self, widget_id: str, text: str) -> None:
        self.query_one(f"#{widget_id}", Static).update(text)


class StatusPane(_Pane):
    def compose(self) -> ComposeResult:
        yield Static("", id="status-text", markup=False)
        yield Button(t("ui.button.refresh"), id="status-refresh")

    def reload(self) -> None:
        self.message("status-text", self.orkestra.guard(self.orkestra.status_text))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "status-refresh":
            event.stop()
            self.reload()


class ProvidersPane(_Pane):
    def compose(self) -> ComposeResult:
        yield DataTable(id="providers-table", cursor_type="row")
        with Horizontal():
            yield Button(t("ui.button.toggle"), id="provider-toggle")
            yield Button(t("ui.button.test"), id="provider-test")
        yield Static("", id="providers-message", markup=False)

    def reload(self) -> None:
        table = self.query_one("#providers-table", DataTable)
        table.clear(columns=True)
        table.add_columns(t("ui.column.provider"), t("ui.column.details"))
        rows = self.orkestra.provider_rows()
        self.names = [row.name for row in rows]
        for row in rows:
            table.add_row(row.name, display.row_text(row).removeprefix(f"{row.name}: "))

    def selected(self) -> str | None:
        table = self.query_one("#providers-table", DataTable)
        names: list[str] = getattr(self, "names", [])
        return names[table.cursor_row] if 0 <= table.cursor_row < len(names) else None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        name = self.selected()
        if event.button.id not in ("provider-toggle", "provider-test"):
            return
        event.stop()
        if name is None:
            self.message("providers-message", t("ui.error.choose"))
            return
        if event.button.id == "provider-toggle":
            config = self.orkestra.config()
            enabled = config is not None and config.providers[name].enabled
            saved = self.orkestra.save(("providers", name, "enabled"), not enabled)
            self.message("providers-message", saved)
            self.reload()
        else:
            self.message("providers-message", t("ui.test.running", name=name))
            self.orkestra.test_provider(name, lambda text: self.message("providers-message", text))


class BudgetsPane(_Pane):
    def compose(self) -> ComposeResult:
        names = self.orkestra.provider_names()
        yield Static("", id="budget-table", markup=False)
        yield Select([(name, name) for name in names], id="budget-provider",
                     prompt=t("ui.budget.provider"))  # fmt: skip
        yield Select([(field, field) for field in BUDGET_FIELDS], id="budget-field",
                     prompt=t("ui.budget.field"))  # fmt: skip
        yield Input(placeholder=t("ui.budget.placeholder"), id="budget-value")
        yield Button(t("ui.button.save"), id="budget-save")
        yield Static("", id="budget-message", markup=False)

    def reload(self) -> None:
        lines = [display.budget_text(row) for row in self.orkestra.provider_rows()]
        self.message("budget-table", "\n".join(lines) or t("select.no_providers"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "budget-save":
            return
        event.stop()
        provider = self.query_one("#budget-provider", Select).value
        field = self.query_one("#budget-field", Select).value
        if not isinstance(provider, str) or not isinstance(field, str):
            self.message("budget-message", t("ui.error.choose"))
            return
        raw = self.query_one("#budget-value", Input).value.strip()
        value: float | None = None
        if raw:
            try:
                value = int(raw) if field in INTEGER_FIELDS else float(raw)
            except ValueError:
                self.message("budget-message", t("wizard.error.number", value=raw))
                return
        saved = self.orkestra.save(("providers", provider, "budget", field), value)
        self.message("budget-message", saved)
        self.reload()


class ProfilesPane(_Pane):
    def compose(self) -> ComposeResult:
        config = self.orkestra.config()
        profiles = sorted(config.profiles) if config is not None else []
        chiefs = sorted(config.chiefs) if config is not None else []
        yield Static(t("ui.profiles.profile"), markup=False)
        profile = config.defaults.profile if config is not None else Select.NULL
        yield Select(
            [(name, name) for name in profiles], id="defaults-profile", allow_blank=False,
            value=profile,
        )  # fmt: skip
        yield Static(t("ui.profiles.chief"), markup=False)
        chief = config.defaults.chief if config is not None else Select.NULL
        yield Select(
            [(name, name) for name in chiefs], id="defaults-chief", allow_blank=False, value=chief
        )
        yield Button(t("ui.button.save"), id="defaults-save")
        yield Static("", id="defaults-message", markup=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "defaults-save":
            return
        event.stop()
        lines = []
        for key, widget in (("profile", "#defaults-profile"), ("chief", "#defaults-chief")):
            value = self.query_one(widget, Select).value
            if isinstance(value, str):
                lines.append(self.orkestra.save(("defaults", key), value))
        self.message("defaults-message", "\n".join(lines))


class ConsentPane(_Pane):
    def compose(self) -> ComposeResult:
        yield DataTable(id="consent-table", cursor_type="row")
        with Horizontal():
            yield Button(t("ui.button.grant"), id="consent-grant", variant="warning")
            yield Button(t("ui.button.revoke"), id="consent-revoke")
        yield Static("", id="consent-message", markup=False)

    def reload(self) -> None:
        table = self.query_one("#consent-table", DataTable)
        table.clear(columns=True)
        table.add_columns(t("ui.column.provider"), t("ui.column.consent"))
        rows = self.orkestra.provider_rows()
        self.names = [row.name for row in rows]
        for row in rows:
            table.add_row(row.name, t(f"providers.consent.{row.consent}"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id not in ("consent-grant", "consent-revoke"):
            return
        event.stop()
        table = self.query_one("#consent-table", DataTable)
        names: list[str] = getattr(self, "names", [])
        if not 0 <= table.cursor_row < len(names):
            self.message("consent-message", t("ui.error.choose"))
            return
        name = names[table.cursor_row]
        if event.button.id == "consent-revoke":
            self.message("consent-message", self.orkestra.revoke(name))
            self.reload()
            return

        def answered(agreed: bool | None) -> None:
            if agreed:
                self.message("consent-message", self.orkestra.grant(name))
                self.reload()

        lines = self.orkestra.consent_description(name)
        self.orkestra.push_screen(ConfirmScreen(lines), answered)


class HandoffPane(_Pane):
    def compose(self) -> ComposeResult:
        yield Static("", id="handoff-text", markup=False)
        yield Button(t("ui.button.refresh"), id="handoff-refresh")

    def reload(self) -> None:
        self.message("handoff-text", self.orkestra.guard(self.orkestra.handoff_text))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "handoff-refresh":
            event.stop()
            self.reload()


class SettingsPane(_Pane):
    def compose(self) -> ComposeResult:
        config = self.orkestra.config()
        yield Static(t("ui.settings.title"), id="settings-title", markup=False)
        yield Static(t("ui.settings.language"), markup=False)
        yield Select([(code, code) for code in wizard.LANGUAGE_CHOICES], id="settings-language",
                     allow_blank=False,
                     value=config.language if config is not None else "auto")  # fmt: skip
        yield Button(t("ui.button.save"), id="settings-save")
        yield Static("", id="settings-message", markup=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "settings-save":
            return
        event.stop()
        language = self.query_one("#settings-language", Select).value
        if not isinstance(language, str):
            return
        app = self.orkestra
        text = app.save(("language",), language)
        if not app.last_save_ok:
            self.message("settings-message", text)
            return
        if language == "auto":
            i18n.init_language()
        else:
            i18n.set_language(language)
        # Rebuilt after this handler returns: this pane is replaced by the rebuild, and a
        # handler that waits for its own removal never finishes.
        app.call_later(app.rebuild, "settings", text)


# --- the app ---------------------------------------------------------------------------------


class OrkestraApp(App[None]):
    """``mode="ui"``: the tabs; ``mode="wizard"``: the setup wizard of ``orkestra init``."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("ctrl+q", "quit", show=False)]

    def __init__(
        self,
        *,
        config_flag: Path | None,
        mode: Mode = "ui",
        found: detect.Detection | None = None,
        project: bool = False,
        force: bool = False,
    ) -> None:
        super().__init__()
        self.config_flag = config_flag
        self.mode = mode
        self._found = found
        self._project = project
        self._force = force
        self.wizard_done = False
        self.wizard_error: str | None = None
        self.summary: list[str] = []  # the wizard's result, printed again after the app ends
        self.last_save_ok = False

    def compose(self) -> ComposeResult:
        yield Header()
        if self.mode == "wizard":
            yield RichLog(id="wizard-log", wrap=True, markup=False)
            yield Static(t("ui.wizard.hint"), id="hint", markup=False)
            return
        titles = {name: t(f"ui.tab.{name}") for name in TABS}
        panes: dict[str, Callable[[], _Pane]] = {
            "status": StatusPane, "providers": ProvidersPane, "budgets": BudgetsPane,
            "profiles": ProfilesPane, "consent": ConsentPane, "handoff": HandoffPane,
            "settings": SettingsPane,
        }  # fmt: skip
        with TabbedContent(initial="status"):
            for name in TABS:
                with TabPane(titles[name], id=name):
                    yield panes[name]()
        yield Static(t("ui.hint.keys"), id="hint", markup=False)

    def on_mount(self) -> None:
        self.title = t("ui.title")
        if self.mode == "wizard":
            self.run_worker(self._run_wizard, thread=True, exclusive=True)

    async def rebuild(self, active: str, settings_message: str = "") -> None:
        """Build every widget again, so all texts are in the current language."""
        self.title = t("ui.title")
        await self.recompose()
        self.query_one(TabbedContent).active = active
        if settings_message:
            self.query_one("#settings-message", Static).update(settings_message)

    # --- services the panes call (reading; writing goes through config.edits) --------------

    def config(self) -> Config | None:
        try:
            return loader.load_config(self.config_flag).config
        except ConfigError:
            return None

    def guard(self, produce: Callable[[], str]) -> str:
        try:
            return produce()
        except OrkestraError as exc:
            return error_text(exc)

    def status_text(self) -> str:
        config = loader.load_config(self.config_flag).config
        with closing(db.connect()) as conn:
            report = status.collect(status.default_context(config, conn, db.local_now()))
        return status.render(report)

    def provider_rows(self) -> list[registry.ProviderRow]:
        config = self.config()
        if config is None:
            return []
        with closing(db.connect()) as conn:
            return registry.provider_overview(config, conn, db.local_now())

    def provider_names(self) -> list[str]:
        config = self.config()
        return sorted(config.providers) if config is not None else []

    def handoff_text(self) -> str:
        config = loader.load_config(self.config_flag).config
        path = handoff_store.handoff_path(config, Path.cwd())
        if not path.exists():
            return t("ui.handoff.none", path=path)
        with closing(db.connect()) as conn:
            return handoff_brief.build(config, conn, db.local_now(), path=path,
                                       cwd=Path.cwd()).text  # fmt: skip

    def save(self, key_path: tuple[str, ...], value: Any) -> str:
        """Write one value; the message says where, or why it was not saved."""
        try:
            result = edits.set_value(key_path, value, config_flag=self.config_flag)
        except OrkestraError as exc:
            self.last_save_ok = False
            return error_text(exc)
        self.last_save_ok = True
        return t("ui.saved", path=result.path)

    def consent_description(self, name: str) -> list[str]:
        config = self.config()
        if config is None or name not in config.providers:
            return [t("ui.error.choose")]
        return consent.describe(name, config.providers[name])

    def grant(self, name: str) -> str:
        config = self.config()
        if config is None or name not in config.providers:
            return t("ui.error.choose")
        with closing(db.connect()) as conn:
            registry.enable_provider(conn, name, config.providers[name], db.local_now())
        return t("consent.granted", name=name)

    def revoke(self, name: str) -> str:
        with closing(db.connect()) as conn:
            removed = consent.revoke(conn, name)
        return t("consent.revoked" if removed else "consent.not_granted", name=name)

    def test_provider(self, name: str, show: Callable[[str], None]) -> None:
        """One provider's doctor checks in a worker; ``show`` gets the result lines."""
        config = self.config()
        if config is None:
            show(t("ui.error.choose"))
            return

        def work() -> None:
            checks = asyncio.run(doctor.check_one(name, config))
            report = doctor.DoctorReport(tuple(checks))
            self.call_from_thread(show, "\n".join(doctor.report_lines(report)))

        self.run_worker(work, thread=True, exclusive=True)

    # --- the wizard -------------------------------------------------------------------------

    def wizard_say(self, text: str) -> None:
        self.summary.append(text)
        self.query_one("#wizard-log", RichLog).write(text)

    def _run_wizard(self) -> None:
        prompter = _ThreadPrompter(self)
        try:
            found = self._found if self._found is not None else detect.detect()
            current = None if self._force else wizard.current_config(self.config_flag)
            answers = wizard.run_plain(prompter, found, set_language=i18n.set_language,
                                       project=True if self._project else None,
                                       current=current)  # fmt: skip
            outcome = wizard.save_answers(answers, config_flag=self.config_flag,
                                          now=db.local_now(),
                                          fresh=True if self._force else None)  # fmt: skip
            for line in wizard.outcome_lines(outcome, answers.notes):
                prompter.say(line)
            names = wizard.consent_names(answers)
            agreed = wizard.ask_consents(prompter, outcome.config, names)
            granted = wizard.record_consents(outcome.config, agreed, db.local_now())
            waiting = [name for name in names if name not in granted]
            for line in wizard.consent_lines(granted, waiting):
                prompter.say(line)
            if prompter.confirm(t("wizard.ask.doctor"), default=True):
                report = asyncio.run(doctor.run_doctor(config_flag=self.config_flag))
                for line in doctor.report_lines(report):
                    prompter.say(line)
            prompter.say(t("ui.wizard.done"))
        except OrkestraError as exc:
            self.wizard_error = exc.message
            self.summary.append(exc.message)
            if self.is_running:
                self.call_from_thread(self.query_one("#wizard-log", RichLog).write, exc.message)
        finally:
            self.wizard_done = True
