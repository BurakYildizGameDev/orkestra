"""Task templates: ``templates list|show`` and ``run --template`` (Mimari §19, Faz 8a).

A template is YAML: ``description`` (text, or text per language: ``{en: ..., tr: ...}``,
the current language or else English), ``params`` (``name: {default, description}``; no
``default`` means the parameter is required) and ``task`` (task fields without ``id``).

- Built-in templates ship in ``orkestra/templates/``; ``.orkestra/templates/<name>.yaml`` in
  the working directory overrides one with the same name (``overrides`` says so, and the
  CLI warns: a cloned repository could ship its own commands), or adds a new one.
- ``params``: ``name: {default, description}``, or ``name: value`` for a default only;
  ``name:`` with nothing (or no ``default``) is a required parameter.
- ``expand``: one task per file the ``--files`` patterns match (globs as in ``context.globs``:
  ``.gitignore`` and the ignore file are respected; only real files inside the working
  directory count, also for plain paths). In every string of ``task``, ``$file``
  becomes the file (relative to the working directory) and ``$<param>`` the parameter's
  value, with ``string.Template.safe_substitute``: an inserted value is never substituted
  again, so a ``$`` in a file name stays as it is. A ``command`` check whose ``run`` ends
  up empty (an optional ``$check`` left out) is dropped.
- Every task gets the template's name as its first tag (``stats``, learning routing) and an
  id from the template and the file. The tasks run as a batch.
"""

from __future__ import annotations

import re
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Literal

from ruamel.yaml import YAML, YAMLError

from orkestra.errors import UsageError
from orkestra.i18n import get_language, t
from orkestra.tasks.batch import BatchSpec, from_tasks
from orkestra.tasks.context import existing_files
from orkestra.tasks.spec import TaskSpec, parse_task

PROJECT_DIR = Path(".orkestra") / "templates"
TEMPLATE_KEYS = frozenset({"description", "params", "task"})
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_ID_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

Source = Literal["builtin", "project"]


@dataclass(frozen=True)
class Param:
    name: str
    default: str | None  # None: required
    description: str = ""


@dataclass(frozen=True)
class Template:
    name: str
    source: Source
    description: str
    params: tuple[Param, ...]
    task: Mapping[str, Any]
    path: str = ""  # where it was read from (a project template's file)
    overrides: bool = False  # a project template with a built-in one's name


def _builtin_dir() -> Traversable:
    return resources.files("orkestra").joinpath("templates")


def _bad(path: object, key: str, **params: object) -> UsageError:
    return UsageError(t(key, path=path, **params))


def _parse(name: str, source: Source, text: str, where: object) -> Template:
    try:
        data = YAML(typ="safe").load(text)
    except YAMLError as exc:
        raise _bad(where, "template.error.yaml", problem=str(exc).splitlines()[0]) from None
    if not isinstance(data, dict):
        raise _bad(where, "config.error.not_mapping")
    unknown = sorted(set(data) - TEMPLATE_KEYS)
    if unknown:
        raise _bad(where, "template.error.keys", keys=", ".join(unknown))
    task = data.get("task")
    if not isinstance(task, dict) or "id" in task:
        raise _bad(where, "template.error.task")
    raw = data.get("params") or {}
    if not isinstance(raw, dict):
        raise _bad(where, "template.error.params")
    params: list[Param] = []
    for key, value in raw.items():
        if isinstance(value, dict):  # {default, description}
            default, about = value.get("default"), str(value.get("description", ""))
        else:  # short form: the default itself (nothing: required)
            default, about = value, ""
        params.append(Param(str(key), None if default is None else str(default), about))
    return Template(name, source, _description(data.get("description")), tuple(params), task)


def _description(value: Any) -> str:
    if isinstance(value, dict):
        text = value.get(get_language()) or value.get("en") or next(iter(value.values()), "")
        return str(text)
    return "" if value is None else str(value)


