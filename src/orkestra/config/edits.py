"""Change config values in the right file (Faz 11b, Mimari §22).

The terminal interface changes one thing at a time (turn a provider off, set a budget, pick
a profile). A value goes into the file that already defines that exact key; a new key goes into
the project's ``orkestra.yaml`` when that file has the provider's entry (it overrides the base
config there), otherwise into the base config. Removing a value (``None``) removes it from every
file that defines it, and writes nothing when no file does. Everything else in a file stays as
it was, comments included: the write goes through ``config.writer`` (validated before writing,
backup, atomic). An invalid value is never saved: ``ConfigError`` says why, in the current
language.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap

from orkestra.config import loader, writer
from orkestra.errors import ConfigError
from orkestra.i18n import t

KeyPath = Sequence[str]


def _has(data: Mapping[str, Any], key_path: KeyPath) -> bool:
    current: Any = data
    for key in key_path:
        if not isinstance(current, Mapping) or key not in current:
            return False
        current = current[key]
    return True


def _entry(key_path: KeyPath) -> KeyPath:
    """``providers.<name>`` for a provider key; the key itself otherwise."""
    return key_path[:2] if len(key_path) >= 2 and key_path[0] == "providers" else key_path


def _sources(config_flag: Path | None, cwd: Path | None) -> tuple[list[loader.ConfigSource], Path]:
    sources = list(loader.find_sources(config_flag, cwd))
    base = loader.base_config_target(config_flag)[0]
    if not sources:
        raise ConfigError(t("ui.error.no_config", path=base))
    return sources, base


def _validation_base(source: loader.ConfigSource, base: Path) -> Path | None:
    return base if source.kind == "project" else None


def target_for(
    key_path: KeyPath, *, config_flag: Path | None, cwd: Path | None = None
) -> tuple[Path, Path | None]:
    """The file to write ``key_path`` into, and the base config a project file is validated
    with."""
    sources, base = _sources(config_flag, cwd)
    data = {source.path: loader.read_yaml(source.path) for source in sources}
    for wanted in (key_path, _entry(key_path)):
        for source in reversed(sources):
            if _has(data[source.path], wanted):
                return source.path, _validation_base(source, base)
    return sources[0].path, _validation_base(sources[0], base)


def set_values(
    changes: Sequence[tuple[KeyPath, Any]],
    *,
    config_flag: Path | None,
    cwd: Path | None = None,
) -> list[writer.SaveResult]:
    """Set several values; the ones for the same file are one save (one backup)."""
    groups: dict[Path, tuple[Path | None, list[tuple[KeyPath, Any]]]] = {}
    for key_path, value in changes:
        path, base = target_for(key_path, config_flag=config_flag, cwd=cwd)
        groups.setdefault(path, (base, []))[1].append((key_path, value))
    results: list[writer.SaveResult] = []
    for path, (base, values) in groups.items():
        document = writer.load_document(path)
        for key_path, value in values:
            parent = document
            for key in key_path[:-1]:
                child = parent.get(key)
                if not isinstance(child, CommentedMap):
                    child = parent[key] = CommentedMap()
                parent = child
            parent[key_path[-1]] = value
        results.append(writer.save(path, document, base=base))
    return results


def set_value(
    key_path: KeyPath, value: Any, *, config_flag: Path | None, cwd: Path | None = None
) -> writer.SaveResult:
    """Set one value, or remove it with ``None``; nothing else in the file changes."""
    if value is None:
        return _remove(key_path, config_flag=config_flag, cwd=cwd)
    return set_values([(key_path, value)], config_flag=config_flag, cwd=cwd)[0]


def _remove(key_path: KeyPath, *, config_flag: Path | None, cwd: Path | None) -> writer.SaveResult:
    """Remove the key from every file that has it; without one, nothing is written."""
    sources, base = _sources(config_flag, cwd)
    last: writer.SaveResult | None = None
    for source in sources:
        if not _has(loader.read_yaml(source.path), key_path):
            continue
        document = writer.load_document(source.path)
        parent: Any = document
        for key in key_path[:-1]:
            parent = parent[key]
        del parent[key_path[-1]]
        last = writer.save(source.path, document, base=_validation_base(source, base))
    effective = loader.load_config(config_flag, cwd).config
    if last is None:
        return writer.SaveResult(sources[-1].path, None, effective)
    return writer.SaveResult(last.path, last.backup, effective)
