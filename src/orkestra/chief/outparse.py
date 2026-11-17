"""Rule-based digests of long command output (Faz 13i-a, D-088).

``orkestra exec`` keeps long output out of the chief's context. For the output it knows it
needs no model and makes no mistakes: pytest (every failed or errored test, with the file and
line where it failed), ruff (check and format), pyright and compilers or type checkers that
write ``file:line`` (mypy, gcc/clang, tsc, rustc). Anything else returns ``None`` and is
summarised by a worker model instead.

The digest never drops a failed test's name; linter findings are capped for display and the
rest is counted ("+70 more in the log"). Paths inside the working directory are shown
relative to it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from orkestra.i18n import t

MAX_ITEMS = 30  # linter findings shown; failed tests are never capped

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# pytest
_PYTEST_SUMMARY = re.compile(
    r"^=*\s*((?:(?:\d+ (?:failed|passed|errors?|skipped|xfailed|xpassed|warnings?|deselected|"
    r"rerun)(?:, )?)+|no tests ran) in [\d.]+s(?: \([^)]*\))?)\s*=*$"
)
_PYTEST_RESULT = re.compile(r"^(FAILED|ERROR) (\S+)(?: - (.*))?$")
_PYTEST_HEADER = re.compile(r"^_{3,} (.+?) _{3,}$")
_PYTEST_WHERE = re.compile(r"^(\S.*?):(\d+): (\w[\w.]*)$")
_PYTEST_MARKERS = ("short test summary info", "test session starts")

# ruff
_RUFF_CONCISE = re.compile(r"^(.+?):(\d+):(\d+): ([A-Z]+\d+) (?:\[\*\] )?(.*)$")
_RUFF_CODE = re.compile(r"^([A-Z]+\d+|unformatted:) (?:\[\*\] )?(.*)$")
_ARROW = re.compile(r"^\s*--> (.+?):(\d+):(\d+)\s*$")
_RUFF_HEADLINE = re.compile(
    r"^(Found \d+ errors?\..*|All checks passed!|\d+ files? would be reformatted.*|"
    r"\d+ files? (?:already formatted|left unchanged).*)$"
)

# pyright
_PYRIGHT = re.compile(r"^\s+(.+?):(\d+):(\d+) - (error|warning|information): (.*)$")
_PYRIGHT_HEADLINE = re.compile(r"^(\d+ errors?, \d+ warnings?, \d+ informations?.*)$")

# compilers and type checkers
_COLON_FORM = re.compile(
    r"^(.+?):(\d+)(?::(\d+))?: ((?:fatal )?(?:error|warning)(?:\[[^\]]*\])?:? .*)$"
)
_PAREN_FORM = re.compile(r"^(.+?)\((\d+),(\d+)\): ((?:error|warning) \w+: .*)$")
_RUST_HEAD = re.compile(r"^((?:error|warning)(?:\[\w+\])?: .*)$")
_COMPILER_HEADLINE = re.compile(
    r"^(Found \d+ errors? in .*|\d+ errors? generated\..*|error: could not compile.*|"
    r"Found \d+ errors?\..*)$"
)


@dataclass(frozen=True)
class Item:
    text: str
    file: str | None = None
    line: int | None = None
    col: int | None = None

    @property
    def pointer(self) -> str | None:
        if self.file is None:
            return None
        where = self.file if self.line is None else f"{self.file}:{self.line}"
        return where if self.col is None else f"{where}:{self.col}"


@dataclass
class Digest:
    tool: str
    headline: str | None
    items: list[Item] = field(default_factory=list)


def parse(output: str, *, cwd: str | None = None) -> Digest | None:
    """The digest of output known tools wrote; ``None`` when no parser knows it.

    One command may run several tools (``make check``, ``pre-commit run``): every tool that
    is recognised keeps its findings. Compiler-style lines count only when nothing else was
    recognised and at least one of them is an error (one stray warning in a test log must not
    hide the failed tests from the worker's summary).
    """
    lines = [_ANSI.sub("", line).rstrip("\r") for line in output.splitlines()]
    found = [d for parser in _PARSERS if (d := parser(lines, cwd)) is not None]
    if not found:
        compiled = _compiler(lines, cwd)
        return compiled if compiled is not None and _has_error(compiled) else None
    if len(found) == 1:
        return found[0]
    headlines = [d.headline for d in found if d.headline]
    return Digest(
        "+".join(d.tool for d in found),
        " · ".join(headlines) or None,
        [item for d in found for item in d.items],
    )


def _has_error(digest: Digest) -> bool:
    return any(item.text.lower().startswith(("error", "fatal error")) for item in digest.items)


def render_items(digest: Digest, *, cap: int = MAX_ITEMS) -> str:
    """One line per item; failed tests are all shown, other findings up to ``cap``."""
    items = digest.items if digest.tool == "pytest" else digest.items[:cap]
    lines = [f"{i.pointer}: {i.text}" if i.pointer else i.text for i in items]
    if len(items) < len(digest.items):
        lines.append(t("exec.more", count=len(digest.items) - len(items)))
    return "\n".join(lines)


def relative(path: str, cwd: str | None) -> str:
    """``path`` with forward slashes, relative to ``cwd`` when it is inside it."""
    norm = path.replace("\\", "/")
    if cwd:
        base = cwd.replace("\\", "/").rstrip("/") + "/"
        if norm.lower().startswith(base.lower()):
            return norm[len(base) :]
    return norm


# --- parsers ---------------------------------------------------------------------------


def _pytest(lines: list[str], cwd: str | None) -> Digest | None:
    summary = next((line for line in reversed(lines) if _PYTEST_SUMMARY.match(line)), None)
    if summary is None:
        return None
    last = next((line for line in reversed(lines) if line.strip()), "")
    known = (
        summary.startswith("=")  # pytest's own banner line
        or summary == last  # "-q": the summary is the last line
        or any(marker in line for line in lines for marker in _PYTEST_MARKERS)
    )
    if not known:
        return None
    match = _PYTEST_SUMMARY.match(summary)
    assert match is not None
    headline = match[1]
    sections = _pytest_sections(lines, cwd)
    items: list[Item] = []
    for line in lines:
        match = _PYTEST_RESULT.match(line)
        if match is None:
            continue
        test_id = match[2]
        file = relative(test_id.split("::")[0], cwd)
        name = ".".join(test_id.split("::")[1:])
        where = _take_section(sections, name, file)
        items.append(Item(line.strip(), *(where or (file, None))))
    return Digest("pytest", headline, items)


_SETUP = re.compile(r"^ERROR at (?:setup|teardown) of (.+)$")


def _pytest_sections(lines: list[str], cwd: str | None) -> list[tuple[str, list[tuple[str, int]]]]:
    """Each failure section's test name and its ``file:line: Error`` lines, in order."""
    sections: list[tuple[str, list[tuple[str, int]]]] = []
    current: list[tuple[str, int]] | None = None
    for line in lines:
        header = _PYTEST_HEADER.match(line)
        if header:
            setup = _SETUP.match(header[1])
            current = []
            sections.append((setup[1] if setup else header[1], current))
            continue
        if line.startswith("="):
            current = None
            continue
        match = _PYTEST_WHERE.match(line)
        if current is not None and match:
            current.append((relative(match[1], cwd), int(match[2])))
    return sections


def _take_section(
    sections: list[tuple[str, list[tuple[str, int]]]], name: str, file: str
) -> tuple[str, int] | None:
    """Where the test failed (its section's last location), taking the section so that a
    test of the same name in another file gets its own: the one that went through its file
    first, else the first of that name."""
    named = [s for s in sections if s[0] == name and s[1]]
    chosen = next(
        (s for s in named if any(f == file for f, _ in s[1])), named[0] if named else None
    )
    if chosen is None:
        return None
    sections.remove(chosen)
    return chosen[1][-1]


def _ruff(lines: list[str], cwd: str | None) -> Digest | None:
    headlines = [m[1] for line in lines if (m := _RUFF_HEADLINE.match(line))]
    if not headlines:
        return None
    items: list[Item] = []
    for index, line in enumerate(lines):
        concise = _RUFF_CONCISE.match(line)
        if concise:
            text = f"{concise[4]} {concise[5]}"
            items.append(Item(text, relative(concise[1], cwd), int(concise[2]), int(concise[3])))
            continue
        code = _RUFF_CODE.match(line)
        arrow = _ARROW.match(lines[index + 1]) if code and index + 1 < len(lines) else None
        if code and arrow:
            text = f"{code[1]} {code[2]}".removeprefix("unformatted: ")
            items.append(Item(text, relative(arrow[1], cwd), int(arrow[2]), int(arrow[3])))
    if not items and not any(
        "All checks passed" in h or "already formatted" in h for h in headlines
    ):
        return None
    return Digest("ruff", headlines[-1] if len(headlines) == 1 else ", ".join(headlines), items)


def _pyright(lines: list[str], cwd: str | None) -> Digest | None:
    headline = next((m[1] for line in lines if (m := _PYRIGHT_HEADLINE.match(line))), None)
    if headline is None:
        return None
    items = [
        Item(f"{m[4]}: {m[5]}", relative(m[1], cwd), int(m[2]), int(m[3]))
        for line in lines
        if (m := _PYRIGHT.match(line))
    ]
    return Digest("pyright", headline, items)


def _compiler(lines: list[str], cwd: str | None) -> Digest | None:
    items: list[Item] = []
    for index, line in enumerate(lines):
        colon = _COLON_FORM.match(line)
        paren = _PAREN_FORM.match(line)
        head = _RUST_HEAD.match(line)
        if paren:
            items.append(Item(paren[4], relative(paren[1], cwd), int(paren[2]), int(paren[3])))
        elif colon and not colon[1].startswith(("error", "warning")):
            col = int(colon[3]) if colon[3] else None
            items.append(Item(colon[4], relative(colon[1], cwd), int(colon[2]), col))
        elif head and index + 1 < len(lines) and (arrow := _ARROW.match(lines[index + 1])):
            items.append(Item(head[1], relative(arrow[1], cwd), int(arrow[2]), int(arrow[3])))
    if not items:
        return None
    headline = next(
        (m[1] for line in reversed(lines) if (m := _COMPILER_HEADLINE.match(line))), None
    )
    return Digest("compiler", headline, items)


_PARSERS: tuple[Callable[[list[str], str | None], Digest | None], ...] = (
    _ruff, _pyright, _pytest,
)  # fmt: skip
