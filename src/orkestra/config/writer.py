"""Write a config file without losing the user's comments (Mimari §22, Faz 11a).

``ruamel.yaml`` round trip keeps comments, key order and quoting. Before anything touches the
disk the new text is validated (a project file together with the base config it overrides);
an invalid config is never saved. The previous file is kept as ``<name>.bak`` (``.bak.1``,
``.bak.2`` … when one exists: an earlier backup, e.g. from ``init --force``, is never replaced)
and the new one replaces it atomically, with the file's own line endings. Atomic writing,
the backup name and the same-file check are ``loader``'s, so both writers follow one rule.

The setup wizard (``--plain`` now, the terminal interface in Faz 11b) writes only through here.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

from orkestra.config import loader
from orkestra.config.schema import Config
from orkestra.errors import ConfigError
from orkestra.i18n import t


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
        return CommentedMap()
    try:
        text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(t("config.error.read", path=path, reason=exc)) from exc
    return _parse(path, text)


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
    """Validate, back up the old file, then replace it atomically. Nothing is written if invalid."""
    text = render(document)
    config = validate(path, text, base=base)
    old = path.read_bytes() if path.exists() else None
    if old is not None and b"\r\n" in old:
        text = text.replace("\n", "\r\n")
    backup: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if old is not None:
            backup = backup_path(path)
            loader.atomic_write(backup, old)
        loader.atomic_write(path, text.encode("utf-8"))
    except OSError as exc:
        raise ConfigError(t("config.error.write", path=path, reason=exc)) from exc
    return SaveResult(path, backup, config)
