"""Add or remove any OpenAI-compatible provider, by hand or from OpenCode's config (Faz 13o).

No service is built in: a provider is a name, an address, the *name* of the environment
variable that holds the key, and model ids (``type: openai_compat``). The key itself never
passes through here: OpenCode's ``options.apiKey`` is only looked at to tell an ``{env:X}``
reference (whose variable name is taken) or a ``{file:…}`` reference from a plain key (which
is dropped at once, and the user is told which variable to set). A value given as the key
*variable* must look like a variable name, so a pasted key is refused and never echoed (D-101).

Writing goes through ``config.writer`` (comments kept, validated, backup, atomic), like the
setup wizard (Mimari §22).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError
from ruamel.yaml.comments import CommentedMap

from orkestra.config import loader, writer
from orkestra.config.schema import CONFIG_VERSION, PROVIDER_NAME, Config
from orkestra.errors import ConfigError, UsageError
from orkestra.i18n import t
from orkestra.state import consent

DEFAULT_TIER = 2  # a good API model (the wizard's API tier)
OPENCODE_ENV = "OPENCODE_CONFIG"
OPENCODE_NPM = "@ai-sdk/openai-compatible"  # the only OpenCode provider package Orkestra reads
VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # as notify's (D-075)
_ENV_REF = re.compile(r"^\{env:([A-Za-z_][A-Za-z0-9_]*)\}$")
_FILE_REF = re.compile(r"^\{file:[^}]+\}$")
_NOT_WORD = re.compile(r"[^A-Za-z0-9]+")
_NOT_NAME = re.compile(r"[^a-z0-9_-]+")

KeyNote = Literal["plain", "file"]


@dataclass(frozen=True)
class ApiProvider:
    name: str
    base_url: str
    api_key_env: str | None  # None: a server without a key (e.g. a local one)
    models: tuple[str, ...]
    tier: int = DEFAULT_TIER
    context_window: int | None = None  # every model; None: per model, else the schema default
    model_windows: tuple[tuple[str, int], ...] = ()  # per model (from OpenCode's limit.context)


def suggest_key_env(name: str) -> str:
    """``evren`` → ``EVREN_API_KEY``: the variable a provider's key is expected in."""
    return f"{_NOT_WORD.sub('_', name).strip('_').upper()}_API_KEY"


def suggest_name(name: str) -> str:
    """``My.Lab`` → ``my-lab``: a valid provider name close to ``name``."""
    return _NOT_NAME.sub("-", name.lower()).strip("-") or "provider"


def valid_base_url(url: str) -> bool:
    return url.startswith(("https://", "http://")) and len(url) > len("https://")


def valid_key_env(value: str) -> bool:
    return bool(VARIABLE_NAME.match(value))


def from_flags(
    name: str,
    base_url: str,
    models: Sequence[str],
    *,
    api_key_env: str | None,
    no_key: bool,
    tier: int = DEFAULT_TIER,
    context_window: int | None = None,
) -> ApiProvider:
    """``providers add``'s options as a provider: the key variable is the given one, none
    (``no_key``) or the suggested one."""
    if no_key and api_key_env is not None:
        raise UsageError(t("providers.error.no_key_and_env"))
    variable = None if no_key else (api_key_env or suggest_key_env(name))
    return ApiProvider(name, base_url, variable, tuple(models), tier, context_window)


def settings(provider: ApiProvider) -> dict[str, Any]:
    """Plain data for ``providers.<name>``."""
    windows = dict(provider.model_windows)
    models: list[dict[str, Any]] = []
    for model in provider.models:
        spec: dict[str, Any] = {"id": model, "tier": provider.tier}
        window = provider.context_window or windows.get(model)
        if window is not None:
            spec["context_window"] = window
        models.append(spec)
    data: dict[str, Any] = {"type": "openai_compat", "base_url": provider.base_url}
    if provider.api_key_env is not None:
        data["api_key_env"] = provider.api_key_env  # the variable's name, never the key
    data["models"] = models
    return data


def _providers(document: CommentedMap) -> CommentedMap:
    providers = document.get("providers")
    if not isinstance(providers, CommentedMap):
        providers = document["providers"] = CommentedMap()
    return providers


