"""The Claude skill (``skill/orkestra/SKILL.md``) must only name commands and flags that exist.

Claude follows the skill literally, so a command it names that the CLI does not have (a later
phase's ``status`` or ``batch``, a renamed flag) breaks the workflow. These tests read every
``orkestra …`` invocation in the skill's code, and every command or flag its prose names, and
check them against the real typer app.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

import pytest
import typer.main
from ruamel.yaml import YAML
from typer.core import TyperArgument, TyperGroup, TyperOption

from orkestra.cli import build_app
from orkestra.tasks.spec import parse_task

SKILL = Path(__file__).resolve().parents[2] / "skill" / "orkestra" / "SKILL.md"
MAX_LINES = 500  # Faz 9: the skill stays under 500 lines
_YAML = YAML(typ="safe", pure=True)

_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.DOTALL | re.MULTILINE)
_INLINE = re.compile(r"`([^`\n]+)`")
_CALL = re.compile(r"(?<![\w./-])orkestra((?:\s+[^\s`|;&]+)*)")
_HELP = "--help"  # click adds it to every command; it is not in ``params``


def _cli() -> TyperGroup:
    command = typer.main.get_command(build_app())
    assert isinstance(command, TyperGroup)
    return command


def _inline_spans(text: str) -> list[str]:
    return _INLINE.findall(_FENCE.sub("", text))


def _fenced_lines(text: str) -> list[str]:
    return [line for block in _FENCE.findall(text) for line in block.splitlines()]


def _words(code: str) -> list[str]:
    try:
        return shlex.split(code)
    except ValueError:  # an unbalanced quote: fall back to plain words
        return code.split()


def _calls(text: str, *, inline: bool = True) -> list[list[str]]:
    """Each ``orkestra …`` invocation as its shell words, comments dropped.

    Lines of fenced blocks are commands to run; inline spans (``orkestra run``) may also
    just name a command in prose.
    """
    found: list[list[str]] = []
    for span in _fenced_lines(text) + (_inline_spans(text) if inline else []):
        code = span.split(" #", 1)[0]
        found.extend(_words(match.group(1)) for match in _CALL.finditer(code))
    return [words for words in found if words]  # a bare `orkestra` names the tool


def _options(command: Any) -> dict[str, Any]:
    return {
        opt: param
        for param in command.params
        if isinstance(param, TyperOption)
        for opt in (*param.opts, *param.secondary_opts)
    }


def _takes_value(param: Any) -> bool:
    return isinstance(param, TyperOption) and not param.is_flag and not param.count


def _is_option(word: str) -> bool:
    return word.startswith("-") and len(word) > 1


def _split_options(command: Any, words: list[str], path: list[str]) -> tuple[list[str], list[str]]:
    """The positional words of one command's arguments, and problems with its options."""
    options = _options(command)
    positionals: list[str] = []
    problems: list[str] = []
    rest = list(words)
    while rest:
        word = rest.pop(0)
        if not _is_option(word):
            positionals.append(word)
            continue
        name = word.split("=", 1)[0]
        if name == _HELP:
            continue
        param = options.get(name)
        if param is None:
            problems.append(f"'{' '.join(path)}' has no option {name}")
        elif _takes_value(param) and "=" not in word and rest:
            rest.pop(0)
    return positionals, problems


def _check_arguments(command: Any, positionals: list[str], path: list[str]) -> list[str]:
    arguments = [param for param in command.params if isinstance(param, TyperArgument)]
    least = sum(max(arg.nargs, 1) for arg in arguments if arg.required)
    most = None if any(arg.nargs < 0 for arg in arguments) else sum(a.nargs for a in arguments)
    if len(positionals) < least:
        return [f"'{' '.join(path)}' needs {least} argument(s), got {len(positionals)}"]
    if most is not None and len(positionals) > most:
        return [f"'{' '.join(path)}' takes {most} argument(s), got {len(positionals)}"]
    return []


def _resolve(
    group: TyperGroup, words: list[str], *, complete: bool
) -> tuple[Any, list[str], list[str], list[str]]:
    """Walk global options and subcommands: (command, its words, path, problems)."""
    root_options = _options(group)
    rest = list(words)
    while rest and _is_option(rest[0]):  # global options before the command
        word = rest.pop(0)
        name = word.split("=", 1)[0]
        param = root_options.get(name)
        if name == _HELP or (param is not None and param.is_eager and not rest):
            return None, [], ["orkestra"], []  # `--help`, `--version`: no subcommand needed
        if param is None:
            return None, [], ["orkestra"], [f"unknown global option {name}"]
        if _takes_value(param) and "=" not in word and rest:
            rest.pop(0)
    command: Any = group
    path = ["orkestra"]
    while isinstance(command, TyperGroup):
        if not rest or _is_option(rest[0]):
            if complete and _HELP not in rest:
                return None, [], path, [f"'{' '.join(path)}' needs a subcommand"]
            break
        name = rest.pop(0)
        sub = command.commands.get(name)
        if sub is None:
            return None, [], path, [f"unknown command '{' '.join([*path, name])}'"]
        command, path = sub, [*path, name]
    return command, rest, path, []


