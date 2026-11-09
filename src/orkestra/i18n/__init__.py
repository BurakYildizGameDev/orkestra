"""Translation catalogs and language selection (Mimari §18).

Catalogs are flat ``key: value`` YAML files in ``locales/<lang>.yaml``; placeholders use
``{name}``. English is the source language and the fallback for every missing key.

Selection order: ``--lang`` > ``ORKESTRA_LANG`` > config ``language`` > system language > ``en``.
"""

from __future__ import annotations

import locale
import logging
import os
import sys
from collections.abc import Mapping
from functools import cache
from importlib import resources

from ruamel.yaml import YAML

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "tr", "de", "es", "fr")
LANG_ENV = "ORKESTRA_LANG"
STRICT_ENV = "ORKESTRA_I18N_STRICT"
"""When set to ``1`` a key missing from every catalog raises ``KeyError`` (used in tests)."""

_SYSTEM_LANG_VARS = ("LC_ALL", "LC_MESSAGES", "LANG")
# Windows reports locales by English name, e.g. "Turkish_Türkiye".
_LANGUAGE_NAMES = {
    "english": "en",
    "turkish": "tr",
    "german": "de",
    "spanish": "es",
    "french": "fr",
}

_logger = logging.getLogger(__name__)
_current = DEFAULT_LANGUAGE


def normalize_language(value: str | None) -> str | None:
    """Map ``tr``, ``tr_TR.UTF-8``, ``de-DE`` or ``Turkish_Türkiye`` to a supported code.

    Returns ``None`` for empty, ``auto``, ``C``/``POSIX`` and unsupported values.
    """
    if not value:
        return None
    code = value.strip().lower().replace("-", "_").split(".")[0].split("@")[0].split("_")[0]
    if code in SUPPORTED_LANGUAGES:
        return code
    return _LANGUAGE_NAMES.get(code)


def _platform_locale() -> str | None:
    if sys.platform == "win32":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            name = locale.windows_locale.get(lang_id)
            if name:
                return name
        except (AttributeError, OSError):
            pass
    try:
        return locale.getlocale()[0]
    except ValueError:
        return None


def system_language(environ: Mapping[str, str] | None = None) -> str | None:
    """Language from ``LC_ALL``/``LC_MESSAGES``/``LANG``, then the OS locale."""
    env = os.environ if environ is None else environ
    for var in _SYSTEM_LANG_VARS:
        lang = normalize_language(env.get(var))
        if lang:
            return lang
    return normalize_language(_platform_locale())


def resolve_language(
    *,
    cli: str | None = None,
    env: str | None = None,
    config: str | None = None,
    system: str | None = None,
) -> str:
    """Pick the first supported language in selection order, ``en`` if none."""
    for candidate in (cli, env, config, system):
        lang = normalize_language(candidate)
        if lang:
            return lang
    return DEFAULT_LANGUAGE


def init_language(*, cli: str | None = None, config: str | None = None) -> str:
    """Resolve the language from the real environment, activate it and return it."""
    lang = resolve_language(
        cli=cli,
        env=os.environ.get(LANG_ENV),
        config=config,
        system=system_language(),
    )
    set_language(lang)
    return lang


def set_language(lang: str) -> None:
    global _current
    code = normalize_language(lang)
    if code is None:
        raise ValueError(f"unsupported language: {lang!r}")
    _current = code


def get_language() -> str:
    return _current


@cache
def load_catalog(lang: str) -> dict[str, str]:
    """Load ``locales/<lang>.yaml``. A language without a catalog yields an empty dict."""
    path = resources.files(__name__).joinpath("locales").joinpath(f"{lang}.yaml")
    if not path.is_file():
        return {}
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"locale catalog {lang}.yaml must be a mapping")
    catalog: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(value, str):
            raise ValueError(f"locale catalog {lang}.yaml: value of {key!r} must be a string")
        catalog[str(key)] = value
    return catalog


class _KeepMissing(dict[str, object]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _lookup(key: str) -> str | None:
    for lang in (_current, DEFAULT_LANGUAGE):
        text = load_catalog(lang).get(key)
        if text:
            return text
    return None


def t(key: str, /, **params: object) -> str:
    """Translate ``key`` into the active language and fill ``{placeholders}``.

    Falls back to English; if English lacks the key too, returns the key itself
    (or raises ``KeyError`` when ``ORKESTRA_I18N_STRICT=1``).
    """
    text = _lookup(key)
    if text is None:
        if os.environ.get(STRICT_ENV) == "1":
            raise KeyError(f"missing translation key: {key}")
        _logger.warning("missing translation key: %s", key)
        return key
    return text.format_map(_KeepMissing(params))
