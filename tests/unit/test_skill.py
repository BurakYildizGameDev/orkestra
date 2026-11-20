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
REFERENCE = SKILL.with_name("reference.md")  # the details, read only when needed (D-113)
CORE_MAX_BYTES = 6000  # what every delegating session loads (Faz 13p)
MAX_LINES = 500  # Faz 9: the skill stays under 500 lines
_YAML = YAML(typ="safe", pure=True)

_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.DOTALL | re.MULTILINE)
_INLINE = re.compile(r"`([^`\n]+)`")
_SHELL_OPERATORS = "|;&"
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


def _tokens(code: str) -> list[str]:
    """Shell words; ``|``, ``;`` and ``&`` outside quotes are tokens of their own."""
    lexer = shlex.shlex(code, posix=True, punctuation_chars=_SHELL_OPERATORS)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:  # an unbalanced quote: fall back to plain words
        return code.split()


def _invocations(code: str) -> list[list[str]]:
    """The words after each ``orkestra`` up to the next shell operator, comments dropped."""
    found: list[list[str]] = []
    current: list[str] | None = None
    for token in _tokens(code):
        if token and all(char in _SHELL_OPERATORS for char in token):
            current = None
        elif token == "orkestra":
            current = []
            found.append(current)
        elif current is not None:
            current.append(token)
    return found


def _calls(text: str, *, inline: bool = True) -> list[list[str]]:
    """Each ``orkestra …`` invocation as its shell words.

    Lines of fenced blocks are commands to run; inline spans (``orkestra run``) may also
    just name a command in prose.
    """
    spans = _fenced_lines(text) + (_inline_spans(text) if inline else [])
    found = [words for span in spans for words in _invocations(span)]
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