def check_call(group: TyperGroup, words: list[str]) -> list[str]:
    """Problems with one full invocation; an empty list means click would accept it."""
    command, rest, path, problems = _resolve(group, words, complete=True)
    if command is None:
        return problems
    positionals, problems = _split_options(command, rest, path)
    if _HELP in rest:
        return problems
    return problems + _check_arguments(command, positionals, path)


def _all_options(command: Any) -> set[str]:
    found = set(_options(command)) | {_HELP}
    if isinstance(command, TyperGroup):
        for sub in command.commands.values():
            found |= _all_options(sub)
    return found


def check_mention(group: TyperGroup, words: list[str]) -> list[str]:
    """Problems with a command named in prose: its path and options, not its arguments."""
    command, rest, path, problems = _resolve(group, words, complete=False)
    if command is None:
        return problems
    return _split_options(command, rest, path)[1]


def check_reference(group: TyperGroup, span: str) -> list[str]:
    """Problems with a command or flag named in prose without ``orkestra`` (``apply --force``).

    A span that starts with a command is checked with ``check_mention``; a span of flags
    (``--dry-run``) must name options that some command has. Other inline code (field
    names, values) is ignored.
    """
    words = _words(span)
    if not words:
        return []
    if words[0] in group.commands:
        return check_mention(group, words)
    if not words[0].startswith("--"):
        return []
    known = _all_options(group)
    names = [word.split("=", 1)[0] for word in words if word.startswith("--")]
    return [f"no command has option {name}" for name in names if name not in known]


@pytest.fixture(scope="module")
def skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_the_skill_has_front_matter_with_name_and_description(skill_text: str) -> None:
    assert skill_text.startswith("---\n")
    front = _YAML.load(skill_text.split("---\n", 2)[1])
    assert front["name"] == "orkestra"
    assert len(front["description"]) > 50


def test_the_skill_stays_under_500_lines(skill_text: str) -> None:
    assert len(skill_text.splitlines()) <= MAX_LINES


def test_the_skill_names_commands(skill_text: str) -> None:
    names = {words[0] for words in _calls(skill_text)}
    assert {"doctor", "ask", "run", "show", "apply", "discard"} <= names


def test_every_command_and_flag_in_the_skill_exists(skill_text: str) -> None:
    group = _cli()
    problems = [
        f"orkestra {' '.join(words)}: {problem}"
        for words in _calls(skill_text, inline=False)
        for problem in check_call(group, words)
    ]
    mentions = [
        _words(match.group(1))
        for span in _inline_spans(skill_text)
        for match in _CALL.finditer(span)
    ]
    problems += [
        f"`orkestra {' '.join(words)}`: {problem}"
        for words in mentions
        if words
        for problem in check_mention(group, words)
    ]
    assert problems == []


@pytest.mark.parametrize(
    "words",
    [
        ["status", "--json"],  # Faz 8
        ["batch", "tasks.yaml"],  # Faz 7
        ["show", "x", "--diff", "--only-flagged"],  # Faz 8
        ["run", "--template", "docstring"],  # Faz 8
        ["providers"],
        ["config", "dump"],
        ["--nope", "doctor"],
        ["show", "--diff"],  # RUN_ID missing
        ["ask", "x", "-y"],  # no such short option
        ["apply", "a", "b"],  # one argument too many
        ["--lang", "en"],  # the value is not a subcommand
    ],
)
def test_the_checker_catches_what_does_not_exist(words: list[str]) -> None:
    assert check_call(_cli(), words)


@pytest.mark.parametrize(
    "words",
    [
        ["--lang", "en", "doctor", "--json"],
        ["providers", "enable", "<name>"],
        ["show", "<run_id>", "--diff"],
        ["ask", "<prompt with spaces>", "--context", "a.py", "--tier", "1", "--json"],
        ["--lang=en", "doctor", "--json"],
        ["--config", "x.yaml", "doctor"],
        ["--version"],
        ["run", "--help"],
        ["ask", "--schema=s.json", "x"],
    ],
)
def test_the_checker_accepts_what_exists(words: list[str]) -> None:
    assert check_call(_cli(), words) == []


def test_a_quoted_prompt_is_one_argument() -> None:
    assert _calls('`orkestra ask "two words" --json`') == [["ask", "two words", "--json"]]


@pytest.mark.parametrize(
    "span", ["apply --force", "providers enable", "--dry-run", "--schema sema.json", "ask"]
)
def test_the_checker_accepts_prose_references_that_exist(span: str) -> None:
    assert check_reference(_cli(), span) == []


@pytest.mark.parametrize(
    "span", ["apply --nope", "providers grant", "--offline", "--schema x --strict"]
)
def test_the_checker_catches_prose_references_that_do_not_exist(span: str) -> None:
    assert check_reference(_cli(), span)


def test_every_command_and_flag_named_in_the_prose_exists(skill_text: str) -> None:
    group = _cli()
    spans = [span for span in _inline_spans(skill_text) if not _CALL.search(span)]
    problems = [
        f"`{span}`: {problem}" for span in spans for problem in check_reference(group, span)
    ]
    assert problems == []


def test_the_example_task_files_in_the_skill_are_valid(skill_text: str) -> None:
    tasks = [
        _YAML.load(block)
        for block in _FENCE.findall(skill_text)
        if re.search(r"^kind:", block, re.MULTILINE)
    ]
    assert tasks, "the skill shows at least one task file"
    for data in tasks:
        parse_task(data, source="SKILL.md")
