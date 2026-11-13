"""The setup wizard's flow, independent of how it asks (Faz 11a, Mimari §22)."""

from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

from orkestra import i18n
from orkestra.config import writer
from orkestra.config.schema import OllamaProvider
from orkestra.i18n import t, t_in
from orkestra.tui import detect, wizard

USER_FILE = """\
# my own notes at the top
version: 1
language: tr   # I read Turkish

providers:
  local:
    type: ollama          # the small box under my desk
    models:
      - id: qwen2.5-coder:7b
        tier: 1
    budget: {}
  codex:
    type: cli_agent
    command: codex
    budget:
      daily_runs: 5       # keep Codex cheap
"""

OPENROUTER = next(api for api in detect.KNOWN_APIS if api.name == "openrouter")


def _found(
    *, models: tuple[str, ...] = (), agents: tuple[str, ...] = (), keys: tuple[str, ...] = ()
) -> detect.Detection:
    return detect.Detection(
        ollama=detect.OllamaFound(detect.OLLAMA_URL, bool(models), models),
        agents=tuple(
            detect.AgentFound(name, f"/bin/{name}" if name in agents else None, None)
            for name in detect.AGENTS
        ),
        keys=tuple(detect.KeyFound(api, api.env in keys) for api in detect.KNOWN_APIS),
    )


def _openrouter_only() -> wizard.Answers:
    pick = wizard.ProviderPick("openrouter", wizard.api_settings(OPENROUTER, "x/model", 2, 1.5))
    return wizard.Answers(providers=[pick])


# --- applying answers to a config document -------------------------------------------------


def test_only_openrouter_in_a_fresh_config_leaves_no_ollama(tmp_path: Path) -> None:
    document = wizard.apply(writer.template_document(), _openrouter_only(), fresh=True)
    result = writer.save(tmp_path / "config.yaml", document)
    assert set(result.config.providers) == {"openrouter"}
    assert result.config.providers["openrouter"].budget.daily_usd == 1.5
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert text.startswith("# Orkestra configuration.")  # the example's comments stay
    assert "# auto | en | tr | de | es | fr" in text
    assert "ollama" not in text.split("chiefs:")[0]


