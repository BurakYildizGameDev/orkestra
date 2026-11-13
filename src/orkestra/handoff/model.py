"""The handoff file: parse it, change one section, write it back byte for byte (Mimari §17).

A chief edits this file by hand as well, so the round trip must not lose anything: unknown
sections, their order, blank lines, Turkish text, emoji, code fences (a ``## `` inside a fence
is not a heading), and CRLF line endings. ``update`` changes only what it was asked to change.

Slugs (``goal``, ``in_progress`` …) are stable and English, like the headings; the text inside
may be in any language. A duplicate heading uses the first section and keeps both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise
from typing import Any

MARKER = "<!-- orkestra-handoff v1 -->"
MISSING_MARKER = "missing_marker"
DUPLICATE_SECTION = "duplicate_section"

SECTION_ORDER = (
    "goal",
    "status",
    "done",
    "in_progress",
    "decisions",
    "open_questions",
    "watch_out",
)
SECTION_HEADINGS: dict[str, str] = {
    "goal": "Goal",
    "status": "Status",
    "done": "Done",
    "in_progress": "In progress",
    "decisions": "Decisions",
    "open_questions": "Open questions",
    "watch_out": "Watch out",
}
LAST_UPDATED = "last_updated"
LAST_UPDATED_HEADING = "Last updated"
LIST_SECTIONS = ("done", "decisions")

_SLUG_BY_HEADING: dict[str, str] = {
    **{heading: slug for slug, heading in SECTION_HEADINGS.items()},
    LAST_UPDATED_HEADING: LAST_UPDATED,
}
_HEADING = re.compile(r"^##\s+(.+?)\s*$")
_FENCE = re.compile(r"^\s*```")


@dataclass
class Section:
    heading: str
    start: int  # index of the heading line
    end: int  # exclusive: the next heading line, or the end of the document
    slug: str | None  # None for a section Orkestra does not know


@dataclass(frozen=True)
class LastUpdated:
    chief: str | None
    at: datetime | None
    commit: str | None


@dataclass
class Document:
    lines: list[str]
    newline: str = "\n"
    ends_with_newline: bool = True
    marker: bool = True
    warnings: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)

    def section(self, slug: str) -> Section | None:
        """The first section with ``slug``; a duplicate later in the file is ignored."""
        for section in self.sections:
            if section.slug == slug:
                return section
        return None


def _scan(lines: list[str]) -> tuple[list[Section], list[str]]:
    sections: list[Section] = []
    warnings: list[str] = []
    seen: set[str] = set()
    fenced = False
    for index, line in enumerate(lines):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = _HEADING.match(line)
        if match is None:
            continue
        heading = match.group(1)
        slug = _SLUG_BY_HEADING.get(heading)
        sections.append(Section(heading, index, len(lines), slug))
        if slug is not None:
            if slug in seen:
                warnings.append(DUPLICATE_SECTION)
            else:
                seen.add(slug)
    for section, following in pairwise(sections):
        section.end = following.start
    return sections, warnings


def parse(text: str) -> Document:
    newline = "\r\n" if "\r\n" in text else "\n"
    ends_with_newline = text.endswith(newline)
    lines = text.split(newline)
    if ends_with_newline:
        lines = lines[:-1]
    marker = bool(lines) and lines[0] == MARKER
    sections, warnings = _scan(lines)
    if not marker:
        warnings.insert(0, MISSING_MARKER)
    return Document(lines, newline, ends_with_newline, marker, warnings, sections)


def render(document: Document) -> str:
    text = document.newline.join(document.lines)
    if document.ends_with_newline:
        text += document.newline
    return text


def _refresh(document: Document) -> None:
    document.sections = _scan(document.lines)[0]
    document.marker = bool(document.lines) and document.lines[0] == MARKER


def _content(document: Document, section: Section) -> list[str]:
    return document.lines[section.start + 1 : section.end]


def section_text(document: Document, slug: str) -> str:
    """The section body without the blank lines around it; ``""`` if it is not there."""
    section = document.section(slug)
    if section is None:
        return ""
    return "\n".join(_content(document, section)).strip("\n")


def set_section(document: Document, slug: str, text: str) -> None:
    """Replace one section's body; every other byte stays as it was."""
    section = document.section(slug)
    if section is None:
        _append_section(document, slug, text)
        return
    content = _content(document, section)
    had_blank_line = bool(content) and not content[-1].strip()
    new_content = text.split("\n") if text else []
    if had_blank_line:
        new_content.append("")
    document.lines[section.start + 1 : section.end] = new_content
    _refresh(document)


