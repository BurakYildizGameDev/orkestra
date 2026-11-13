"""Change one config value in the right file (Faz 11b, Mimari §22).

The terminal interface changes one thing at a time (turn a provider off, set a budget, pick
a profile). The value goes into the file that already defines it: the project's
``orkestra.yaml`` when it does, otherwise the base config. Everything else in that file stays
as it was, comments included, because the write goes through ``config.writer`` (validated
before writing, backup, atomic). An invalid value is never saved: ``ConfigError`` says why,
in the current language.
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


def _defines(data: Mapping[str, Any], key_path: KeyPath) -> bool:
    """Whether ``data`` has the key path, or its provider entry (``providers.<name>``)."""
    depth = 2 if len(key_path) >= 2 and key_path[0] == "providers" else len(key_path)
    current: Any = data
    for key in key_path[:depth]:
        if not isinstance(current, Mapping) or key not in current:
            return False
        current = current[key]
    return True


def target_for(
    key_path: KeyPath, *, config_flag: Path | None, cwd: Path | None = None
) -> tuple[Path, Path | None]:
    """The file to change and, for a project file, the base config it is validated with."""
    sources = loader.find_sources(config_flag, cwd)
    base = loader.base_config_target(config_flag)[0]
    if not sources:
        raise ConfigError(t("ui.error.no_config", path=base))
    for source in reversed(sources):
        if source.kind == "project" and _defines(loader.read_yaml(source.path), key_path):
            return source.path, base
    return sources[0].path, None


def set_value(
    key_path: KeyPath, value: Any, *, config_flag: Path | None, cwd: Path | None = None
) -> writer.SaveResult:
    """Set (``None``: remove) one value; nothing else in the file changes."""
    path, base = target_for(key_path, config_flag=config_flag, cwd=cwd)
    document = writer.load_document(path)
    parent = document
    for key in key_path[:-1]:
        child = parent.get(key)
        if not isinstance(child, CommentedMap):
            child = parent[key] = CommentedMap()
        parent = child
    leaf = key_path[-1]
    if value is None:
        parent.pop(leaf, None)
    else:
        parent[leaf] = value
    return writer.save(path, document, base=base)
