"""Find, load, merge and validate configuration files; create the example config.

Search order for the base file: ``--config`` > ``$ORKESTRA_CONFIG`` > ``~/.orkestra/config.yaml``.
The nearest ``orkestra.yaml`` from the working directory up to the git root is merged on top.
Mappings merge deeply, lists are replaced, ``providers.<name>: null`` removes a provider.
"""

from __future__ import annotations

import copy
import os
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from io import StringIO
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError
from pydantic_core import ErrorDetails
from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError, YAMLError

from orkestra import paths
from orkestra.config.schema import CONFIG_VERSION, PROVIDER_TYPES, Config
from orkestra.errors import ConfigError
from orkestra.i18n import t

CONFIG_ENV = "ORKESTRA_CONFIG"
PROJECT_CONFIG_NAME = "orkestra.yaml"
GITIGNORE_ENTRY = ".orkestra/cache/"

SourceKind = Literal["flag", "env", "global", "project"]


@dataclass(frozen=True)
class ConfigSource:
    path: Path
    kind: SourceKind


@dataclass(frozen=True)
class LoadedConfig:
    config: Config
    sources: tuple[ConfigSource, ...]


# --- merging ---------------------------------------------------------------------------


def merge_dicts(
    base: Mapping[str, Any], override: Mapping[str, Any], _path: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Merge ``override`` onto ``base`` without mutating either."""
    result = copy.deepcopy(dict(base))
    for key, value in override.items():
        here = (*_path, key)
        current = result.get(key)
        if value is None and len(here) == 2 and here[0] == "providers":
            result.pop(key, None)
        elif isinstance(value, Mapping) and (current is None or isinstance(current, Mapping)):
            # Merge into an empty mapping too, so "providers.<name>: null" also works when no
            # earlier file has a providers section (D-036).
            result[key] = merge_dicts(current or {}, value, here)
        else:
            result[key] = copy.deepcopy(value)
    return result


# --- reading ---------------------------------------------------------------------------


_YAML_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def read_yaml(path: Path) -> dict[str, Any]:
    """Safe-load a YAML mapping. An empty file is an empty mapping.

    Parsing is cached by path and content: the language pre-scan and the real load read the
    same files in one invocation, and a changed file is always parsed again.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(t("config.error.read", path=path, reason=exc)) from exc
    key = (str(path), text)
    if key in _YAML_CACHE:
        return copy.deepcopy(_YAML_CACHE[key])
    data = _parse_yaml(path, text)
    _YAML_CACHE[key] = copy.deepcopy(data)
    return data


def read_yaml_text(path: Path, text: str) -> dict[str, Any]:
    """Like ``read_yaml`` for text that is not on disk yet (the config writer validates it)."""
    return _parse_yaml(path, text)


def _parse_yaml(path: Path, text: str) -> dict[str, Any]:
    try:
        data = YAML(typ="safe").load(text)
    except MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        problem = exc.problem or exc.context or str(exc)
        if mark is None:
            raise ConfigError(t("config.error.yaml", path=path, problem=problem)) from exc
        message = t("config.error.yaml_line", path=path, line=mark.line + 1, problem=problem)
        started = exc.context_mark
        if started is not None and started.line != mark.line:
            # e.g. an unclosed "[" is only noticed at the end of the file; show where it began
            message += " " + t("config.error.yaml_started", line=started.line + 1)
        raise ConfigError(message) from exc
    except YAMLError as exc:
        raise ConfigError(t("config.error.yaml", path=path, problem=exc)) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(t("config.error.not_mapping", path=path))
    return data


# --- finding ---------------------------------------------------------------------------


def find_git_root(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        if (directory / ".git").exists():
            return directory
    return None


def find_project_config(cwd: Path) -> Path | None:
    """Nearest ``orkestra.yaml`` from ``cwd`` up to the git root; only ``cwd`` outside git."""
    cwd = cwd.resolve()
    root = find_git_root(cwd)
    for directory in (cwd, *cwd.parents):
        path = directory / PROJECT_CONFIG_NAME
        if path.is_file():
            return path
        if root is None or directory == root:
            break
    return None


def base_config_target(
    config_flag: Path | None = None, environ: Mapping[str, str] | None = None
) -> tuple[Path, SourceKind]:
    """Where the base config is (or would be): flag, environment variable or global path."""
    env = os.environ if environ is None else environ
    if config_flag is not None:
        return config_flag.expanduser(), "flag"
    if env.get(CONFIG_ENV, "").strip():
        return Path(env[CONFIG_ENV]).expanduser(), "env"
    return paths.global_config_path(), "global"


def find_sources(
    config_flag: Path | None = None,
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[ConfigSource, ...]:
    base, kind = base_config_target(config_flag, environ)
    sources: list[ConfigSource] = []
    if base.is_file():
        sources.append(ConfigSource(base, kind))
    elif kind != "global":
        raise ConfigError(t("config.error.not_found", path=base))
    project = find_project_config(Path.cwd() if cwd is None else cwd)
    if project is not None and not (sources and _same_file(project, sources[0].path)):
        sources.append(ConfigSource(project, "project"))
    return tuple(sources)


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.samefile(b)
    except OSError:
        return False


# --- loading ---------------------------------------------------------------------------


def _merged(sources: Sequence[ConfigSource]) -> dict[str, Any]:
    if not sources:
        return {"version": CONFIG_VERSION}
    merged: dict[str, Any] = {}
    for source in sources:
        merged = merge_dicts(merged, read_yaml(source.path))
    return merged


def load_config(
    config_flag: Path | None = None,
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> LoadedConfig:
    """Load and validate the effective configuration. Raises ``ConfigError`` (exit code 2)."""
    sources = find_sources(config_flag, cwd, environ)
    data = _merged(sources)
    try:
        config = Config.model_validate(data)
    except ValidationError as exc:
        names = ", ".join(str(s.path) for s in sources) or "-"
        raise ConfigError(
            t("config.error.invalid", sources=names), details=format_validation_error(exc)
        ) from exc
    return LoadedConfig(config, sources)


def read_language(
    config_flag: Path | None = None,
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """The configured ``language`` without full validation; ``None`` if unreadable.

    Runs before the CLI's error handler exists, so it never raises: a deleted working
    directory or an unresolvable home directory must not crash ``--help``.
    """
    try:
        value = _merged(find_sources(config_flag, cwd, environ)).get("language")
    except (ConfigError, OSError, RuntimeError):
        return None
    return value if isinstance(value, str) else None


# --- readable validation errors --------------------------------------------------------


UnionTags = Mapping[str, Collection[str]]
CONFIG_UNION_TAGS: UnionTags = {"providers": PROVIDER_TYPES}


def _format_loc(loc: tuple[int | str, ...], tags: UnionTags) -> str:
    parts = list(loc)
    # Discriminated unions add the tag ("openai_compat") to the location; users never wrote it.
    if len(parts) >= 3 and parts[2] in tags.get(str(parts[0]), ()):
        del parts[2]
    text = ""
    for part in parts:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += ("." if text else "") + part
    return text


def _join_choices(expected: str) -> str:
    """Pydantic says ``1, 2 or 3``; rebuild it with the translated "or"."""
    items = [item for item in re.split(r", | or ", expected) if item]
    if len(items) < 2:
        return expected
    return f"{', '.join(items[:-1])} {t('config.validation.or')} {items[-1]}"


_SIMPLE = {
    "missing": "config.validation.missing",
    "extra_forbidden": "config.validation.unknown_field",
    "int_parsing": "config.validation.int",
    "int_type": "config.validation.int",
    "int_from_float": "config.validation.int",
    "float_parsing": "config.validation.float",
    "float_type": "config.validation.float",
    "bool_parsing": "config.validation.bool",
    "bool_type": "config.validation.bool",
    "string_type": "config.validation.str",
    "dict_type": "config.validation.mapping",
    "model_type": "config.validation.mapping",
    "model_attributes_type": "config.validation.mapping",
    "list_type": "config.validation.list",
}


def _number(value: Any) -> Any:
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _message(error: ErrorDetails, tags: UnionTags) -> str:
    kind = error["type"]
    ctx: dict[str, Any] = dict(error.get("ctx") or {})
    if kind in _SIMPLE:
        return t(_SIMPLE[kind])
    if kind == "literal_error":
        return t("config.validation.literal", expected=_join_choices(str(ctx.get("expected", ""))))
    if kind == "greater_than_equal":
        return t("config.validation.ge", limit=_number(ctx.get("ge")))
    if kind == "less_than_equal":
        return t("config.validation.le", limit=_number(ctx.get("le")))
    if kind in ("union_tag_invalid", "union_tag_not_found"):
        field = str(error["loc"][0]) if error["loc"] else ""
        expected = ", ".join(tags.get(field, ())) or _tag_list(ctx.get("expected_tags", ""))
        noun = "provider_type" if field == "providers" else "type"
        if kind == "union_tag_invalid":
            return t(f"config.validation.{noun}_unknown", tag=ctx.get("tag"), expected=expected)
        return t(f"config.validation.{noun}_missing", expected=expected)
    if kind == "too_short":
        return t("config.validation.too_short", min=ctx.get("min_length"))
    if kind == "string_too_short":
        return t("config.validation.empty")
    if kind == "value_error" and "error" in ctx:
        return str(ctx["error"])
    # Not mapped above: a translated frame with pydantic's English text as the detail.
    return t("config.validation.other", detail=error["msg"])


def _tag_list(expected: object) -> str:
    """Pydantic's ``'command', 'regex'`` → ``command, regex``."""
    return ", ".join(part.strip(" '") for part in str(expected).split(","))


def format_validation_error(exc: ValidationError, tags: UnionTags = CONFIG_UNION_TAGS) -> list[str]:
    """One ``location: message`` line per problem, in the active language.

    ``tags``: per top-level field, the tags of a discriminated union below it (dropped from
    the location; ``verify[0]`` instead of ``verify[0].command``).
    """
    lines: list[str] = []
    for error in exc.errors():
        loc = _format_loc(error["loc"], tags)
        message = _message(error, tags)
        lines.append(f"{loc}: {message}" if loc else message)
    return lines


# --- init ------------------------------------------------------------------------------


def example_config_text() -> str:
    return resources.files("orkestra.config").joinpath("example.yaml").read_text(encoding="utf-8")


@dataclass(frozen=True)
class InitResult:
    path: Path
    written: bool
    backup: Path | None
    gitignore: Path | None  # .gitignore that received the cache entry, if any


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def ensure_gitignore_entry(gitignore: Path, entry: str = GITIGNORE_ENTRY) -> bool:
    """Append ``entry`` unless an equivalent line exists. Keeps the file's line endings.

    Bytes that are not UTF-8 (e.g. a cp1254 comment) are written back unchanged.
    """
    raw = gitignore.read_bytes() if gitignore.exists() else b""
    existing = raw.decode("utf-8", errors="surrogateescape")
    wanted = entry.strip("/")
    if any(line.strip().strip("/") == wanted for line in existing.splitlines()):
        return False
    newline = "\r\n" if "\r\n" in existing else "\n"
    if existing and not existing.endswith(("\n", "\r")):
        existing += newline
    _atomic_write(gitignore, (existing + entry + newline).encode("utf-8", "surrogateescape"))
    return True


def init_target(
    config_flag: Path | None = None, *, project: bool = False, cwd: Path | None = None
) -> Path:
    """Project file in ``cwd`` with ``project``, otherwise the base config location."""
    if project:
        return (Path.cwd() if cwd is None else cwd) / PROJECT_CONFIG_NAME
    return base_config_target(config_flag)[0]


def dump_yaml(data: Any) -> str:
    stream = StringIO()
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.dump(data, stream)
    return stream.getvalue()


def _free_backup_path(target: Path) -> Path:
    """``<name>.bak``, else ``<name>.bak.1``, ``.bak.2`` …: an earlier backup is never replaced."""
    candidate = target.with_name(target.name + ".bak")
    number = 0
    while candidate.exists():
        number += 1
        candidate = target.with_name(f"{target.name}.bak.{number}")
    return candidate


def init_config(
    target: Path, *, force: bool = False, project: bool = False, cwd: Path | None = None
) -> InitResult:
    """Copy the example config to ``target`` (never over an existing file unless ``force``).

    ``force`` keeps every earlier backup and makes none while the file is still the untouched
    example. Only a project config adds the cache entry to the repository's ``.gitignore``;
    the global config has nothing to do with the repository in the working directory.
    """
    written = False
    backup: Path | None = None
    gitignore: Path | None = None
    example = example_config_text().encode("utf-8")
    try:
        if not target.exists() or force:
            if target.exists() and target.read_bytes() != example:
                backup = _free_backup_path(target)
                _atomic_write(backup, target.read_bytes())
            _atomic_write(target, example)
            written = True
        root = find_git_root((Path.cwd() if cwd is None else cwd).resolve()) if project else None
        if root is not None and ensure_gitignore_entry(root / ".gitignore"):
            gitignore = root / ".gitignore"
    except (OSError, UnicodeError) as exc:
        raise ConfigError(t("config.error.write", path=target, reason=exc)) from exc
    return InitResult(target, written, backup, gitignore)
