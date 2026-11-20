"""The README and the user guides name only commands and flags that exist, stay short, and
keep their links working (düzeltme-fable c, D-108). The checker is the skill's (Faz 9a)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.unit.test_skill import (
    _calls,
    _cli,
    _inline_spans,
    _invocations,
    check_call,
    check_mention,
)

ROOT = Path(__file__).resolve().parents[2]
READMES = ("README.md", "README.tr.md")
DOCS = (*READMES, "docs/guide.md", "docs/guide.tr.md", "docs/recipes.md", "docs/recipes.tr.md")
README_MAX_LINES = 320  # the plan's target is ~300: details live in docs/guide*.md
_LINK = re.compile(r"\]\(([^)\s]+)\)")
_HEADING = re.compile(r"^#{1,6} (.+)$", re.MULTILINE)
_FENCE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
_OUTPUT = re.compile(r"^```text\n.*?^```\n?", re.DOTALL | re.MULTILINE)


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _commands(name: str) -> str:
    """The text with sample output (```text blocks) left out and continued lines joined."""
    return _OUTPUT.sub("", _text(name)).replace("\\\n", " ")


def _anchor(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to dashes."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


@pytest.mark.parametrize("name", DOCS)
def test_every_command_and_flag_in_the_docs_exists(name: str) -> None:
    text = _commands(name)
    group = _cli()
    problems = [
        f"orkestra {' '.join(words)}: {problem}"
        for words in _calls(text, inline=False)
        for problem in check_call(group, words)
    ]
    mentions = [words for span in _inline_spans(text) for words in _invocations(span)]
    problems += [
        f"`orkestra {' '.join(words)}`: {problem}"
        for words in mentions
        if words
        for problem in check_mention(group, words)
    ]
    assert problems == []


@pytest.mark.parametrize("name", READMES)
def test_the_readme_is_short(name: str) -> None:
    assert len(_text(name).splitlines()) <= README_MAX_LINES


@pytest.mark.parametrize("name", READMES)
def test_the_readme_has_known_limits_and_no_phase_counting_status(name: str) -> None:
    text = _text(name)
    headings = [h.lower() for h in _HEADING.findall(text)]
    assert any(h.startswith(("known limits", "bilinen sınırlar")) for h in headings)
    dash = chr(0x2013)  # the en dash the old status box used
    assert f"Phase 3{dash}4" not in text and f"Faz 3{dash}4" not in text
    assert not re.search(f"Phases? 0{dash}4|Faz 0{dash}4|0{dash}4\\. faz", text)


@pytest.mark.parametrize("name", READMES)
def test_the_readme_names_every_provider_kind_and_five_languages(name: str) -> None:
    text = _text(name)
    for word in ("Ollama", "OpenAI", "Codex", "Antigravity", "cli_agent"):
        assert word in text, word
    assert "--lang en|tr" not in text
    for code in ("en", "tr", "de", "es", "fr"):
        assert code in text


@pytest.mark.parametrize("name", DOCS)
def test_local_links_and_anchors_resolve(name: str) -> None:
    path = ROOT / name
    text = _text(name)
    problems: list[str] = []
    for target in _LINK.findall(_FENCE.sub("", text)):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        file_part, _, anchor = target.partition("#")
        linked = (path.parent / file_part).resolve() if file_part else path
        if not linked.exists():
            problems.append(f"{target}: no such file")
            continue
        if anchor and linked.suffix == ".md":
            body = _FENCE.sub("", linked.read_text(encoding="utf-8"))
            anchors = {_anchor(h) for h in _HEADING.findall(body)}
            if anchor not in anchors:
                problems.append(f"{target}: no such heading")
    assert problems == []
