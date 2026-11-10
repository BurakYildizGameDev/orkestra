from __future__ import annotations

from pathlib import Path
from string import Formatter

import pytest

from orkestra import i18n
from orkestra.errors import TranslationError, UsageError
from orkestra.i18n import t

CATALOG_LANGUAGES = ("en", "tr")  # de, es, fr arrive in Faz 11


def _placeholders(text: str) -> set[str]:
    return {field for _, field, _, _ in Formatter().parse(text) if field is not None}


# --- selection order -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"cli": "tr", "env": "en", "config": "en", "system": "en"}, "tr"),
        ({"cli": None, "env": "tr", "config": "en", "system": "en"}, "tr"),
        ({"cli": None, "env": None, "config": "tr", "system": "en"}, "tr"),
        ({"cli": None, "env": None, "config": "auto", "system": "tr"}, "tr"),
        ({"cli": None, "env": None, "config": None, "system": "tr"}, "tr"),
        ({"cli": None, "env": None, "config": None, "system": None}, "en"),
        # unsupported values are skipped, not fatal
        ({"cli": "xx", "env": "tr"}, "tr"),
        ({"env": "ja_JP.UTF-8", "system": "tr_TR"}, "tr"),
        ({"system": "C"}, "en"),
    ],
)
def test_resolve_language_order(kwargs: dict[str, str | None], expected: str) -> None:
    assert i18n.resolve_language(**kwargs) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("tr", "tr"),
        ("TR", "tr"),
        ("tr_TR.UTF-8", "tr"),
        ("de-DE", "de"),
        ("fr_FR@euro", "fr"),
        ("Turkish_Türkiye", "tr"),
        ("English_United States", "en"),
        ("es", "es"),
        ("C", None),
        ("POSIX", None),
        ("auto", None),
        ("ja_JP", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_language(raw: str | None, expected: str | None) -> None:
    assert i18n.normalize_language(raw) == expected


def test_system_language_env_order() -> None:
    assert i18n.system_language({"LC_ALL": "tr_TR.UTF-8", "LANG": "en_US.UTF-8"}) == "tr"
    # POSIX: a set LC_ALL wins; "C" means English (scripts use it for stable output)
    assert i18n.system_language({"LC_ALL": "C", "LANG": "tr_TR.UTF-8"}) == "en"
    assert i18n.system_language({"LC_ALL": "C.UTF-8", "LANG": "tr_TR.UTF-8"}) == "en"
    assert i18n.system_language({"LC_ALL": "POSIX", "LANG": "tr_TR.UTF-8"}) == "en"
    # set but unsupported: no language from the system, LANG is not consulted
    assert i18n.system_language({"LC_ALL": "ja_JP.UTF-8", "LANG": "tr_TR.UTF-8"}) is None
    assert i18n.system_language({"LC_ALL": "", "LANG": "tr_TR.UTF-8"}) == "tr"
    assert i18n.system_language({"LANG": "de_DE.UTF-8"}) == "de"


def test_system_language_falls_back_to_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "_platform_locale", lambda: "Turkish_Türkiye")
    assert i18n.system_language({}) == "tr"
    monkeypatch.setattr(i18n, "_platform_locale", lambda: None)
    assert i18n.system_language({}) is None


def test_init_language_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(i18n.LANG_ENV, "tr")
    assert i18n.init_language() == "tr"
    assert i18n.get_language() == "tr"
    assert i18n.init_language(cli="en") == "en"


def test_init_language_cli_beats_env_and_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(i18n.LANG_ENV, "en")
    assert i18n.init_language(cli="tr", config="en") == "tr"


def test_init_language_env_beats_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(i18n.LANG_ENV, "tr")
    assert i18n.init_language(config="en") == "tr"


