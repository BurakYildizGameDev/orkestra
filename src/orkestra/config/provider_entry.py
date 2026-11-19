"""Add or remove any OpenAI-compatible provider, by hand or from OpenCode's config (Faz 13o).

No service is built in: a provider is a name, an address, the *name* of the environment
variable that holds the key, and model ids (``type: openai_compat``). The key itself never
passes through here: OpenCode's ``options.apiKey`` is only looked at to tell an ``{env:X}``
reference (whose variable name is taken) from a plain key (which is dropped at once, and the
user is told which variable to set).

Writing goes through ``config.writer`` (comments kept, validated, backup, atomic), like the
setup wizard (Mimari §22).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from orkestra.config import writer
from orkestra.config.schema import CONFIG_VERSION
from orkestra.errors import ConfigError, UsageError
from orkestra.i18n import t

DEFAULT_TIER = 2  # a good API model (the wizard's API tier)
OPENCODE_ENV = "OPENCODE_CONFIG"
OPENCODE_NPM = "@ai-sdk/openai-compatible"  # the only OpenCode provider package Orkestra reads
_ENV_REF = re.compile(r"^\{env:([A-Za-z_][A-Za-z0-9_]*)\}$")
_NOT_WORD = re.compile(r"[^A-Za-z0-9]+")


@dataclass(frozen=True)
class ApiProvider:
    name: str
    base_url: str
    api_key_env: str | None  # None: a server without a key (e.g. a local one)
    models: tuple[str, ...]
    tier: int = DEFAULT_TIER
    context_window: int | None = None  # None: the schema's default


def suggest_key_env(name: str) -> str:
    """``evren`` → ``EVREN_API_KEY``: the variable a provider's key is expected in."""
    return f"{_NOT_WORD.sub('_', name).strip('_').upper()}_API_KEY"


def valid_base_url(url: str) -> bool:
    return url.startswith(("https://", "http://")) and len(url) > len("https://")


def settings(provider: ApiProvider) -> dict[str, Any]:
    """Plain data for ``providers.<name>``."""
    models: list[dict[str, Any]] = []
    for model in provider.models:
        spec: dict[str, Any] = {"id": model, "tier": provider.tier}
        if provider.context_window is not None:
            spec["context_window"] = provider.context_window
        models.append(spec)
    data: dict[str, Any] = {"type": "openai_compat", "base_url": provider.base_url}
    if provider.api_key_env is not None:
        data["api_key_env"] = provider.api_key_env  # the variable's name, never the key
    data["models"] = models
    return data


def _yaml(value: Any) -> Any:
    if isinstance(value, Mapping):
        mapping = CommentedMap()
        for key, item in value.items():
            mapping[key] = _yaml(item)
        return mapping
    if isinstance(value, list):
        return CommentedSeq([_yaml(item) for item in value])
    return value


def _providers(document: CommentedMap) -> CommentedMap:
    providers = document.get("providers")
    if not isinstance(providers, CommentedMap):
        providers = document["providers"] = CommentedMap()
    return providers


def add(
    path: Path, provider: ApiProvider, *, force: bool = False, base: Path | None = None
) -> writer.SaveResult:
    """Write ``provider`` into the config file at ``path`` (created when missing).

    ``base``: the base config a project file is validated with. An existing name is refused
    unless ``force`` (then the entry is replaced as a whole).
    """
    if not provider.models:
        raise UsageError(t("providers.error.no_model"))
    if not valid_base_url(provider.base_url):
        raise UsageError(t("providers.error.base_url", value=provider.base_url))
    document = writer.load_document(path)
    if not document:
        document["version"] = CONFIG_VERSION
    providers = _providers(document)
    if provider.name in providers and not force:
        raise UsageError(t("providers.error.exists", name=provider.name))
    providers[provider.name] = _yaml(settings(provider))
    return writer.save(path, document, base=base)


def remove(path: Path, name: str, *, base: Path | None = None) -> writer.SaveResult:
    document = writer.load_document(path)
    providers = document.get("providers")
    if not isinstance(providers, CommentedMap) or name not in providers:
        raise UsageError(t("providers.error.not_in_file", name=name, path=path))
    del providers[name]
    return writer.save(path, document, base=base)


# --- OpenCode ------------------------------------------------------------------------------


@dataclass(frozen=True)
class OpencodeProvider:
    name: str
    npm: str | None
    base_url: str | None
    models: tuple[str, ...]
    key_env: str | None  # from an ``{env:X}`` reference
    plain_key: bool  # the file holds the key itself (it is not kept here)

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


def read_opencode(path: Path) -> list[OpencodeProvider]:
    """The providers in OpenCode's config. A plain ``apiKey`` value is never kept."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise UsageError(t("providers.import.not_found", path=path)) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(t("config.error.read", path=path, reason=type(exc).__name__)) from None
    # ``.jsonc``: whole-line comments only; the error never quotes the file (it holds keys).
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("//")]
    try:
        data = json.loads("\n".join(lines))
    except json.JSONDecodeError as exc:
        raise ConfigError(t("providers.import.bad_json", path=path, line=exc.lineno)) from None
    section = data.get("provider") if isinstance(data, dict) else None
    if not isinstance(section, dict):
        return []
    return [_opencode_entry(str(name), raw) for name, raw in section.items()
            if isinstance(raw, dict)]  # fmt: skip


def _opencode_entry(name: str, raw: Mapping[str, Any]) -> OpencodeProvider:
    options = raw.get("options")
    options = options if isinstance(options, Mapping) else {}
    key = options.get("apiKey")
    match = _ENV_REF.match(key) if isinstance(key, str) else None
    models = raw.get("models")
    base_url = options.get("baseURL")
    npm = raw.get("npm")
    return OpencodeProvider(
        name=name,
        npm=npm if isinstance(npm, str) else None,
        base_url=base_url if isinstance(base_url, str) else None,
        models=tuple(str(model) for model in models) if isinstance(models, Mapping) else (),
        key_env=match.group(1) if match else None,
        plain_key=isinstance(key, str) and bool(key) and match is None,
    )


def from_opencode(
    found: OpencodeProvider,
    *,
    name: str | None = None,
    api_key_env: str | None = None,
    tier: int = DEFAULT_TIER,
    context_window: int | None = None,
) -> ApiProvider:
    """The Orkestra entry for an OpenCode provider; the key variable is the given one, the one
    OpenCode refers to, or the suggested one."""
    target = name or found.name
    variable = api_key_env or found.key_env or suggest_key_env(target)
    return ApiProvider(target, found.base_url or "", variable, found.models, tier, context_window)


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
