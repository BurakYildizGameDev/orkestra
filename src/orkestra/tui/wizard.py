"""The setup wizard's flow and what it writes (Mimari §22, Faz 11a).

The flow does not know how it asks: ``run_plain`` talks to a ``Prompter`` (``init --plain``
gives it ``typer.prompt``; the Faz 11b terminal interface gives it its screens), and
``defaults_answers`` answers everything from detection alone (``init --defaults``). Both end in
``save_answers``, which writes through ``config.writer`` (comments kept, validated, ``.bak``,
atomic) and records consent only for providers the user explicitly confirmed. ``--defaults``
never grants consent: consent is always an explicit user action.

Steps: language → detection → providers (detected ones preselected, at least one) → model
tiers → budget → consent → where to save (global or project).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import TypeAdapter
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from orkestra.config import loader, writer
from orkestra.config.schema import Provider
from orkestra.i18n import SUPPORTED_LANGUAGES, t
from orkestra.providers import registry
from orkestra.state import consent, db
from orkestra.tui import detect

LANGUAGE_CHOICES = ("auto", *SUPPORTED_LANGUAGES)
CHIEFS = ("claude", "codex", "agy")  # the default chiefs, in the order a default is picked
AGENT_DAILY_RUNS = {"codex": 20, "agy": 10}
LOCAL_TIER = 1
API_TIER = 2
AGENT_TIER = 3
API_DAILY_USD = 2.0
TIERS = ("1", "2", "3")

_PROVIDER: TypeAdapter[Any] = TypeAdapter(Provider)

# Yes/no in every supported language, so a Turkish user can answer "e"/"h" (typer's own
# confirm only knows y/n and complains in English).
YES_WORDS = frozenset({"y", "yes", "e", "evet", "j", "ja", "s", "si", "sí", "o", "oui"})
NO_WORDS = frozenset({"n", "no", "h", "hayır", "hayir", "nein", "non"})


def yes_no(raw: str) -> bool | None:
    """``True``/``False`` for a yes/no word in any supported language, else ``None``."""
    word = raw.strip().lower()
    if word in YES_WORDS:
        return True
    if word in NO_WORDS:
        return False
    return None


class Prompter(Protocol):
    def say(self, text: str) -> None: ...

    def ask(self, text: str, default: str | None = None) -> str: ...

    def confirm(self, text: str, default: bool = False) -> bool: ...


@dataclass
class ProviderPick:
    name: str
    settings: dict[str, Any]  # plain data for ``providers.<name>``
    consent: bool = False

    @property
    def enabled(self) -> bool:
        return self.settings.get("enabled", True) is not False


@dataclass
class Answers:
    providers: list[ProviderPick] = field(default_factory=list)
    language: str | None = None
    chief: str | None = None
    project: bool = False
    notes: list[str] = field(default_factory=list)  # shown to the user, already translated


@dataclass(frozen=True)
class Outcome:
    path: Path
    written: bool
    backup: Path | None = None
    gitignore: Path | None = None
    providers: list[str] = field(default_factory=list)
    consent: list[str] = field(default_factory=list)  # providers whose consent was recorded


# --- provider settings -------------------------------------------------------------------


def candidate_names() -> list[str]:
    """Everything the wizard can set up, in the order it lists them."""
    return ["ollama", *(api.name for api in detect.KNOWN_APIS), "codex", "agy"]


def ollama_settings(url: str, models: list[tuple[str, int]]) -> dict[str, Any]:
    return {
        "type": "ollama",
        "base_url": url,
        "local": True,
        "models": [{"id": model, "tier": tier} for model, tier in models],
    }


def api_settings(
    api: detect.KnownApi, model: str, tier: int, daily_usd: float | None
) -> dict[str, Any]:
    return {
        "type": "openai_compat",
        "base_url": api.base_url,
        "api_key_env": api.env,  # the variable's name; the key itself never enters the file
        "models": [{"id": model, "tier": tier}],
        "budget": {} if daily_usd is None else {"daily_usd": daily_usd},
    }


def agent_settings(name: str, *, daily_runs: int, enabled: bool = True) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "type": "cli_agent",
        "command": name,
        "tier": AGENT_TIER,
        "budget": {"daily_runs": daily_runs},
    }
    if name == "agy":
        settings["experimental"] = True
    if not enabled:
        settings["enabled"] = False
    return settings


# --- --defaults --------------------------------------------------------------------------


def defaults_answers(found: detect.Detection) -> Answers:
    """Turn on what was found; ask nothing and grant no consent (Mimari §22)."""
    picks: list[ProviderPick] = []
    if found.ollama.reachable and found.ollama.models:
        models = [(model, LOCAL_TIER) for model in found.ollama.models]
        picks.append(ProviderPick("ollama", ollama_settings(found.ollama.url, models)))
    for name in ("codex", "agy"):
        agent = found.agent(name)
        if agent is not None and agent.found:
            # agy is experimental: written, but off until the user turns it on
            settings = agent_settings(name, daily_runs=AGENT_DAILY_RUNS[name],
                                      enabled=name != "agy")  # fmt: skip
            picks.append(ProviderPick(name, settings))
    notes = [t("wizard.note.key_needs_model", env=key.api.env) for key in found.keys if key.present]
    if not picks:
        notes.append(t("wizard.note.nothing_found"))
    return Answers(providers=picks, chief=_default_chief(found), notes=notes)


def _default_chief(found: detect.Detection) -> str | None:
    for name in CHIEFS:
        agent = found.agent(name)
        if agent is not None and agent.found:
            return name
    return None


# --- --plain (and later the terminal interface) -------------------------------------------


def run_plain(
    ask: Prompter,
    found: detect.Detection,
    *,
    set_language: Callable[[str], None],
    project: bool | None = None,
) -> Answers:
    """Ask every step; a wrong answer is asked again with the reason."""
    choices = ", ".join(LANGUAGE_CHOICES)
    language = _choice(ask, t("wizard.ask.language", choices=choices), LANGUAGE_CHOICES, "auto")
    if language != "auto":
        set_language(language)  # every following question is in the chosen language

    ask.say(t("wizard.detected"))
    for line in detect.summary_lines(found):
        ask.say(f"  {line}")

    picks = [_pick(ask, name, found) for name in _choose_providers(ask, found)]
    for pick in picks:
        if not pick.enabled:
            continue  # a provider that stays off needs no consent yet
        for line in consent.describe(pick.name, _PROVIDER.validate_python(pick.settings)):
            ask.say(line)
        pick.consent = ask.confirm(t("consent.confirm"), default=False)

    chief: str | None = None
    if (default_chief := _default_chief(found)) is not None:
        chief = _choice(ask, t("wizard.ask.chief", choices=", ".join(CHIEFS)), CHIEFS,
                        default_chief)  # fmt: skip
    if project is None:
        project = ask.confirm(t("wizard.ask.project"), default=False)
    return Answers(providers=picks, language=language, chief=chief, project=project)


def _detected(name: str, found: detect.Detection) -> bool:
    if name == "ollama":
        return found.ollama.reachable
    agent = found.agent(name)
    if agent is not None:
        return agent.found
    return any(key.present for key in found.keys if key.api.name == name)


def _choose_providers(ask: Prompter, found: detect.Detection) -> list[str]:
    names = candidate_names()
    ask.say(t("wizard.providers.title"))
    for number, name in enumerate(names, start=1):
        mark = t("wizard.providers.found") if _detected(name, found) else ""
        ask.say(t("wizard.providers.item", number=number, name=name, mark=mark).rstrip())
    preselected = [str(n) for n, name in enumerate(names, start=1) if _detected(name, found)]
    while True:
        raw = ask.ask(t("wizard.ask.providers"), ",".join(preselected) or None)
        numbers = _numbers(raw, len(names))
        if numbers:
            return [names[number - 1] for number in numbers]
        ask.say(t("wizard.error.providers"))


def _pick(ask: Prompter, name: str, found: detect.Detection) -> ProviderPick:
    if name == "ollama":
        return ProviderPick(name, ollama_settings(found.ollama.url, _ollama_models(ask, found)))
    if name in AGENT_DAILY_RUNS:
        enabled = True
        if name == "agy":
            ask.say(t("wizard.agy.experimental"))
            enabled = ask.confirm(t("wizard.ask.agy_enable"), default=False)
        runs = AGENT_DAILY_RUNS[name]
        if enabled:
            runs = int(_number(ask, t("wizard.ask.daily_runs", name=name), runs, integer=True))
        return ProviderPick(name, agent_settings(name, daily_runs=runs, enabled=enabled))
    api = next(api for api in detect.KNOWN_APIS if api.name == name)
    model = _required(ask, t("wizard.ask.api_model", name=name))
    tier = _tier(ask, t("wizard.ask.tier", model=model), API_TIER)
    usd = _number(ask, t("wizard.ask.daily_usd", name=name), API_DAILY_USD, integer=False)
    return ProviderPick(name, api_settings(api, model, tier, usd))


def _ollama_models(ask: Prompter, found: detect.Detection) -> list[tuple[str, int]]:
    available = list(found.ollama.models)
    if available:
        for number, model in enumerate(available, start=1):
            ask.say(t("wizard.ollama.model", number=number, name=model))
        everything = ",".join(str(n) for n in range(1, len(available) + 1))
        while True:
            numbers = _numbers(ask.ask(t("wizard.ask.ollama_models"), everything), len(available))
            if numbers:
                break
            ask.say(t("wizard.error.numbers"))
        chosen = [available[number - 1] for number in numbers]
    else:
        chosen = [_required(ask, t("wizard.ask.ollama_model"))]
    return [(model, _tier(ask, t("wizard.ask.tier", model=model), LOCAL_TIER)) for model in chosen]


def _numbers(raw: str, count: int) -> list[int]:
    """``"1, 3,3"`` → ``[1, 3]``; empty if anything is not a number from 1 to ``count``."""
    numbers: list[int] = []
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        if not part.isdigit() or not 1 <= int(part) <= count:
            return []
        if int(part) not in numbers:
            numbers.append(int(part))
    return sorted(numbers)


def _choice(ask: Prompter, text: str, choices: tuple[str, ...], default: str) -> str:
    while True:
        raw = ask.ask(text, default).strip().lower()
        if raw in choices:
            return raw
        ask.say(t("wizard.error.choice", value=raw, choices=", ".join(choices)))


def _required(ask: Prompter, text: str) -> str:
    while True:
        raw = ask.ask(text, None).strip()
        if raw:
            return raw
        ask.say(t("wizard.error.required"))


def _tier(ask: Prompter, text: str, default: int) -> int:
    while True:
        raw = ask.ask(text, str(default)).strip()
        if raw in TIERS:
            return int(raw)
        ask.say(t("wizard.error.tier", value=raw))


def _number(ask: Prompter, text: str, default: float, *, integer: bool) -> float:
    shown = str(int(default)) if integer else f"{default:g}"
    while True:
        raw = ask.ask(text, shown).strip()
        try:
            value = int(raw) if integer else float(raw)
        except ValueError:
            ask.say(t("wizard.error.number", value=raw))
            continue
        if not math.isfinite(value) or value < 0:
            ask.say(t("wizard.error.number_min", value=raw, min=0))
            continue
        return value


# --- writing -----------------------------------------------------------------------------


def apply(document: CommentedMap, answers: Answers, *, fresh: bool) -> CommentedMap:
    """Put the answers into ``document`` without touching anything else in it.

    ``fresh`` (a new file from the example): providers that were not picked are removed. In
    an existing file they are only turned off (``enabled: false``); nothing the user wrote is
    deleted.
    """
    if answers.language is not None:
        document["language"] = answers.language
    if answers.chief is not None:
        _mapping(document, "defaults")["chief"] = answers.chief
    providers = _mapping(document, "providers")
    picked = {pick.name for pick in answers.providers}
    for name in list(providers):
        if name in picked:
            continue
        if fresh:
            del providers[name]
        elif isinstance(providers[name], CommentedMap):
            providers[name]["enabled"] = False
    for pick in answers.providers:
        entry = providers.get(name := pick.name)
        if not isinstance(entry, CommentedMap):
            entry = providers[name] = CommentedMap()
        if fresh and "budget" in pick.settings:
            # the example's own limits are examples, not choices; a user file keeps its own
            entry["budget"] = _yaml_value(pick.settings["budget"])
        _merge(entry, pick.settings)
        if pick.enabled and "enabled" in entry:
            entry["enabled"] = True
    return document


def _mapping(document: CommentedMap, key: str) -> CommentedMap:
    value = document.get(key)
    if not isinstance(value, CommentedMap):
        value = document[key] = CommentedMap()
    return value


def _merge(target: CommentedMap, values: Mapping[str, Any]) -> None:
    """Set ``values`` in place: nested mappings merge (comments on their keys stay), lists and
    scalars replace."""
    for key, value in values.items():
        current = target.get(key)
        if isinstance(value, Mapping) and isinstance(current, CommentedMap):
            _merge(current, value)
        else:
            target[key] = _yaml_value(value)


def _yaml_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        mapping = CommentedMap()
        for key, item in value.items():
            mapping[key] = _yaml_value(item)
        return mapping
    if isinstance(value, list):
        return CommentedSeq([_yaml_value(item) for item in value])
    return value


def save_answers(
    answers: Answers,
    *,
    config_flag: Path | None,
    now: datetime,
    fresh: bool | None = None,
    cwd: Path | None = None,
) -> Outcome:
    """Write the answers (global or project file) and record the confirmed consents.

    ``fresh=None``: start from the example when the file does not exist yet, otherwise edit
    the file in place. ``--defaults`` passes ``True`` (``--force`` already allowed replacing).
    """
    workdir = Path.cwd() if cwd is None else cwd
    target = loader.init_target(config_flag, project=answers.project, cwd=workdir)
    base = loader.base_config_target(config_flag)[0] if answers.project else None
    from_example = not target.exists() if fresh is None else fresh
    document = writer.template_document() if from_example else writer.load_document(target)
    result = writer.save(target, apply(document, answers, fresh=from_example), base=base)
    granted: list[str] = []
    confirmed = [pick for pick in answers.providers if pick.consent and pick.enabled]
    if confirmed:
        with closing(db.connect()) as conn:
            for pick in confirmed:
                registry.enable_provider(conn, pick.name, result.config.providers[pick.name], now)
                granted.append(pick.name)
    gitignore: Path | None = None
    if answers.project:
        root = loader.find_git_root(workdir.resolve())
        if root is not None and loader.ensure_gitignore_entry(root / ".gitignore"):
            gitignore = root / ".gitignore"
    return Outcome(target, True, result.backup, gitignore,
                   [pick.name for pick in answers.providers], granted)  # fmt: skip
