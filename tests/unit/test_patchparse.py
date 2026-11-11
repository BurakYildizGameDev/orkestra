"""Unified diff parsing for review and ``show --only-flagged`` (Faz 8b review, D-062)."""

from __future__ import annotations

from orkestra.chief import patchparse

TWO_FILES = """\
diff --git a/src/a.py b/src/a.py
index 1111111..2222222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,2 +1,2 @@
 keep
-old
+new
diff --git a/src/b.py b/src/b.py
index 3333333..4444444 100644
--- a/src/b.py
+++ b/src/b.py
@@ -1 +1,2 @@
 one
+two
"""


def test_each_file_is_one_block_that_starts_with_its_own_header() -> None:
    files = patchparse.parse_patch(TWO_FILES)
    assert [f.path for f in files] == ["src/a.py", "src/b.py"]
    assert files[0].text.startswith("diff --git a/src/a.py b/src/a.py\n")
    assert "+++ b/src/a.py\n" in files[0].text
    assert files[1].text.startswith("diff --git a/src/b.py b/src/b.py\n")
    assert "".join(f.text for f in files) == TWO_FILES


def test_a_removed_line_that_starts_with_two_dashes_does_not_split_the_hunk() -> None:
    """``-- comment`` removed from SQL/Lua is ``--- comment`` in the diff: still hunk body."""
    patch = """\
diff --git a/db/schema.sql b/db/schema.sql
--- a/db/schema.sql
+++ b/db/schema.sql
@@ -1,3 +1,2 @@
 CREATE TABLE t (id INT);
--- old comment
+++ new comment
 SELECT 1;
"""
    files = patchparse.parse_patch(patch)
    assert len(files) == 1
    assert files[0].path == "db/schema.sql"
    assert len(files[0].hunks) == 1
    assert "--- old comment\n" in files[0].hunks[0].lines


def test_a_patch_without_git_headers_is_split_on_its_file_headers() -> None:
    patch = """\
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-x
+y
--- a/src/b.py
+++ b/src/b.py
@@ -1 +1 @@
-p
+q
"""
    files = patchparse.parse_patch(patch)
    assert [f.path for f in files] == ["src/a.py", "src/b.py"]


def test_paths_with_spaces_quotes_and_deletions_are_read_from_the_headers() -> None:
    patch = (
        "diff --git a/my notes.md b/my notes.md\n"
        "--- a/my notes.md\t\n"
        "+++ b/my notes.md\t\n"
        "@@ -1 +1 @@\n-a\n+b\n"
        'diff --git "a/\\303\\247ay.txt" "b/\\303\\247ay.txt"\n'
        '--- "a/\\303\\247ay.txt"\n'
        '+++ "b/\\303\\247ay.txt"\n'
        "@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/gone.txt b/gone.txt\n"
        "deleted file mode 100644\n"
        "--- a/gone.txt\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n-q\n"
        "diff --git a/img one.png b/img one.png\n"
        "Binary files a/img one.png and b/img one.png differ\n"
    )
    files = patchparse.parse_patch(patch)
    assert [f.path for f in files] == ["my notes.md", "çay.txt", "gone.txt", "img one.png"]


def test_hunk_lines_keep_new_file_line_numbers() -> None:
    files = patchparse.parse_patch(TWO_FILES)
    hunk = files[1].hunks[0]
    assert hunk.new_start == 1
    assert list(patchparse.numbered(hunk)) == [(1, " one\n"), (2, "+two\n")]


def test_no_newline_marker_stays_in_its_hunk() -> None:
    patch = (
        "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n"
        "@@ -1 +1 @@\n-a\n\\ No newline at end of file\n+b\n\\ No newline at end of file\n"
    )
    files = patchparse.parse_patch(patch)
    assert len(files) == 1
    assert files[0].text == patch
