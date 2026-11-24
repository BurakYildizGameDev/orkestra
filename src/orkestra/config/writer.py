"""Write a config file without losing the user's comments (Mimari §22, Faz 11a).

``ruamel.yaml`` round trip keeps comments, key order and quoting. Before anything touches the
disk the new text is validated (a project file together with the base config it overrides);
an invalid config is never saved. A cross-process lock serializes writes, and a source digest
rejects stale documents instead of silently replacing a newer config. The previous file is kept
as ``<name>.bak`` (``.bak.1``,
``.bak.2`` … when one exists: an earlier backup, e.g. from ``init --force``, is never replaced)
and the new one replaces it atomically, with the file's own line endings. Atomic writing,
the backup name and the same-file check are ``loader``'s, so both writers follow one rule.

The setup wizard (``--plain`` now, the terminal interface in Faz 11b) writes only through here.
"""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from orkestra.config import loader
from orkestra.config.file_lock import process_lock
from orkestra.config.schema import Config
from orkestra.errors import ConfigError
from orkestra.i18n import t

_SOURCE_DIGEST = "_orkestra_source_digest"


@dataclass(frozen=True)
class SaveResult:
    path: Path
    backup: Path | None
    config: Config  # the validated effective config (with the base config for a project file)


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096  # never re-wrap a long line
    yaml.indent(mapping=2, sequence=4, offset=2)  # the example config's style
    yaml.representer.add_representer(type(None), _represent_null)
    return yaml


def _represent_null(representer: Any, data: None) -> Any:
    """``model: null`` stays ``null``; ruamel would write an empty value."""
    return representer.represent_scalar("tag:yaml.org,2002:null", "null")


def to_yaml(value: Any) -> Any:
    """Plain data (dicts, lists, scalars) as ruamel nodes for a round-trip document."""
    if isinstance(value, Mapping):
        mapping = CommentedMap()
        for key, item in value.items():
            mapping[key] = to_yaml(item)
        return mapping
    if isinstance(value, list):
        return CommentedSeq([to_yaml(item) for item in value])
    return value


def backup_path(path: Path) -> Path:
    """Where the next backup of ``path`` goes (never over an earlier one)."""
    return loader.free_backup_path(path)


def _parse(path: Path, text: str) -> CommentedMap:
    try:
        data = _yaml().load(text)
    except YAMLError as exc:
        raise ConfigError(t("config.error.yaml", path=path, problem=exc)) from exc
    if data is None:
        return CommentedMap()
    if not isinstance(data, CommentedMap):
        raise ConfigError(t("config.error.not_mapping", path=path))
    return data


def template_document() -> CommentedMap:
    """The example config (with all its comments) as an editable document."""
    return _parse(Path("example.yaml"), loader.example_config_text())


def load_document(path: Path) -> CommentedMap:
    """The file as an editable document; a missing or empty file is an empty one."""
    if not path.exists():
        document = CommentedMap()
        setattr(document, _SOURCE_DIGEST, None)
        return document
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(t("config.error.read", path=path, reason=exc)) from exc
    document = _parse(path, text)
    setattr(document, _SOURCE_DIGEST, hashlib.sha256(raw).digest())
    return document


def render(document: CommentedMap) -> str:
    stream = StringIO()
    _yaml().dump(document, stream)
    return stream.getvalue()


def validate(path: Path, text: str, *, base: Path | None = None) -> Config:
    """The config ``text`` would give, merged over ``base`` (for a project file)."""
    data: dict[str, Any] = loader.read_yaml_text(path, text)
    sources = [path]
    if base is not None and base.is_file() and not loader.same_file(base, path):
        data = loader.merge_dicts(loader.read_yaml(base), data)
        sources.insert(0, base)
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        names = ", ".join(str(source) for source in sources)
        raise ConfigError(
            t("config.error.invalid", sources=names),
            details=loader.format_validation_error(exc),
        ) from exc


def save(path: Path, document: CommentedMap, *, base: Path | None = None) -> SaveResult:
    """Validate, back up, then replace atomically without clobbering a concurrent edit."""
    lock_paths = {path.expanduser().resolve()}
    if base is not None:
        lock_paths.add(base.expanduser().resolve())
    try:
        with contextlib.ExitStack() as stack:
            for lock_target in sorted(lock_paths, key=str):
                stack.enter_context(process_lock(lock_target))
            has_expected = hasattr(document, _SOURCE_DIGEST)
            expected = getattr(document, _SOURCE_DIGEST, None)
            old = path.read_bytes() if path.exists() else None
            current_digest = hashlib.sha256(old).digest() if old is not None else None
            if has_expected and current_digest != expected:
                raise ConfigError(t("config.error.concurrent_update", path=path))

            text = render(document)
            config = validate(path, text, base=base)
            if old is not None and b"\r\n" in old:
                text = text.replace("\n", "\r\n")
            new = text.encode("utf-8")
            if old is not None and old == new:
                setattr(document, _SOURCE_DIGEST, current_digest)
                return SaveResult(path, None, config)  # no write, no backup (B-14)
            backup: Path | None = None
            path.parent.mkdir(parents=True, exist_ok=True)
            if old is not None:
                backup = backup_path(path)
                loader.atomic_write(backup, old)
            loader.atomic_write(path, new)
            setattr(document, _SOURCE_DIGEST, hashlib.sha256(new).digest())
    except OSError as exc:
        raise ConfigError(t("config.error.write", path=path, reason=exc)) from exc
    return SaveResult(path, backup, config)
