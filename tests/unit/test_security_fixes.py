"""Secret scanning and redaction fixes from the Faz 3 code review (PR #4)."""

from __future__ import annotations

import pytest

from orkestra.security.redact import MASK, Redactor
from orkestra.security.secrets_scan import scan_text


@pytest.mark.parametrize(
    "line",
    [
        "see task-runner-configuration-file",
        "disk-usage-monitoring-script-v2",
        "risk-assessment-matrix-2026",
    ],
)
def test_kebab_case_words_are_not_openai_keys(line: str) -> None:
    assert scan_text("f", line) == []
    assert Redactor()(line) == line


def test_real_openai_style_key_still_found() -> None:
    line = 'key = "sk-proj-abcdefghijklmnopqrstuvwxyz012345"'
    assert [f.kind for f in scan_text("f", line)] == ["openai_style_key"]


def test_output_redactor_keeps_password_examples() -> None:
    redact = Redactor(passwords=False)
    assert redact('{"dsn": "password=x"}') == '{"dsn": "password=x"}'
    assert redact("AKIAABCDEFGHIJKLMNOP") == MASK