def test_deselecting_in_an_existing_file_disables_instead_of_deleting(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(USER_FILE.encode("utf-8"))
    document = wizard.apply(writer.load_document(path), _openrouter_only(), fresh=False)
    result = writer.save(path, document)
    assert result.config.providers["local"].enabled is False
    assert result.config.providers["codex"].enabled is False
    assert result.config.providers["openrouter"].enabled is True
    text = path.read_text(encoding="utf-8")
    assert "# the small box under my desk" in text
    assert "# keep Codex cheap" in text
    assert "# my own notes at the top" in text


def test_a_picked_provider_that_exists_is_updated_in_place(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(USER_FILE.encode("utf-8"))
    answers = wizard.Answers(
        providers=[wizard.ProviderPick("codex", wizard.agent_settings("codex", daily_runs=20))]
    )
    result = writer.save(path, wizard.apply(writer.load_document(path), answers, fresh=False))
    assert result.config.providers["codex"].budget.daily_runs == 20
    assert result.config.providers["codex"].enabled is True
    assert "# the small box under my desk" in path.read_text(encoding="utf-8")


def test_language_and_chief_answers_are_written(tmp_path: Path) -> None:
    answers = _openrouter_only()
    answers.language = "tr"
    answers.chief = "codex"
    result = writer.save(tmp_path / "c.yaml", wizard.apply(writer.template_document(), answers,
                                                           fresh=True))  # fmt: skip
    assert result.config.language == "tr"
    assert result.config.defaults.chief == "codex"


# --- --defaults ------------------------------------------------------------------------------


def test_defaults_turn_on_what_was_found_and_grant_nothing(tmp_path: Path) -> None:
    found = _found(models=("qwen2.5-coder:14b", "llama3:8b"), agents=("codex", "agy", "claude"),
                   keys=("OPENROUTER_API_KEY",))  # fmt: skip
    answers = wizard.defaults_answers(found)
    assert [pick.name for pick in answers.providers] == ["ollama", "codex", "agy"]
    assert all(pick.consent is False for pick in answers.providers)
    assert answers.chief == "claude"
    assert answers.notes == [t("wizard.note.key_needs_model", env="OPENROUTER_API_KEY")]
    result = writer.save(tmp_path / "c.yaml", wizard.apply(writer.template_document(), answers,
                                                           fresh=True))  # fmt: skip
    ollama = result.config.providers["ollama"]
    assert isinstance(ollama, OllamaProvider)
    assert [(m.id, m.tier) for m in ollama.models] == [("qwen2.5-coder:14b", 1), ("llama3:8b", 1)]
    assert result.config.providers["codex"].enabled is True
    assert result.config.providers["agy"].enabled is False  # experimental stays off
    assert "openrouter" not in result.config.providers


def test_defaults_with_nothing_found_write_a_valid_config_without_providers(
    tmp_path: Path,
) -> None:
    answers = wizard.defaults_answers(_found())
    assert answers.providers == []
    assert answers.notes == [t("wizard.note.nothing_found")]
    result = writer.save(tmp_path / "c.yaml", wizard.apply(writer.template_document(), answers,
                                                           fresh=True))  # fmt: skip
    assert result.config.providers == {}


# --- --plain ---------------------------------------------------------------------------------


class Script:
    """Answers the wizard's questions in order and records what it was shown."""

    def __init__(self, *answers: str) -> None:
        self.answers = deque(answers)
        self.shown: list[str] = []
        self.asked: list[str] = []

    def say(self, text: str) -> None:
        self.shown.append(text)

    def ask(self, text: str, default: str | None = None) -> str:
        self.asked.append(text)
        answer = self.answers.popleft()
        return default if answer == "" and default is not None else answer

    def confirm(self, text: str, default: bool = False) -> bool:
        self.asked.append(text)
        answer = self.answers.popleft()
        return default if answer == "" else answer.lower() in ("y", "yes", "e", "evet")


def _number_of(name: str) -> str:
    return str(wizard.candidate_names().index(name) + 1)


@pytest.fixture
def english() -> None:
    i18n.set_language("en")


def test_the_plain_wizard_walks_every_step(english: None) -> None:
    script = Script(
        "en",                                   # language
        "",                                     # providers: the detected default (ollama, codex)
        "",                                     # ollama models: all
        "", "2",                                # tiers of the two models
        "",                                     # codex daily runs (default 20)
        "y",                                    # consent: ollama
        "n",                                    # consent: codex
        "",                                     # chief (default: the detected one)
        "",                                     # project? (default no)
    )  # fmt: skip
    found = _found(models=("small:1b", "big:14b"), agents=("codex",))
    answers = wizard.run_plain(script, found, set_language=i18n.set_language)
    assert [pick.name for pick in answers.providers] == ["ollama", "codex"]
    ollama = answers.providers[0].settings
    assert [(m["id"], m["tier"]) for m in ollama["models"]] == [("small:1b", 1), ("big:14b", 2)]
    assert answers.providers[1].settings["budget"] == {"daily_runs": 20}
    assert [pick.consent for pick in answers.providers] == [True, False]
    assert answers.chief == "codex"
    assert answers.project is False
    assert answers.language == "en"
    assert not script.answers  # every scripted answer was used


def test_the_wizard_switches_language_right_after_it_is_chosen() -> None:
    i18n.set_language("en")
    script = Script("tr", _number_of("codex"), "", "n", "", "")
    wizard.run_plain(script, _found(agents=("codex",)), set_language=i18n.set_language)
    assert script.asked[1] == t_in("tr", "wizard.ask.providers")
    i18n.set_language("en")


def test_a_wrong_answer_is_asked_again_with_the_reason(english: None) -> None:
    script = Script(
        "xx",                                   # not a language
        "en",
        "",                                     # no provider: nothing detected, no default
        "99",                                   # no such number
        _number_of("openrouter"),
        "",                                     # model id is required
        "my/model",
        "5",                                    # tier 5 does not exist
        "",                                     # tier default 2
        "-3",                                   # negative budget
        "abc",                                  # not a number
        "1.25",
        "n",                                    # consent
        "",                                     # project
    )  # fmt: skip
    answers = wizard.run_plain(script, _found(), set_language=i18n.set_language)
    settings = answers.providers[0].settings
    assert settings["models"] == [{"id": "my/model", "tier": 2}]
    assert settings["budget"] == {"daily_usd": 1.25}
    choices = ", ".join(wizard.LANGUAGE_CHOICES)
    assert t("wizard.error.choice", value="xx", choices=choices) in script.shown
    assert t("wizard.error.providers") in script.shown
    assert t("wizard.error.required") in script.shown
    assert t("wizard.error.tier", value="5") in script.shown
    assert t("wizard.error.number_min", value="-3", min=0) in script.shown
    assert t("wizard.error.number", value="abc") in script.shown


def test_agy_stays_off_unless_the_user_turns_it_on(english: None) -> None:
    script = Script("en", _number_of("agy"), "n", "", "")  # enable?, chief, project
    answers = wizard.run_plain(script, _found(agents=("agy",)), set_language=i18n.set_language)
    assert not script.answers
    assert answers.providers[0].settings["enabled"] is False
    assert answers.providers[0].consent is False  # a disabled provider is not asked for consent


def test_the_consent_step_shows_what_is_allowed(english: None) -> None:
    script = Script("en", _number_of("codex"), "", "y", "", "")
    wizard.run_plain(script, _found(agents=("codex",)), set_language=i18n.set_language)
    assert t("consent.describe.title", name="codex", type="cli_agent") in script.shown
    assert t("consent.confirm") in script.asked


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("y", True), ("Yes", True), ("e", True), ("evet", True), ("ja", True), ("oui", True),
     ("sí", True), ("n", False), ("h", False), ("hayır", False), ("nein", False),
     ("non", False), ("maybe", None), ("", None)],
)  # fmt: skip
def test_yes_and_no_are_understood_in_every_supported_language(
    raw: str, expected: bool | None,
) -> None:  # fmt: skip
    assert wizard.yes_no(raw) is expected


def test_a_fresh_config_has_exactly_the_budget_the_wizard_was_given(tmp_path: Path) -> None:
    """The example's own limits (openrouter: daily_tokens) must not sneak into a new file."""
    document = wizard.apply(writer.template_document(), _openrouter_only(), fresh=True)
    budget = writer.save(tmp_path / "c.yaml", document).config.providers["openrouter"].budget
    assert budget.model_dump(exclude_none=True) == {"daily_usd": 1.5}


def test_an_existing_file_keeps_the_limits_the_wizard_did_not_ask_about(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(USER_FILE.replace("daily_runs: 5", "daily_runs: 5\n      daily_usd: 1")
                     .encode("utf-8"))  # fmt: skip
    answers = wizard.Answers(
        providers=[wizard.ProviderPick("codex", wizard.agent_settings("codex", daily_runs=20))]
    )
    budget = writer.save(path, wizard.apply(writer.load_document(path), answers, fresh=False))
    assert budget.config.providers["codex"].budget.model_dump(exclude_none=True) == {
        "daily_runs": 20,
        "daily_usd": 1.0,
    }