def available(cwd: Path) -> dict[str, Template]:
    """Every template by name: built-in ones, then the project's (which win)."""
    found: dict[str, Template] = {}
    for entry in sorted(_builtin_dir().iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".yaml"):
            name = entry.name.removesuffix(".yaml")
            found[name] = _parse(name, "builtin", entry.read_text(encoding="utf-8"), entry.name)
    project = cwd / PROJECT_DIR
    if project.is_dir():
        for path in sorted(project.glob("*.yaml")):
            if _NAME.match(path.stem):
                text = path.read_bytes().decode("utf-8", errors="replace")
                template = _parse(path.stem, "project", text, path)
                overrides = found.get(path.stem, template).source == "builtin"
                found[path.stem] = Template(
                    template.name, "project", template.description, template.params,
                    template.task, str(path), overrides,
                )  # fmt: skip
    return found


def find(name: str, *, cwd: Path) -> Template:
    templates = available(cwd)
    if name not in templates:
        raise UsageError(
            t("template.error.unknown", name=name, available=", ".join(sorted(templates)))
        )
    return templates[name]


def parse_params(pairs: Sequence[str]) -> dict[str, str]:
    """``--param key=value`` (repeatable)."""
    values: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise UsageError(t("template.error.param_format", value=pair))
        values[key.strip()] = value
    return values


def _values(template: Template, given: Mapping[str, str]) -> dict[str, str]:
    known = {p.name for p in template.params}
    unknown = sorted(set(given) - known)
    if unknown:
        names = ", ".join(sorted(known)) or "-"
        raise UsageError(t("template.error.param_unknown", name=template.name,
                           params=", ".join(unknown), known=names))  # fmt: skip
    values: dict[str, str] = {}
    for param in template.params:
        value = given.get(param.name, param.default)
        if value is None:
            raise UsageError(t("template.error.param_missing", name=template.name,
                               param=param.name))  # fmt: skip
        values[param.name] = value
    return values


def _fill(value: Any, mapping: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return string.Template(value).safe_substitute(mapping)
    if isinstance(value, list):
        return [_fill(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: _fill(item, mapping) for key, item in value.items()}
    return value


def _drop_empty_commands(task: dict[str, Any]) -> None:
    checks = task.get("verify")
    if isinstance(checks, list):
        task["verify"] = [
            c for c in checks
            if not (isinstance(c, dict) and c.get("type") == "command"
                    and not str(c.get("run", "")).strip())
        ]  # fmt: skip


def _task_id(template: str, file: str, taken: set[str]) -> str:
    stem = _ID_CHARS.sub("-", Path(file).stem).strip("-._") or "file"
    base = f"{template}-{stem}"
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}-{number}", number + 1
    taken.add(candidate)
    return candidate


def expand(
    template: Template,
    patterns: Sequence[str],
    params: Mapping[str, str],
    *,
    cwd: Path,
    ignore_file: str | None = None,
) -> BatchSpec:
    """One task per matching file, as a batch. No match is a usage error."""
    values = _values(template, params)
    root = cwd.resolve()
    files = [p.relative_to(root).as_posix() for p in existing_files(patterns, root, ignore_file)]
    if not files:
        raise UsageError(t("template.error.no_files", patterns=", ".join(patterns)))
    tasks: list[TaskSpec] = []
    taken: set[str] = set()
    for file in files:
        data = _fill(dict(template.task), {**values, "file": file})
        _drop_empty_commands(data)
        tags = [str(tag) for tag in data.get("tags") or []]
        data["tags"] = [template.name, *[tag for tag in tags if tag != template.name]]
        data["id"] = _task_id(template.name, file, taken)
        tasks.append(parse_task(data, source=f"template {template.name} ({file})"))
    return from_tasks(tasks, source=f"template {template.name}")


def to_batch_document(spec: BatchSpec) -> dict[str, Any]:
    """The tasks as a batch file would hold them (``run --template --dry-run``)."""
    return {
        "tasks": [
            task.model_dump(mode="json", by_alias=True, exclude_defaults=True)
            | {"id": task.id, "kind": task.kind, "prompt": task.prompt, "tags": list(task.tags)}
            for task in spec.tasks
        ]
    }
