"""Unit tests for chief review (parsing, schema validation, diff context extraction)."""

from __future__ import annotations

import pytest

from orkestra.chief import review


def test_parse_review_json_valid() -> None:
    raw = """\
```json
{
  "risk": "medium",
  "flags": [
    {
      "file": "src/api.py",
      "start_line": 20,
      "end_line": 25,
      "reason": "Missing auth check",
      "severity": "medium"
    }
  ],
  "summary": "Auth check was omitted."
}
```
"""
    parsed = review.parse_review_response(raw)
    assert parsed.risk == "medium"
    assert len(parsed.flags) == 1
    assert parsed.flags[0].file == "src/api.py"
    assert parsed.flags[0].start_line == 20
    assert parsed.flags[0].severity == "medium"


def test_parse_review_json_invalid_raises_format_error() -> None:
    raw = "Not json at all"
    with pytest.raises(review.ReviewFormatError):
        review.parse_review_response(raw)

    raw_missing_risk = '{"flags": [], "summary": "ok"}'
    with pytest.raises(review.ReviewFormatError):
        review.parse_review_response(raw_missing_risk)


def test_extract_flagged_diff_context() -> None:
    patch = """\
diff --git a/src/calc.py b/src/calc.py
--- a/src/calc.py
+++ b/src/calc.py
@@ -1,20 +1,21 @@
 # line 1
 # line 2
 # line 3
 # line 4
 # line 5
 # line 6
 # line 7
 # line 8
 # line 9
 # line 10
-def old():
+def new():
+    eval(user_input)
 # line 12
 # line 13
 # line 14
 # line 15
 # line 16
 # line 17
 # line 18
 # line 19
 # line 20
"""
    flags = [
        review.ReviewFlag(
            file="src/calc.py",
            start_line=11,
            end_line=12,
            reason="eval is dangerous",
            severity="high",
        )
    ]
    extracted = review.extract_flagged_lines(patch, flags, context_lines=5)
    assert "eval(user_input)" in extracted
    # Lines around 11-12 with +-5 context: lines 6 through 17
    assert "line 6" in extracted or "line 7" in extracted
    # Far lines outside 5 lines of context must not appear
    assert "line 1\n" not in extracted
    assert "line 20\n" not in extracted