def _append_section(document: Document, slug: str, text: str) -> None:
    heading = SECTION_HEADINGS.get(slug, LAST_UPDATED_HEADING if slug == LAST_UPDATED else slug)
    if document.lines and document.lines[-1].strip():
        document.lines.append("")
    document.lines.extend([f"## {heading}", *text.split("\n")])
    if document.lines[-1].strip():
        document.lines.append("")
        document.ends_with_newline = True
    _refresh(document)


def add_item(document: Document, slug: str, item: str) -> None:
    """Append a list item to ``Done`` or ``Decisions``."""
    line = item if item.startswith("- ") else f"- {item}"
    current = section_text(document, slug) or ""
    set_section(document, slug, f"{current}\n{line}" if current else line)


_MINUTE_STAMP = re.compile(r"T\d{2}:\d{2}(?:[+-]|Z)")


def _at_text(document: Document, at: datetime) -> str:
    """Keep the file's own timestamp precision: minutes if it had minutes, else seconds."""
    existing = section_text(document, LAST_UPDATED) or ""
    if _MINUTE_STAMP.search(existing):
        return at.isoformat(timespec="minutes")
    return at.isoformat()


def set_last_updated(document: Document, chief: str, at: datetime, commit: str | None) -> None:
    set_section(
        document,
        LAST_UPDATED,
        f"chief: {chief} | at: {_at_text(document, at)} | commit: {commit or 'none'}",
    )


def parse_last_updated(document: Document) -> LastUpdated | None:
    text = section_text(document, LAST_UPDATED)
    if not document.section(LAST_UPDATED):
        return None
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        for part in line.split("|"):
            key, separator, value = part.partition(":")
            if separator:
                values[key.strip().lower()] = value.strip()
        break
    at_text = values.get("at")
    try:
        at = datetime.fromisoformat(at_text) if at_text else None
    except ValueError:
        at = None
    commit = values.get("commit")
    return LastUpdated(
        chief=values.get("chief") or None,
        at=at,
        commit=None if commit in (None, "", "none") else commit,
    )


def as_json(document: Document) -> dict[str, Any]:
    """The structured form of ``show --json``: every known section, unknown ones, the marker."""
    sections = {
        slug: {
            "heading": SECTION_HEADINGS[slug],
            "text": section_text(document, slug) or "",
        }
        for slug in SECTION_ORDER
    }
    unknown = [
        {"heading": section.heading, "text": "\n".join(_content(document, section)).strip("\n")}
        for section in document.sections
        if section.slug is None
    ]
    updated = parse_last_updated(document)
    return {
        "marker": document.marker,
        "warnings": list(document.warnings),
        "sections": sections,
        "unknown_sections": unknown,
        "last_updated": None
        if updated is None
        else {
            "chief": updated.chief,
            "at": updated.at.isoformat() if updated.at is not None else None,
            "commit": updated.commit,
        },
    }


def template(project: str, chief: str, at: datetime, commit: str | None) -> str:
    lines = [MARKER, f"# Devir: {project}", ""]
    for slug in SECTION_ORDER:
        lines.extend([f"## {SECTION_HEADINGS[slug]}", ""])
    lines.append(f"## {LAST_UPDATED_HEADING}")
    lines.append(f"chief: {chief} | at: {at.isoformat()} | commit: {commit or 'none'}")
    return "\n".join(lines) + "\n"
