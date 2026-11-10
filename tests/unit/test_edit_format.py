"""The full-file edit format of API workers (Mimari §8.2, Faz 5c)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from orkestra import i18n
from orkestra.errors import InternalError
from orkestra.tasks import edit_format as ef

ANSWER = {"files": [{"path": "src/app.py", "content": "x = 2\n"}], "note": "set x to 2"}


def _english(problems: list[ef.Message]) -> str:
    return "; ".join(p.english() for p in problems)


# --- parse -----------------------------------------------------------------------------


def test_plain_json() -> None:
    answer = ef.parse(json.dumps(ANSWER))
    assert answer.files == (ef.FileEdit("src/app.py", "x = 2\n"),)
    assert answer.note == "set x to 2"


def test_note_is_optional_and_extra_keys_are_ignored() -> None:
    answer = ef.parse(json.dumps({"files": [], "summary": "?"}))
    assert answer.files == () and answer.note == ""


def test_fenced_json_with_prose_around_it() -> None:
    text = f"Here is the change:\n```json\n{json.dumps(ANSWER, indent=2)}\n```\nDone."
    assert ef.parse(text).files[0].path == "src/app.py"


def test_first_balanced_object_with_files_is_taken() -> None:
    # Braces in prose and inside the file content must not confuse the parser.
    content = "def f():\n    return {'a': '}'}\n"
    payload = {"files": [{"path": "a.py", "content": content}]}
    text = "I used {braces} here. " + json.dumps(payload) + ' and {"files": []}'
    assert ef.parse(text).files == (ef.FileEdit("a.py", content),)


@pytest.mark.parametrize(
    "text",
    [
        '{"files": [{"path": "a.py", "content": "x = 1\n}]}',  # raw newline, unclosed string
        '{"files": [{"path": "a.py", content: "x"}]}',  # unquoted key
        "",
        "no json here at all",
    ],
)
def test_broken_json_is_an_error_with_english_feedback(text: str) -> None:
    with pytest.raises(ef.EditFormatError) as exc_info:
        ef.parse(text)
    assert "JSON" in exc_info.value.problem.english()


def test_truncated_json_is_an_error() -> None:
    full = json.dumps({"files": [{"path": "a.py", "content": "x = 1\n" * 50}]})
    with pytest.raises(ef.EditFormatError):
        ef.parse(full[: len(full) // 2])


@pytest.mark.parametrize(
    "payload",
    [
        {"files": "a.py"},
        {"files": [{"path": "a.py"}]},
        {"files": [{"path": "a.py", "content": 3}]},
        {"files": [{"path": 1, "content": ""}]},
        {"files": [["a.py", ""]]},
        {"edits": []},
    ],
)
def test_wrong_shape_is_an_error(payload: object) -> None:
    with pytest.raises(ef.EditFormatError):
        ef.parse(json.dumps(payload))


def test_the_same_path_twice_is_an_error() -> None:
    payload = {"files": [{"path": "a.py", "content": "1"}, {"path": "./a.py", "content": "2"}]}
    with pytest.raises(ef.EditFormatError) as exc_info:
        ef.parse(json.dumps(payload))
    assert "a.py" in exc_info.value.problem.english()


def test_messages_are_translated_for_the_user() -> None:
    i18n.set_language("tr")
    with pytest.raises(ef.EditFormatError) as exc_info:
        ef.parse("nope")
    assert exc_info.value.problem.user() != exc_info.value.problem.english()


# --- paths -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("src/app.py", "src/app.py"),
        ("./src/app.py", "src/app.py"),
        ("src\\app.py", "src/app.py"),
        ("src//app.py", "src/app.py"),
    ],
)
def test_paths_are_normalized(raw: str, expected: str) -> None:
    assert ef.normalize_path(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "../outside.txt",
        "src/../../outside.txt",
        "/etc/passwd",
        "\\Windows\\x.txt",
        "C:\\x.txt",
        "C:x.txt",
        "\\\\server\\share\\x.txt",
        ".git/config",
        "src/.git/hooks/pre-commit",
        "",
        ".",
        "a/\x00b",
    ],
)
def test_unsafe_paths_are_rejected(raw: str) -> None:
    assert ef.normalize_path(raw) is None


def _workdir(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    (work / "src" / "app.py").write_bytes(b"x = 1\n")
    (work / "README.md").write_bytes(b"# readme\n")
    return work


def _check(
    work: Path,
    *files: tuple[str, str],
    editable: frozenset[str] = frozenset({"src/app.py"}),
    allow_new: bool = True,
    forbidden: tuple[str, ...] = (".env",),
) -> list[ef.Message]:
    answer = ef.EditAnswer(tuple(ef.FileEdit(p, c) for p, c in files))
    return ef.check_paths(answer, work, editable=editable, allow_new=allow_new, forbidden=forbidden)


def test_context_files_and_new_files_are_allowed(tmp_path: Path) -> None:
    work = _workdir(tmp_path)
    assert _check(work, ("src/app.py", "x = 2\n"), ("src/new.py", "y = 1\n")) == []


def test_escaping_paths_are_reported(tmp_path: Path) -> None:
    work = _workdir(tmp_path)
    problems = _check(work, ("../outside.txt", "x"), ("/abs.txt", "x"))
    text = _english(problems)
    assert "../outside.txt" in text and "/abs.txt" in text


def test_an_existing_file_outside_the_context_is_rejected(tmp_path: Path) -> None:
    work = _workdir(tmp_path)
    problems = _check(work, ("README.md", "overwritten\n"))
    assert "README.md" in _english(problems)


def test_new_files_can_be_turned_off(tmp_path: Path) -> None:
    work = _workdir(tmp_path)
    assert _check(work, ("src/new.py", "y\n"), allow_new=False) != []


def test_forbidden_paths_are_rejected_before_writing(tmp_path: Path) -> None:
    work = _workdir(tmp_path)
    problems = _check(work, (".env", "KEY=x\n"), forbidden=(".env", "secrets/**"))
    assert ".env" in _english(problems)


def test_a_symlink_out_of_the_workdir_is_rejected(tmp_path: Path) -> None:
    work = _workdir(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, work / "link", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need extra rights on this system")
    assert _check(work, ("link/x.txt", "x")) != []


# --- write -----------------------------------------------------------------------------


def test_write_keeps_crlf_of_the_original(tmp_path: Path) -> None:
    work = _workdir(tmp_path)
    (work / "win.txt").write_bytes(b"one\r\ntwo\r\n")
    ef.write(ef.EditAnswer((ef.FileEdit("win.txt", "one\nTWO\n"),)), work)
    assert (work / "win.txt").read_bytes() == b"one\r\nTWO\r\n"


def test_write_keeps_lf_of_the_original(tmp_path: Path) -> None:
    work = _workdir(tmp_path)
    ef.write(ef.EditAnswer((ef.FileEdit("src/app.py", "x = 2\r\ny = 3\r\n"),)), work)
    assert (work / "src" / "app.py").read_bytes() == b"x = 2\ny = 3\n"


def test_write_keeps_a_utf8_bom(tmp_path: Path) -> None:
    work = _workdir(tmp_path)
    (work / "bom.txt").write_bytes(b"\xef\xbb\xbfold\n")
    ef.write(ef.EditAnswer((ef.FileEdit("bom.txt", "new\n"),)), work)
    assert (work / "bom.txt").read_bytes() == b"\xef\xbb\xbfnew\n"


def test_write_creates_new_files_and_directories(tmp_path: Path) -> None:
    work = _workdir(tmp_path)
    ef.write(ef.EditAnswer((ef.FileEdit("pkg/sub/mod.py", "ç = 1\n"),)), work)
    assert (work / "pkg" / "sub" / "mod.py").read_bytes() == "ç = 1\n".encode()


def test_write_refuses_an_unsafe_path(tmp_path: Path) -> None:
    work = _workdir(tmp_path)
    with pytest.raises(InternalError):
        ef.write(ef.EditAnswer((ef.FileEdit("../outside.txt", "x"),)), work)
    assert not (tmp_path / "outside.txt").exists()


# --- code review fixes (PR #8) -----------------------------------------------------------


def test_cannot_do_in_json() -> None:
    assert ef.cannot_do('{"cannot_do": "needs the schema"}') == "needs the schema"
    assert ef.cannot_do('```json\n{"CANNOT_DO": "no"}\n```') == "no"
    assert ef.cannot_do(json.dumps(ANSWER)) is None
    assert ef.cannot_do("plain text") is None


def test_protected_and_ignored_paths_are_rejected(tmp_path: Path) -> None:
    work = _workdir(tmp_path)
    answer = ef.EditAnswer((ef.FileEdit("tests/t.py", "x"), ef.FileEdit("build/x.py", "y")))
    problems = ef.check_paths(
        answer, work, editable=frozenset(), allow_new=True, forbidden=(),
        protected=("tests/**",), ignored={"build/x.py"},
    )  # fmt: skip
    keys = [p.key for p in problems]
    assert keys == ["edit.error.protected", "edit.error.ignored"]


def test_write_reports_a_path_that_cannot_be_created(tmp_path: Path) -> None:
    work = _workdir(tmp_path)
    with pytest.raises(ef.EditFormatError) as exc_info:
        ef.write(ef.EditAnswer((ef.FileEdit("src/app.py/x.py", "x"),)), work)
    assert "src/app.py/x.py" in exc_info.value.problem.english()
