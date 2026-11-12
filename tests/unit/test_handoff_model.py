"""Handoff file parsing and rendering: the round trip must never lose anything (Faz 10a)."""

from __future__ import annotations

from datetime import datetime

from orkestra.handoff import model

MARKER = "<!-- orkestra-handoff v1 -->"

DOCUMENT = """\
<!-- orkestra-handoff v1 -->
# Devir: örnek proje 🚀

Some free text before the sections stays exactly where it is.

## Goal
Türkçe hedef: ığüşöç — emoji ✅

## Status
faz 10a

## Notes from the old chief
This section is not one of ours; it must survive.

```markdown
## This is not a section heading
- because it is inside a code block
```

## Done
- [2026-11-07 claude] ilk iş

## Last updated

chief: claude | at: 2026-11-07T10:15+03:00 | commit: abc123
"""


def test_parse_and_render_keep_every_byte_of_a_hand_edited_file() -> None:
    assert model.render(model.parse(DOCUMENT)) == DOCUMENT


def test_a_heading_inside_a_code_fence_is_not_a_section() -> None:
    document = model.parse(DOCUMENT)
    assert [section.heading for section in document.sections] == [
        "Goal",
        "Status",
        "Notes from the old chief",
        "Done",
        "Last updated",
    ]
    assert document.section("goal") is not None
    assert model.section_text(document, "goal") == "Türkçe hedef: ığüşöç — emoji ✅"


def test_unknown_sections_survive_an_update_in_their_original_place() -> None:
    document = model.parse(DOCUMENT)
    model.set_section(document, "goal", "new goal")
    rendered = model.render(document)
    assert "## Notes from the old chief" in rendered
    assert "This section is not one of ours; it must survive." in rendered
    assert rendered.index("## Goal") < rendered.index("## Notes from the old chief")
    assert rendered.index("## Notes from the old chief") < rendered.index("## Done")
    assert "new goal" in rendered
    assert model.render(model.parse(rendered)) == rendered


def test_crlf_is_read_and_written_back_with_crlf_only() -> None:
    text = DOCUMENT.replace("\n", "\r\n")
    document = model.parse(text)
    assert document.newline == "\r\n"
    assert model.render(document) == text
    model.set_section(document, "status", "line one\nline two")
    rendered = model.render(document)
    assert "\r\n" in rendered
    assert "\n" not in rendered.replace("\r\n", "")
    assert "line one\r\nline two" in rendered


def test_a_file_without_the_marker_is_parsed_but_reported() -> None:
    text = DOCUMENT.replace(MARKER + "\n", "")
    document = model.parse(text)
    assert document.marker is False
    assert "missing_marker" in document.warnings
    assert model.render(document) == text


def test_a_duplicate_section_uses_the_first_one_and_keeps_both() -> None:
    text = DOCUMENT.replace(
        "## Done\n- [2026-11-07 claude] ilk iş\n",
        "## Done\n- [2026-11-07 claude] ilk iş\n\n## Done\n- ikinci kez yazılmış\n",
    )
    document = model.parse(text)
    assert model.section_text(document, "done") == "- [2026-11-07 claude] ilk iş"
    assert "duplicate_section" in document.warnings
    assert model.render(document) == text
    assert model.render(document).count("## Done") == 2


def test_an_empty_section_is_an_empty_string_and_renders_unchanged() -> None:
    text = "## Goal\n\n## Status\n"
    document = model.parse(text)
    assert model.section_text(document, "goal") == ""
    assert model.render(document) == text


def test_last_updated_is_parsed() -> None:
    document = model.parse(DOCUMENT)
    last = model.parse_last_updated(document)
    assert last is not None
    assert last.chief == "claude"
    assert last.at is not None and last.at.isoformat() == "2026-11-07T10:15:00+03:00"
    assert last.commit == "abc123"


def test_last_updated_is_replaced_not_appended() -> None:
    document = model.parse(DOCUMENT)
    model.set_last_updated(
        document, "agy", datetime.fromisoformat("2026-11-11T12:00+03:00"), "def456"
    )
    rendered = model.render(document)
    assert rendered.count("## Last updated") == 1
    assert "chief: agy | at: 2026-11-11T12:00+03:00 | commit: def456" in rendered


def test_items_are_appended_before_the_blank_line() -> None:
    document = model.parse(DOCUMENT)
    model.add_item(document, "done", "[2026-11-11 agy] yeni iş")
    assert model.section_text(document, "done").splitlines() == [
        "- [2026-11-07 claude] ilk iş",
        "- [2026-11-11 agy] yeni iş",
    ]
