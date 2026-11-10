"""Find credentials in context before it leaves the machine (Mimari §11).

``block`` findings keep the context away from remote (``local: false``) providers.
``warn`` findings (e.g. ``password = …``) are only reported. Findings never contain the value.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

Severity = Literal["block", "warn"]

PATTERNS: tuple[tuple[str, Severity, re.Pattern[str]], ...] = (
    ("openrouter_key", "block", re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}")),
    # Not inside a word: "task-runner-…", "disk-usage-…" are not keys (D-037).
    ("openai_style_key", "block", re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}")),
    ("aws_access_key", "block", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "private_key",
        "block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    (
        "github_token",
        "block",
        re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,}"),
    ),
    ("slack_token", "block", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", "block", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("password", "warn", re.compile(r"(?i)password\s*[:=]\s*\S+")),
)

MIN_SECRET_LENGTH = 8  # shorter environment values would match too much text


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    severity: Severity


def scan_text(path: str, text: str, known_secrets: Iterable[str] = ()) -> list[Finding]:
    """Patterns plus the literal values of configured API key variables."""
    secrets = [s for s in known_secrets if len(s) >= MIN_SECRET_LENGTH]
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        matched_block = False
        for value in secrets:
            if value in line:
                findings.append(Finding(path, number, "configured_api_key", "block"))
                matched_block = True
                break
        for kind, severity, pattern in PATTERNS:
            if severity == "block" and matched_block:
                continue
            if pattern.search(line):
                findings.append(Finding(path, number, kind, severity))
                if severity == "block":
                    matched_block = True
    return findings


def blocking(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "block"]
