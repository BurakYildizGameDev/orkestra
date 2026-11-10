"""SEARCH/REPLACE edits from API workers (Faz 9c, Mimari §8.2).

The worker sends only the places it changes; the rest of the file is never rewritten, so a
small model cannot drop lines it did not mean to touch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.tasks import edit_format as ef


def _block(path: str, search: str, replace: str) -> str:
    return f"{path}\n<<<<<<< SEARCH\n{search}=======\n{replace}>>>>>>> REPLACE\n"


def _keys(exc: pytest.ExceptionInfo[ef.EditFormatError]) -> str:
    return exc.value.problem.key


# --- parse -----------------------------------------------------------------------------


def test_one_block() -> None:
    answer = ef.parse_replace(_block("src/a.py", "x = 1\n", "x = 2\n"))
    assert answer.blocks == (ef.ReplaceBlock("src/a.py", "x = 1\n", "x = 2\n", 1),)


def test_several_blocks_fences_and_prose() -> None:
    text = (
        "I changed two places.\n\n```python\n"
        + _block("a.py", "one\n", "ONE\n")
        + "```\n\nAnd the other file:\n```\n"
        + _block("b/c.py", "two\nthree\n", "")
        + "```\n"
    )
    answer = ef.parse_replace(text)
    assert [(b.path, b.search, b.replace) for b in answer.blocks] == [
        ("a.py", "one\n", "ONE\n"),
        ("b/c.py", "two\nthree\n", ""),
    ]
    assert "I changed two places." in answer.note


def test_a_block_without_a_path_line_reuses_the_previous_path() -> None:
    text = _block("a.py", "one\n", "ONE\n") + "<<<<<<< SEARCH\ntwo\n=======\nTWO\n>>>>>>> REPLACE\n"
    assert [b.path for b in ef.parse_replace(text).blocks] == ["a.py", "a.py"]


def test_a_path_in_backticks_or_bold() -> None:
    text = _block("`src/a.py`", "x\n", "y\n") + _block("**src/b.py**", "x\n", "y\n")
    assert [b.path for b in ef.parse_replace(text).blocks] == ["src/a.py", "src/b.py"]


def test_an_empty_search_is_a_new_file() -> None:
    answer = ef.parse_replace(_block("new.py", "", "print(1)\n"))
    assert answer.blocks[0].search == ""


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("Here is the whole file: x = 2", "edit.error.no_blocks"),
        ("<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE\n", "edit.error.block_no_path"),
        ("a.py\n<<<<<<< SEARCH\nx\n=======\ny\n", "edit.error.block_unterminated"),
        ("a.py\n<<<<<<< SEARCH\nx\n>>>>>>> REPLACE\n", "edit.error.block_unterminated"),
    ],
)
def test_broken_answers(text: str, key: str) -> None:
    with pytest.raises(ef.EditFormatError) as exc:
        ef.parse_replace(text)
    assert _keys(exc) == key


# --- resolve: blocks -> whole files ------------------------------------------------------


def _resolve(tmp_path: Path, text: str) -> dict[str, str]:
    answer = ef.resolve_replace(ef.parse_replace(text), tmp_path)
    return {f.path: f.content for f in answer.files}


def test_only_the_searched_lines_change(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"def f():\n    return 1\n\n\ndef g():\n    return 2\n")
    files = _resolve(tmp_path, _block("a.py", "    return 2\n", "    return 20\n"))
    assert files == {"a.py": "def f():\n    return 1\n\n\ndef g():\n    return 20\n"}


def test_blocks_of_one_file_apply_in_order(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"one\ntwo\nthree\n")
    text = _block("a.py", "one\n", "ONE\n") + _block("a.py", "three\n", "THREE\n")
    assert _resolve(tmp_path, text) == {"a.py": "ONE\ntwo\nTHREE\n"}


def test_a_search_matches_whole_lines_only(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"xx = 1\nx = 1\n")
    assert _resolve(tmp_path, _block("a.py", "x = 1\n", "x = 2\n")) == {"a.py": "xx = 1\nx = 2\n"}


def test_line_endings_and_trailing_spaces_are_tolerated(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"a = 1   \r\nb = 2\r\n")
    files = _resolve(tmp_path, _block("a.py", "a = 1\nb = 2\n", "a = 10\nb = 2\n"))
    assert files == {"a.py": "a = 10\nb = 2\n"}  # written back with CRLF by ``write``


def test_the_last_line_without_a_newline(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"a = 1\nb = 2")
    assert _resolve(tmp_path, _block("a.py", "b = 2\n", "b = 3\n")) == {"a.py": "a = 1\nb = 3"}


def test_a_new_file(tmp_path: Path) -> None:
    assert _resolve(tmp_path, _block("pkg/new.py", "", "x = 1\n")) == {"pkg/new.py": "x = 1\n"}


def test_deleting_lines(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"keep\ndrop\nkeep too\n")
    assert _resolve(tmp_path, _block("a.py", "drop\n", "")) == {"a.py": "keep\nkeep too\n"}


def test_a_bom_is_not_part_of_the_text(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(ef.BOM + b"x = 1\n")
    assert _resolve(tmp_path, _block("a.py", "x = 1\n", "x = 2\n")) == {"a.py": "x = 2\n"}


@pytest.mark.parametrize(
    ("files", "text", "key"),
    [
        ({"a.py": "x = 1\n"}, _block("a.py", "y = 1\n", "y = 2\n"), "edit.error.search_not_found"),
        ({"a.py": "x\nx\n"}, _block("a.py", "x\n", "y\n"), "edit.error.search_ambiguous"),
        ({"a.py": "x\n"}, _block("a.py", "", "y\n"), "edit.error.search_empty"),
        ({}, _block("gone.py", "x\n", "y\n"), "edit.error.missing_file"),
    ],
)
def test_blocks_that_do_not_fit(tmp_path: Path, files: dict[str, str], text: str, key: str) -> None:
    for name, content in files.items():
        (tmp_path / name).write_bytes(content.encode())
    with pytest.raises(ef.EditFormatError) as exc:
        ef.resolve_replace(ef.parse_replace(text), tmp_path)
    assert _keys(exc) == key


def test_not_found_shows_the_closest_lines(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"import os\n\n\ndef calculate(a, b):\n    return a + b\n")
    with pytest.raises(ef.EditFormatError) as exc:
        ef.resolve_replace(
            ef.parse_replace(_block("a.py", "def calculate(a,b):\n", "x\n")), tmp_path
        )
    feedback = exc.value.problem.english()
    assert "def calculate(a, b):" in feedback and "4" in feedback  # the line and its number


def test_one_bad_block_leaves_the_whole_file_alone(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"one\ntwo\n")
    text = _block("a.py", "one\n", "ONE\n") + _block("a.py", "nope\n", "x\n")
    with pytest.raises(ef.EditFormatError):
        ef.resolve_replace(ef.parse_replace(text), tmp_path)
    assert (tmp_path / "a.py").read_bytes() == b"one\ntwo\n"  # resolve never writes


def test_paths_only_lists_each_file_once() -> None:
    answer = ef.parse_replace(
        _block("a.py", "x\n", "y\n") + _block("a.py", "z\n", "w\n") + _block("b.py", "", "n\n")
    )
    assert [f.path for f in ef.paths_only(answer).files] == ["a.py", "b.py"]


def test_resolve_never_reads_outside_the_workdir(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_bytes(b"x\n")
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(Exception):  # noqa: B017 - paths are checked before; this is the guard
        ef.resolve_replace(ef.parse_replace(_block("../secret.txt", "x\n", "y\n")), work)


# --- choosing the format ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("task", "model", "lines", "expected"),
    [
        # auto (the default): whole files up to max_api_edit_lines, SEARCH/REPLACE above it.
        # Faz 9c manual runs: qwen2.5-coder:14b did better with whole files on a small file.
        (None, None, 120, "whole"),
        (None, None, 400, "whole"),
        (None, None, 401, "replace"),
        ("auto", "replace", 120, "whole"),  # an explicit auto in the task file wins too
        (None, "replace", 120, "replace"),
        (None, "whole", 5000, "whole"),
        ("whole", "replace", 120, "whole"),  # the task file wins over the model setting
        ("replace", None, 10, "replace"),
    ],
)
def test_resolving_the_format(
    task: str | None, model: str | None, lines: int, expected: str
) -> None:
    from orkestra.config.schema import resolve_edit_format

    assert resolve_edit_format(task, model, lines=lines, limit=400) == expected  # type: ignore[arg-type]


# --- prompts ---------------------------------------------------------------------------


def test_edit_feedback_says_the_files_are_back_to_the_original() -> None:
    # Faz 9c manual run: after "duplicated export" the model thought the file itself was
    # broken and gave up; the feedback must say the previous change was discarded.
    from orkestra.tasks.prompts import build_retry_message

    edit = build_retry_message("task", "answer", ["command: exit 1"], edit=True)
    assert "discarded" in edit and "exactly as shown" in edit
    ask = build_retry_message("task", "answer", ["regex: no match"])
    assert "discarded" not in ask


def test_the_replace_prompt_shows_how_to_add_lines_above_a_line() -> None:
    from orkestra.tasks.context import Context
    from orkestra.tasks.prompts import build_edit_messages

    _, user = build_edit_messages(
        "Add a comment.",
        Context(),
        editable=["a.py"],
        allow_new=False,
        protected=[],
        edit_format="replace",
    )
    assert "exactly once" in user and "above" in user


# --- code review fixes (PR #11) ----------------------------------------------------------


def test_a_divider_line_inside_the_file_content_is_content(tmp_path: Path) -> None:
    # A setext title underline or a conflict-marker sample looks like "=======".
    (tmp_path / "README.md").write_bytes(b"Title\n=======\n\nold text\n")
    text = _block("README.md", "Title\n=======\n\nold text\n", "Title\n=======\n\nnew text\n")
    assert _resolve(tmp_path, text) == {"README.md": "Title\n=======\n\nnew text\n"}


def test_a_divider_line_only_in_replace(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_bytes(b"Title\n\ntext\n")
    text = _block("README.md", "Title\n", "Title\n=======\n")
    assert _resolve(tmp_path, text) == {"README.md": "Title\n=======\n\ntext\n"}


@pytest.mark.parametrize(
    "header",
    ["### src/a.py", "File: src/a.py", "**File:** `src/a.py`", "src/a.py:", "# src/a.py"],
)
def test_common_path_headers(header: str) -> None:
    text = f"{header}\n<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE\n"
    assert ef.parse_replace(text).blocks[0].path == "src/a.py"


def test_a_known_path_with_spaces() -> None:
    text = _block("docs/user guide.md", "x\n", "y\n")
    assert ef.parse_replace(text, known=["docs/user guide.md"]).blocks[0].path == (
        "docs/user guide.md"
    )


def test_a_directory_or_an_unreadable_file_is_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    with pytest.raises(ef.EditFormatError) as exc:
        ef.resolve_replace(ef.parse_replace(_block("src/pkg", "x\n", "y\n")), tmp_path)
    assert _keys(exc) == "edit.error.not_a_file"
    (tmp_path / "a.py").write_bytes(b"x\n")

    def locked(self: Path) -> bytes:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_bytes", locked)
    with pytest.raises(ef.EditFormatError) as exc:
        ef.resolve_replace(ef.parse_replace(_block("a.py", "x\n", "y\n")), tmp_path)
    assert _keys(exc) == "edit.error.cannot_read"


def test_the_prompt_builder_needs_an_explicit_format() -> None:
    from orkestra.tasks.context import Context
    from orkestra.tasks.prompts import build_edit_messages

    with pytest.raises(TypeError):
        build_edit_messages(  # type: ignore[call-arg]
            "p", Context(), editable=["a.py"], allow_new=False, protected=[]
        )
