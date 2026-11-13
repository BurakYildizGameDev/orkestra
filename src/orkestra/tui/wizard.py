"""The setup wizard's flow and what it writes (Mimari §22, Faz 11a).

The flow does not know how it asks: ``run_plain`` talks to a ``Prompter`` (``init --plain``
gives it ``typer.prompt``; the Faz 11b terminal interface gives it its screens), and
``defaults_answers`` answers everything from detection alone (``init --defaults``). Both end in
``save_answers``, which writes through ``config.writer`` (comments kept, validated, backup,
atomic).

Consent comes **after** saving (``ask_consents`` + ``record_consents``): the user is shown the
entry exactly as it was saved, which is the same settings whose hash is recorded, and
``--defaults`` never asks, so it never grants anything (D-068).

Steps: language → detection → providers (preselected: the enabled ones of the current config
and the detected ones; at least one) → model tiers → budget → default chief → where to save
(global or project) → save → consent → doctor. Every default comes from the current config
when there is one, so pressing Enter changes nothing.

Editing an existing file never deletes what the user wrote: a provider the wizard offered and
the user did not pick is only turned off; a provider the wizard never offered (a custom one)
is left alone; the identity of an entry (``base_url``, ``command``, ``api_key_env`` …) is kept,
and a model keeps its other fields when only its tier changes.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import TypeAdapter
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from orkestra.config import loader, writer
from orkestra.config.schema import (
    CONFIG_VERSION,
    CliAgentProvider,
    Config,
    OllamaProvider,
    OpenAICompatProvider,
    Provider,
)
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
# Keys that say *which* provider an entry is; an existing entry keeps its own (only a missing
# one is filled in), so a custom address or command path survives a re-run.
IDENTITY_KEYS = ("type", "base_url", "command", "api_key_env", "local", "experimental")

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
    config: Config  # the saved, validated effective config
    backup: Path | None = None
    gitignore: Path | None = None
    providers: list[str] = field(default_factory=list)


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
    """Turn on what was found; ask nothing (and so grant no consent, Mimari §22)."""
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
    return Answers(providers=picks, chief=_detected_chief(found), notes=notes)


def _detected_chief(found: detect.Detection) -> str | None:
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
    current: Config | None = None,
) -> Answers:
    """Ask every step; a wrong answer is asked again with the reason.

    ``current``: the config being edited; its values are the defaults.
    """
    choices = ", ".join(LANGUAGE_CHOICES)
    default_language = current.language if current is not None else "auto"
    language = _choice(ask, t("wizard.ask.language", choices=choices), LANGUAGE_CHOICES,
                       default_language)  # fmt: skip
    if language != "auto":
        set_language(language)  # every following question is in the chosen language

    ask.say(t("wizard.detected"))
    for line in detect.summary_lines(found):
        ask.say(f"  {line}")

    existing = current.providers if current is not None else {}
    picks = [
        _pick(ask, name, found, existing.get(name))
        for name in _choose_providers(ask, found, existing)
    ]

    chief: str | None = None
    default_chief = current.defaults.chief if current is not None else _detected_chief(found)
    if default_chief is not None:
        chief = _choice(ask, t("wizard.ask.chief", choices=", ".join(CHIEFS)), CHIEFS,
                        default_chief if default_chief in CHIEFS else CHIEFS[0])  # fmt: skip
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


def _choose_providers(
    ask: Prompter, found: detect.Detection, existing: Mapping[str, Provider]
) -> list[str]:
    names = candidate_names()
    ask.say(t("wizard.providers.title"))
    for number, name in enumerate(names, start=1):
        mark = t("wizard.providers.found") if _detected(name, found) else ""
        ask.say(t("wizard.providers.item", number=number, name=name, mark=mark).rstrip())
    preselected = [
        str(number)
        for number, name in enumerate(names, start=1)
        if _detected(name, found) or (name in existing and existing[name].enabled)
    ]
    while True:
        raw = ask.ask(t("wizard.ask.providers"), ",".join(preselected) or None)
        numbers = _numbers(raw, len(names))
        if numbers:
            return [names[number - 1] for number in numbers]
        ask.say(t("wizard.error.providers"))


def _pick(
    ask: Prompter, name: str, found: detect.Detection, current: Provider | None
) -> ProviderPick:
    if name == "ollama":
        known = current if isinstance(current, OllamaProvider) else None
        url = known.base_url if known is not None else found.ollama.url
        return ProviderPick(name, ollama_settings(url, _ollama_models(ask, found, known)))
    if name in AGENT_DAILY_RUNS:
        agent = current if isinstance(current, CliAgentProvider) else None
        enabled = True
        if name == "agy":
            ask.say(t("wizard.agy.experimental"))
            enabled = ask.confirm(t("wizard.ask.agy_enable"),
                                  default=agent is not None and agent.enabled)  # fmt: skip
        runs = AGENT_DAILY_RUNS[name]
        if agent is not None and agent.budget.daily_runs is not None:
            runs = agent.budget.daily_runs
        if enabled:
            runs = int(_number(ask, t("wizard.ask.daily_runs", name=name), runs, integer=True))
        return ProviderPick(name, agent_settings(name, daily_runs=runs, enabled=enabled))
    api = next(api for api in detect.KNOWN_APIS if api.name == name)
    chat = current if isinstance(current, OpenAICompatProvider) else None
    first = chat.models[0] if chat is not None and chat.models else None
    model = _required(ask, t("wizard.ask.api_model", name=name), first.id if first else None)
    tier = _tier(ask, t("wizard.ask.tier", model=model), first.tier if first else API_TIER)
    usd = API_DAILY_USD
    if chat is not None and chat.budget.daily_usd is not None:
        usd = chat.budget.daily_usd
    usd = _number(ask, t("wizard.ask.daily_usd", name=name), usd, integer=False)
    return ProviderPick(name, api_settings(api, model, tier, usd))


def _ollama_models(
    ask: Prompter, found: detect.Detection, current: OllamaProvider | None
) -> list[tuple[str, int]]:
    tiers = {model.id: model.tier for model in current.models} if current is not None else {}
    available = [*tiers, *(model for model in found.ollama.models if model not in tiers)]
    if available:
        for number, model in enumerate(available, start=1):
            ask.say(t("wizard.ollama.model", number=number, name=model))
        preselected = [n for n, model in enumerate(available, start=1) if model in tiers]
        everything = ",".join(str(n) for n in preselected or range(1, len(available) + 1))
        while True:
            numbers = _numbers(ask.ask(t("wizard.ask.ollama_models"), everything), len(available))
            if numbers:
                break
            ask.say(t("wizard.error.numbers"))
        chosen = [available[number - 1] for number in numbers]
    else:
        chosen = [_required(ask, t("wizard.ask.ollama_model"), None)]
    return [
        (model, _tier(ask, t("wizard.ask.tier", model=model), tiers.get(model, LOCAL_TIER)))
        for model in chosen
    ]


def _numbers(raw: str, count: int) -> list[int]:
    """``"1, 3,3"`` → ``[1, 3]``; empty if anything is not a number from 1 to ``count``."""
    numbers: list[int] = []
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        # ASCII digits only: "²".isdigit() is True, but int("²") fails (code review #21).
        if not (part.isascii() and part.isdigit()) or not 1 <= int(part) <= count:
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


def _required(ask: Prompter, text: str, default: str | None) -> str:
    while True:
        raw = ask.ask(text, default).strip()
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


# --- consent (after saving) ---------------------------------------------------------------


def consent_names(answers: Answers) -> list[str]:
    """The picked providers that are on; one that stays off needs no consent yet."""
    return [pick.name for pick in answers.providers if pick.enabled]


def ask_consents(ask: Prompter, config: Config, names: Iterable[str]) -> list[str]:
    """Show each provider as it was saved and ask; returns the ones the user agreed to."""
    agreed: list[str] = []
    for name in names:
        provider = config.providers.get(name)
        if provider is None or not provider.enabled:
            continue
        for line in consent.describe(name, provider):
            ask.say(line)
        if ask.confirm(t("consent.confirm"), default=False):
            agreed.append(name)
    return agreed


def record_consents(config: Config, names: Iterable[str], now: datetime) -> list[str]:
    """Record consent for exactly the saved settings (the hash ``providers list`` checks)."""
    recorded: list[str] = []
    wanted = [name for name in names if name in config.providers]
    if not wanted:
        return recorded
    with closing(db.connect()) as conn:
        for name in wanted:
            registry.enable_provider(conn, name, config.providers[name], now)
            recorded.append(name)
    return recorded


# --- writing -----------------------------------------------------------------------------


def apply(document: CommentedMap, answers: Answers, *, fresh: bool) -> CommentedMap:
    """Put the answers into ``document`` without touching anything else in it.

    ``fresh`` (a new file from the example): providers that were not picked are removed and
    the example's budgets are replaced. In an existing file nothing the user wrote is deleted
    (see the module docstring).
    """
    if answers.language is not None:
        document["language"] = answers.language
    if answers.chief is not None:
        _mapping(document, "defaults")["chief"] = answers.chief
    providers = _mapping(document, "providers")
    picked = {pick.name for pick in answers.providers}
    offered = set(candidate_names())
    for name in list(providers):
        if name in picked or name not in offered:
            continue  # a provider the wizard never offered is not the wizard's to change
        if fresh:
            del providers[name]
        elif isinstance(providers[name], CommentedMap):
            providers[name]["enabled"] = False
    for pick in answers.providers:
        entry = providers.get(name := pick.name)
        if not isinstance(entry, CommentedMap):
            entry = providers[name] = CommentedMap()
        _apply_pick(entry, pick, fresh=fresh)
    return document


def _apply_pick(entry: CommentedMap, pick: ProviderPick, *, fresh: bool) -> None:
    for key, value in pick.settings.items():
        if key in IDENTITY_KEYS and not fresh and key in entry:
            continue  # the user's own address, command, key variable … stay
        if key == "models" and isinstance(entry.get("models"), list) and not fresh:
            entry["models"] = _merge_models(entry["models"], value)
        elif key == "budget" and fresh:
            entry["budget"] = _yaml_value(value)  # the example's limits are not choices
        elif isinstance(value, Mapping) and isinstance(entry.get(key), CommentedMap):
            _merge(entry[key], value)
        else:
            entry[key] = _yaml_value(value)
    if pick.enabled and "enabled" in entry:
        entry["enabled"] = True


def _merge_models(existing: list[Any], picked: list[dict[str, Any]]) -> CommentedSeq:
    """The picked models in their order; a model that was already there keeps every other
    field (``context_window``, prices, comments) and only takes the new tier."""
    by_id = {model.get("id"): model for model in existing if isinstance(model, CommentedMap)}
    merged = CommentedSeq()
    for model in picked:
        known = by_id.get(model["id"])
        if known is None:
            merged.append(_yaml_value(model))
            continue
        _merge(known, model)
        merged.append(known)
    return merged


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


def _global_builtins_to_turn_off(answers: Answers, base: Path) -> list[str]:
    """For a new project file: built-in providers of the global config the user did not pick
    are turned off in this project; custom ones are left to the global config."""
    if not base.is_file():
        return []
    global_providers = loader.read_yaml(base).get("providers")
    if not isinstance(global_providers, Mapping):
        return []
    picked = {pick.name for pick in answers.providers}
    offered = set(candidate_names())
    return [name for name in global_providers if name in offered and name not in picked]


def save_answers(
    answers: Answers,
    *,
    config_flag: Path | None,
    now: datetime,
    fresh: bool | None = None,
    cwd: Path | None = None,
) -> Outcome:
    """Write the answers (global or project file). Consent is a separate, later step.

    ``fresh=None``: start new when the file does not exist yet, otherwise edit the file in
    place. ``True`` (``--defaults --force``, ``--plain --force``) starts again from the
    example (a project file: from an empty one); the old file is kept as a backup.
    """
    workdir = Path.cwd() if cwd is None else cwd
    target = loader.init_target(config_flag, project=answers.project, cwd=workdir)
    base = loader.base_config_target(config_flag)[0] if answers.project else None
    from_scratch = not target.exists() if fresh is None else fresh
    if not from_scratch:
        document = apply(writer.load_document(target), answers, fresh=False)
    elif base is not None:
        # A new project file holds only the answers: the whole example would override every
        # global setting (code review #21).
        document = CommentedMap()
        document["version"] = CONFIG_VERSION
        document = apply(document, answers, fresh=True)
        providers = _mapping(document, "providers")
        for name in _global_builtins_to_turn_off(answers, base):
            off = CommentedMap()
            off["enabled"] = False
            providers[name] = off
    else:
        document = apply(writer.template_document(), answers, fresh=True)
    result = writer.save(target, document, base=base)
    gitignore: Path | None = None
    if answers.project:
        root = loader.find_git_root(workdir.resolve())
        if root is not None and loader.ensure_gitignore_entry(root / ".gitignore"):
            gitignore = root / ".gitignore"
    return Outcome(target, result.config, result.backup, gitignore,
                   [pick.name for pick in answers.providers])  # fmt: skip
