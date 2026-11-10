"""The Claude skill (``skill/orkestra/SKILL.md``) must only name commands and flags that exist.

Claude follows the skill literally, so a command it names that the CLI does not have (a later
phase's ``status`` or ``batch``, a renamed flag) breaks the workflow. These tests read every
``orkestra …`` invocation in the skill's code and check it against the real typer app.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import typer.main
from ruamel.yaml import YAML
from typer.core import TyperGroup

from orkestra.cli import build_app
from orkestra.tasks.spec import parse_task

SKILL = Path(__file__).resolve().parents[2] / "skill" / "orkestra" / "SKILL.md"
MAX_LINES = 500  # Faz 9: the skill stays under 500 lines
_YAML = YAML(typ="safe", pure=True)

_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.DOTALL | re.MULTILINE)
_INLINE = re.compile(r"`([^`\n]+)`")
_CALL = re.compile(r"(?<![\w./-])orkestra((?:\s+[^\s`|;&]+)*)")
_FLAG = re.compile(r"^--[a-z][a-z-]*")


def _cli() -> TyperGroup:
    command = typer.main.get_command(build_app())
    assert isinstance(command, TyperGroup)
    return command


def _code_spans(text: str) -> list[str]:
    """Code from fenced blocks (line by line) and inline backticks outside them."""
    spans: list[str] = []
    for block in _FENCE.findall(text):
        spans.extend(block.splitlines())
    spans.extend(_INLINE.findall(_FENCE.sub("", text)))
    return spans


def _calls(text: str) -> list[list[str]]:
    """Each ``orkestra …`` invocation as its words, comments dropped."""
    found: list[list[str]] = []
    for span in _code_spans(text):
        code = span.split(" #", 1)[0]
        found.extend(match.group(1).split() for match in _CALL.finditer(code))
    return [words for words in found if words]  # a bare `orkestra` names the tool


def _options(command: Any) -> set[str]:
    return {opt for param in command.params for opt in (*param.opts, *param.secondary_opts)}


def check_call(group: TyperGroup, words: list[str]) -> list[str]:
    """Problems with one invocation; an empty list means it exists as written."""
    root_options = _options(group)
    words = list(words)
    while words and words[0].startswith("-"):  # global options before the command
        flag = words.pop(0).split("=", 1)[0]
        if flag not in root_options:
            return [f"unknown global option {flag}"]
        if flag in {"--lang", "--config"} and "=" not in flag and words:
            words.pop(0)
    command: Any = group
    path = ["orkestra"]
    while isinstance(command, TyperGroup):
        if not words:
            return [f"'{' '.join(path)}' needs a subcommand"]
        name = words.pop(0)
        sub = command.commands.get(name)
        if sub is None:
            return [f"unknown command '{' '.join([*path, name])}'"]
        command, path = sub, [*path, name]
    allowed = _options(command)
    problems = []
    for word in words:
        flag = _FLAG.match(word)
        if flag and flag.group(0) not in allowed:
            problems.append(f"'{' '.join(path)}' has no option {flag.group(0)}")
    return problems


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
        for words in _calls(skill_text)
        for problem in check_call(group, words)
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
        ["ask", '"<prompt>"', "--context", "a.py", "--tier", "1", "--json"],
    ],
)
def test_the_checker_accepts_what_exists(words: list[str]) -> None:
    assert check_call(_cli(), words) == []


def test_the_example_task_files_in_the_skill_are_valid(skill_text: str) -> None:
    tasks = [
        _YAML.load(block)
        for block in _FENCE.findall(skill_text)
        if re.search(r"^kind:", block, re.MULTILINE)
    ]
    assert tasks, "the skill shows at least one task file"
    for data in tasks:
        parse_task(data, source="SKILL.md")