def _check(provider: ApiProvider) -> None:
    if not provider.models:
        raise UsageError(t("providers.error.no_model"))
    if not valid_base_url(provider.base_url):
        raise UsageError(t("providers.error.base_url", value=provider.base_url))
    if provider.api_key_env is not None and not valid_key_env(provider.api_key_env):
        raise UsageError(t("providers.error.key_env"))  # the value may be the key: not echoed


def add(
    path: Path, provider: ApiProvider, *, force: bool = False, base: Path | None = None
) -> writer.SaveResult:
    """Write ``provider`` into the config file at ``path`` (created when missing).

    ``base``: the base config a project file is validated with. An existing name is refused
    unless ``force`` (then the entry is replaced as a whole). A name the base config already
    has is always refused in a project file: it would be merged into that entry, not replace it.
    """
    _check(provider)
    if base is not None and not loader.same_file(base, path) and base.is_file():
        in_base = loader.read_yaml(base).get("providers")
        if isinstance(in_base, Mapping) and provider.name in in_base:
            raise UsageError(t("providers.error.exists_in_base", name=provider.name, path=base))
    document = writer.load_document(path)
    if not document:
        document["version"] = CONFIG_VERSION
    providers = _providers(document)
    if provider.name in providers and not force:
        raise UsageError(t("providers.error.exists", name=provider.name))
    providers[provider.name] = writer.to_yaml(settings(provider))
    return writer.save(path, document, base=base)


@dataclass(frozen=True)
class RemoveOutcome:
    saved: writer.SaveResult
    still_defined: bool  # another config file (global or project) still defines it
    consent_revoked: bool


def remove(
    path: Path,
    name: str,
    *,
    base: Path | None = None,
    sources: Sequence[Path] = (),
    conn: sqlite3.Connection | None = None,
) -> RemoveOutcome:
    """Delete ``name`` from the file at ``path``.

    ``sources``: every config file in effect, base first (``path`` among them). The effective
    config after the removal must stay valid (a project override such as ``enabled: false``
    left without its entry is refused, nothing is written). Consent is withdrawn (with
    ``conn``) only when no file defines the provider any more.
    """
    document = writer.load_document(path)
    providers = document.get("providers")
    if not isinstance(providers, CommentedMap) or name not in providers:
        raise UsageError(t("providers.error.not_in_file", name=name, path=path))
    del providers[name]
    effective = _effective_after(path, writer.render(document), sources or (path,))
    saved = writer.save(path, document, base=base)
    still = name in effective.providers
    revoked = False if still or conn is None else consent.revoke(conn, name)
    return RemoveOutcome(saved, still, revoked)


def _effective_after(path: Path, text: str, sources: Sequence[Path]) -> Config:
    files = list(sources)
    if not any(loader.same_file(source, path) for source in files):
        files.append(path)
    merged: dict[str, Any] = {}
    for source in files:
        if loader.same_file(source, path):
            merged = loader.merge_dicts(merged, loader.read_yaml_text(path, text))
        elif source.is_file():
            merged = loader.merge_dicts(merged, loader.read_yaml(source))
    try:
        return Config.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(
            t("config.error.invalid", sources=", ".join(str(source) for source in files)),
            details=loader.format_validation_error(exc),
        ) from exc


# --- OpenCode ------------------------------------------------------------------------------


@dataclass(frozen=True)
class OpencodeProvider:
    name: str
    npm: str | None
    base_url: str | None  # an ``{env:X}`` address is resolved; None when it cannot be
    models: tuple[str, ...]
    key_env: str | None  # from an ``{env:X}`` reference
    plain_key: bool  # the file holds the key itself (it is not kept here)
    key_file: bool = False  # ``{file:…}``: OpenCode reads the key from a file
    windows: tuple[tuple[str, int], ...] = ()  # ``models.<id>.limit.context``

    @property
    def supported(self) -> bool:
        return self.npm == OPENCODE_NPM and bool(self.base_url) and bool(self.models)


def opencode_path(environ: Mapping[str, str], *, home: Path) -> Path:
    """OpenCode's global config: ``$OPENCODE_CONFIG``, else ``opencode.json`` (or ``.jsonc``)
    in ``$XDG_CONFIG_HOME/opencode`` or ``~/.config/opencode``."""
    custom = environ.get(OPENCODE_ENV, "").strip()
    if custom:
        return Path(custom).expanduser()
    xdg = environ.get("XDG_CONFIG_HOME", "").strip()
    folder = (Path(xdg) if xdg else home / ".config") / "opencode"
    json_file = folder / "opencode.json"
    jsonc = folder / "opencode.jsonc"
    return jsonc if not json_file.exists() and jsonc.exists() else json_file