def _skip_values(param: Any, word: str, rest: list[str]) -> None:
    """Drop the values an option takes from ``rest`` (``--point 1 2``: two)."""
    if _takes_value(param) and "=" not in word:
        del rest[: max(param.nargs, 1)]


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
        if word == "--":  # click: everything after it is an argument (``exec -- pytest -q``)
            positionals.extend(rest)
            break
        if not _is_option(word):
            positionals.append(word)
            continue
        name = word.split("=", 1)[0]
        if name == _HELP:
            continue
        param = options.get(name)
        if param is None:
            problems.append(f"'{' '.join(path)}' has no option {name}")
        else:
            _skip_values(param, word, rest)
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
        _skip_values(param, word, rest)
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

    A span that starts with a command is checked with ``check_mention``; a span of options
    (``--dry-run``, ``-q``) must name options that some command has. Other inline code
    (field names, values) is ignored.
    """
    words = _words(span)
    if not words:
        return []
    if words[0] in group.commands:
        return check_mention(group, words)
    if not _is_option(words[0]):
        return []
    known = _all_options(group)
    names = [word.split("=", 1)[0] for word in words if _is_option(word)]
    return [f"no command has option {name}" for name in names if name not in known]


@pytest.fixture(scope="module")
def skill_text() -> str:
    """Both files: every command and flag in either one must exist."""
    return SKILL.read_text(encoding="utf-8") + "\n" + REFERENCE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def core_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_the_skill_core_is_small(core_text: str) -> None:
    assert len(core_text.encode("utf-8")) <= CORE_MAX_BYTES


def test_the_core_keeps_the_rules_and_points_at_the_reference(core_text: str) -> None:
    for must in (
        "orkestra run --template",
        "orkestra show <run_id> --report",
        "orkestra apply <run_id> --max-risk low",
        "--only-ok --max-risk low",
        "orkestra exec --",
        "orkestra handoff update",
        "--force",
        "reference.md",
    ):
        assert must in core_text, must


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
    mentions = [words for span in _inline_spans(skill_text) for words in _invocations(span)]
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
        ["handoff", "delete"],  # Faz 10 has init/update/check/show, not delete
        ["batch", "tasks.yaml", "--estimates"],  # typo of --estimate
        ["apply", "--only-okay"],
        ["show", "--diff", "--only-flagged"],  # RUN_ID missing
        ["review"],  # RUN_ID missing
        ["map", "--nope"],  # no such option
        ["templates", "edit", "x"],  # no such subcommand
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
        ["show", "<run_id>", "--diff", "--only-flagged"],  # Faz 8b
        ["ask", "<prompt with spaces>", "--context", "a.py", "--tier", "1", "--json"],
        ["--lang=en", "doctor", "--json"],
        ["--config", "x.yaml", "doctor"],
        ["--version"],
        ["run", "--help"],
        ["batch", "tasks.yaml", "--parallel", "4", "--fail-fast", "--json"],
        ["batch", "tasks.yaml", "--estimate", "--json"],  # Faz 7b
        ["batch", "tasks.yaml", "--json", "--yes-cost"],
        ["exec", "--max-lines", "5", "--", "uv", "run", "pytest", "-q", "-x"],  # Faz 13i-a
        ["tokens", "--since", "7d", "--top", "3", "--json"],  # Faz 13h
        ["apply", "--batch", "<batch_id>", "--only-ok", "--json"],
        ["stats", "--since", "7d", "--json"],
        ["status", "--json"],  # Faz 8a
        ["map", "--json"],  # Faz 8b
        ["review", "<run_id>", "--json"],  # Faz 8b
        ["plan", "expand", "plan.md", "-o", "batch.yaml"],  # Faz 8b
        ["templates", "list", "--json"],
        ["templates", "show", "docstring"],
        ["run", "--template", "docstring", "--files", "src/*.py", "--param", "style=numpy"],
        ["ask", "x", "--no-cache"],
        ["cache", "clear"],
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
    "span", ["apply --nope", "providers grant", "--offline", "--schema x --strictly"]
)
def test_the_checker_catches_prose_references_that_do_not_exist(span: str) -> None:
    assert check_reference(_cli(), span)


def test_every_command_and_flag_named_in_the_prose_exists(skill_text: str) -> None:
    group = _cli()
    spans = [span for span in _inline_spans(skill_text) if "orkestra" not in _tokens(span)]
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


def test_the_example_batch_files_in_the_skill_are_valid(skill_text: str, tmp_path: Path) -> None:
    from orkestra.tasks.batch import load_batch

    blocks = [b for b in _FENCE.findall(skill_text) if re.search(r"^tasks:", b, re.MULTILINE)]
    assert blocks, "the skill shows a batch file (Faz 7b)"
    for index, block in enumerate(blocks):
        path = tmp_path / f"batch{index}.yaml"
        path.write_text(block, encoding="utf-8")
        load_batch(path)


def test_a_quoted_pipe_does_not_end_the_call() -> None:
    calls = _calls('`orkestra ask "a | b" --nope --json`')
    assert calls == [["ask", "a | b", "--nope", "--json"]]
    assert check_call(_cli(), calls[0])


def test_a_pipe_outside_quotes_ends_the_call() -> None:
    assert _calls("`orkestra budget --json | head -5`") == [["budget", "--json"]]


@pytest.mark.parametrize("span", ["-f", "-q --json"])
def test_the_checker_catches_prose_short_options_that_do_not_exist(span: str) -> None:
    assert check_reference(_cli(), span)


def test_an_option_with_two_values_consumes_both() -> None:
    import typer

    app = typer.Typer()

    @app.command()
    def pair(point: tuple[int, int] = typer.Option((0, 0), "--point"), name: str = "") -> None:
        """A command with a two-value option."""

    command = typer.main.get_command(app)
    positionals, problems = _split_options(command, ["--point", "1", "2"], ["pair"])
    assert positionals == [] and problems == []


def test_the_field_list_names_every_task_field_and_nothing_else(skill_text: str) -> None:
    from orkestra.tasks.spec import TaskSpec

    line = next(line for line in skill_text.splitlines() if line.startswith("Alanlar:"))
    top_level = re.sub(r"\([^)]*\)", "", line)  # values and sub-fields are in parentheses
    named = {name.split(".")[0] for name in re.findall(r"`([a-z_][a-z_.]*)`", top_level)}
    fields = {info.alias or name for name, info in TaskSpec.model_fields.items()}
    assert named == fields


def test_the_skill_teaches_bulk_delegation_and_cross_review(skill_text: str) -> None:
    """Faz 13m (D-098): small work is not delegated, mechanical work goes in one batch, and
    a change another provider reviewed as low risk is applied from the report."""
    assert "orkestra run --template" in skill_text and "Tek küçük işi devretme" in skill_text
    assert "işe özel denetim betiği yazma" in skill_text
    assert "orkestra show <run_id> --report" in skill_text
    assert "orkestra apply <run_id> --max-risk low" in skill_text
    assert "--only-ok --max-risk low" in skill_text


# --- the chief guide: what a chief other than Claude learns Orkestra from (Faz 13n) ---------

GUIDE = Path(__file__).resolve().parents[2] / "src" / "orkestra" / "prompts" / "chief_guide.md"
GUIDE_MAX_LINES = 30  # non-empty lines; with the default brief limit (60) at least 20 lines
# of project content still fit beside it (D-066), and no line is wrapped (WRAP_WIDTH)
# Flags that carry a rule of the skill: the guide must keep them, or a non-Claude chief
# applies without review, reads whole diffs, or starts by scanning the project.
RULE_FLAGS = ("--max-risk", "--report", "--only-flagged", "--only-ok", "--brief", "--dry-run")


@pytest.fixture(scope="module")
def guide_text() -> str:
    return GUIDE.read_text(encoding="utf-8")


def test_every_command_and_flag_in_the_chief_guide_exists(guide_text: str) -> None:
    group = _cli()
    problems = [
        f"orkestra {' '.join(words)}: {problem}"
        for words in _calls(guide_text, inline=False)
        for problem in check_call(group, words)
    ]
    problems += [
        f"`orkestra {' '.join(words)}`: {problem}"
        for span in _inline_spans(guide_text)
        for words in _invocations(span)
        if words
        for problem in check_mention(group, words)
    ]
    spans = [span for span in _inline_spans(guide_text) if "orkestra" not in _tokens(span)]
    problems += [f"`{span}`: {p}" for span in spans for p in check_reference(group, span)]
    assert problems == []


def test_the_chief_guide_names_every_command_the_skill_names(
    skill_text: str, guide_text: str
) -> None:
    in_skill = {words[0] for words in _calls(skill_text)}
    in_guide = {words[0] for words in _calls(guide_text)}
    assert sorted(in_skill - in_guide) == []


def test_the_chief_guide_keeps_the_rule_flags_of_the_skill(
    skill_text: str, guide_text: str
) -> None:
    for flag in RULE_FLAGS:
        assert flag in skill_text, flag  # still a rule of the skill
        assert flag in guide_text, flag


def test_the_chief_guide_is_short(guide_text: str) -> None:
    from orkestra.handoff.brief import WRAP_WIDTH

    lines = [line for line in guide_text.splitlines() if line.strip()]
    assert len(lines) <= GUIDE_MAX_LINES
    assert [line for line in lines if len(line) > WRAP_WIDTH] == []


def test_every_command_in_the_chief_guide_is_complete(guide_text: str) -> None:
    """The guide has no code blocks: its inline commands are the ones a chief runs, so each
    must also have its arguments (``orkestra review`` without a run id would fail)."""
    group = _cli()
    problems = [
        f"`orkestra {' '.join(words)}`: {problem}"
        for span in _inline_spans(guide_text)
        for words in _invocations(span)
        if words
        for problem in check_call(group, words)
    ]
    assert problems == []


def test_the_chief_guide_points_at_rules_a_chief_can_reach(guide_text: str) -> None:
    assert "https://github.com/" in guide_text  # an installed package has no skill/ folder
    assert "in the Orkestra repository" not in guide_text