def test_init_language_system_used_last(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    assert i18n.init_language() == "tr"
    assert i18n.init_language(config="en") == "en"


def test_set_language_rejects_unsupported() -> None:
    with pytest.raises(UsageError):
        i18n.set_language("xx")


# --- t() -------------------------------------------------------------------------------


def test_t_translates_and_formats() -> None:
    assert t("cli.version", version="1.2.3") == "orkestra 1.2.3"
    i18n.set_language("tr")
    assert t("errors.prefix", message="x") == "Hata: x"


def test_t_keeps_unknown_placeholder() -> None:
    assert t("errors.prefix") == "Error: {message}"


def test_t_falls_back_to_english(monkeypatch: pytest.MonkeyPatch) -> None:
    catalogs = {"en": {"only.en": "Hello {name}"}, "tr": {}}
    monkeypatch.setattr(i18n, "load_catalog", lambda lang: catalogs.get(lang, {}))
    i18n.set_language("tr")
    assert t("only.en", name="Ada") == "Hello Ada"


def test_t_empty_translation_falls_back_to_english(monkeypatch: pytest.MonkeyPatch) -> None:
    catalogs = {"en": {"k": "English"}, "tr": {"k": ""}}
    monkeypatch.setattr(i18n, "load_catalog", lambda lang: catalogs.get(lang, {}))
    i18n.set_language("tr")
    assert t("k") == "English"


def test_t_language_without_catalog_uses_english() -> None:
    i18n.set_language("de")
    assert t("errors.prefix", message="x") == "Error: x"


def test_t_missing_key_strict_raises() -> None:
    with pytest.raises(TranslationError):
        t("no.such.key")


def test_t_missing_key_returns_key_when_not_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(i18n.STRICT_ENV)
    assert t("no.such.key") == "no.such.key"


# --- catalogs --------------------------------------------------------------------------


def test_catalog_key_sets_match() -> None:
    en_keys = set(i18n.load_catalog("en"))
    assert en_keys
    for lang in CATALOG_LANGUAGES:
        keys = set(i18n.load_catalog(lang))
        assert keys == en_keys, f"{lang}: missing {en_keys - keys}, extra {keys - en_keys}"


def test_catalog_placeholders_match() -> None:
    en = i18n.load_catalog("en")
    for lang in CATALOG_LANGUAGES:
        catalog = i18n.load_catalog(lang)
        for key, text in en.items():
            assert _placeholders(catalog[key]) == _placeholders(text), f"{lang}:{key}"


def test_catalog_values_not_empty() -> None:
    for lang in CATALOG_LANGUAGES:
        for key, text in i18n.load_catalog(lang).items():
            assert text.strip(), f"{lang}:{key} is empty"


@pytest.mark.parametrize("bad", ["{0} files", "{", "use {name.attr}", "}"])
def test_unformattable_translation_does_not_crash(
    bad: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(i18n, "load_catalog", lambda lang: {"k": bad})
    monkeypatch.delenv(i18n.STRICT_ENV)
    assert t("k", name="x") == bad  # returned unformatted
    monkeypatch.setenv(i18n.STRICT_ENV, "1")
    with pytest.raises(TranslationError):
        t("k", name="x")


def test_escaped_braces_are_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "load_catalog", lambda lang: {"k": 'use {{"tier": {n}}}'})
    assert t("k", n=1) == 'use {"tier": 1}'


def test_every_catalog_entry_formats() -> None:
    """Placeholders are plain names and every text formats with them (no stray braces)."""
    for lang in CATALOG_LANGUAGES:
        for key, text in i18n.load_catalog(lang).items():
            fields = _placeholders(text)
            assert all(f.isidentifier() for f in fields), f"{lang}:{key}: {fields}"
            text.format(**{f: "x" for f in fields})


def test_bad_catalog_is_translation_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from importlib import resources

    folder = tmp_path / "locales"
    folder.mkdir()
    (folder / "en.yaml").write_bytes(b"k: [1, 2]\n")  # a list where a string belongs
    real_files = resources.files

    def files(name: str) -> object:
        return tmp_path if name == i18n.__name__ else real_files(name)

    monkeypatch.setattr(i18n.resources, "files", files)
    i18n.load_catalog.cache_clear()
    try:
        with pytest.raises(TranslationError):
            i18n.load_catalog("en")
    finally:
        i18n.load_catalog.cache_clear()