def read_opencode(path: Path, environ: Mapping[str, str] | None = None) -> list[OpencodeProvider]:
    """The providers in OpenCode's config. A plain ``apiKey`` value is never kept."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise UsageError(t("providers.import.not_found", path=path)) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(t("config.error.read", path=path, reason=type(exc).__name__)) from None
    # ``.jsonc``: whole-line comments are blanked (line numbers stay right); the error never
    # quotes the file, which holds keys.
    lines = ["" if line.lstrip().startswith("//") else line for line in text.splitlines()]
    try:
        data = json.loads("\n".join(lines))
    except json.JSONDecodeError as exc:
        raise ConfigError(t("providers.import.bad_json", path=path, line=exc.lineno)) from None
    section = data.get("provider") if isinstance(data, dict) else None
    if not isinstance(section, dict):
        return []
    env = {} if environ is None else environ
    return [_opencode_entry(str(name), raw, env) for name, raw in section.items()
            if isinstance(raw, dict)]  # fmt: skip


def _opencode_entry(
    name: str, raw: Mapping[str, Any], environ: Mapping[str, str]
) -> OpencodeProvider:
    options = raw.get("options")
    options = options if isinstance(options, Mapping) else {}
    key = options.get("apiKey")
    key = key if isinstance(key, str) else ""
    key_ref = _ENV_REF.match(key)
    key_file = bool(_FILE_REF.match(key))
    base_url = options.get("baseURL")
    base_url = base_url if isinstance(base_url, str) else None
    if base_url is not None and (base_ref := _ENV_REF.match(base_url)):
        base_url = environ.get(base_ref.group(1)) or None  # an address is not a secret
    models = raw.get("models")
    models = models if isinstance(models, Mapping) else {}
    npm = raw.get("npm")
    return OpencodeProvider(
        name=name,
        npm=npm if isinstance(npm, str) else None,
        base_url=base_url,
        models=tuple(str(model) for model in models),
        key_env=key_ref.group(1) if key_ref else None,
        plain_key=bool(key) and key_ref is None and not key_file,
        key_file=key_file,
        windows=tuple((str(m), w) for m, spec in models.items() if (w := _context(spec))),
    )


def _context(spec: Any) -> int | None:
    limit = spec.get("limit") if isinstance(spec, Mapping) else None
    value = limit.get("context") if isinstance(limit, Mapping) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


@dataclass(frozen=True)
class ImportPlan:
    provider: ApiProvider
    key_note: KeyNote | None  # the key could not be taken over: say where to put it


def plan_import(
    found: OpencodeProvider,
    *,
    name: str | None = None,
    api_key_env: str | None = None,
    tier: int = DEFAULT_TIER,
    context_window: int | None = None,
) -> ImportPlan:
    """The Orkestra entry for an OpenCode provider (``name``: under another name). The key
    variable is the given one, the one OpenCode refers to, or the suggested one."""
    target = name or found.name
    if not PROVIDER_NAME.match(target):
        raise UsageError(
            t("providers.import.bad_name", name=target, suggestion=suggest_name(target))
        )
    variable = api_key_env or found.key_env or suggest_key_env(target)
    provider = ApiProvider(target, found.base_url or "", variable, found.models, tier,
                           context_window, found.windows)  # fmt: skip
    note: KeyNote | None = None
    if api_key_env is None and found.key_env is None:
        note = "plain" if found.plain_key else "file" if found.key_file else None
    return ImportPlan(provider, note)


def pick_opencode(found: Sequence[OpencodeProvider], name: str | None) -> OpencodeProvider | None:
    """The provider to import: the named one, or the only supported one (``None``: choose)."""
    if name is not None:
        chosen = next((entry for entry in found if entry.name == name), None)
        if chosen is None:
            names = ", ".join(entry.name for entry in found) or "-"
            raise UsageError(t("providers.import.unknown", name=name, available=names))
        if not chosen.supported:
            raise UsageError(t("providers.import.unsupported", name=name, npm=chosen.npm or "-"))
        return chosen
    supported = [entry for entry in found if entry.supported]
    if not supported:
        raise UsageError(t("providers.import.none"))
    return supported[0] if len(supported) == 1 else None
