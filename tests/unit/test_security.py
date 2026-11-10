from __future__ import annotations

import logging
from pathlib import Path

import pytest

from orkestra.config.schema import Config
from orkestra.logging_setup import run_log
from orkestra.security.redact import MASK, Redactor, configured_secrets
from orkestra.security.secrets_scan import blocking, scan_text

FAKE_ENV_KEY = "fake-router-key-value-0123456789"


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ("key = sk-or-v1-" + "a" * 40, "openrouter_key"),
        ("OPENAI_API_KEY=sk-" + "B" * 30, "openai_style_key"),
        ("aws AKIA" + "ABCDEFGHIJKLMNOP", "aws_access_key"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private_key"),
        ("-----BEGIN PRIVATE KEY-----", "private_key"),
        ("token ghp_" + "x" * 36, "github_token"),
        ("xoxb-1234567890-abcdef", "slack_token"),
        ("AIza" + "y" * 35, "google_api_key"),
    ],
)
def test_block_patterns(line: str, kind: str) -> None:
    findings = scan_text("cfg.env", f"first line\n{line}\n")
    assert [(f.kind, f.line, f.severity) for f in findings] == [(kind, 2, "block")]


def test_password_is_warning_only() -> None:
    findings = scan_text("settings.py", "PASSWORD = 'hunter2'\n")
    assert [(f.kind, f.severity) for f in findings] == [("password", "warn")]
    assert blocking(findings) == []


def test_configured_key_value_is_found() -> None:
    findings = scan_text("notes.md", f"my key is {FAKE_ENV_KEY}", [FAKE_ENV_KEY, "short"])
    assert [(f.kind, f.severity) for f in findings] == [("configured_api_key", "block")]


def test_clean_text_has_no_findings() -> None:
    assert scan_text("a.py", "def f():\n    return 'sky-is-blue'\n") == []


def test_findings_never_hold_the_value() -> None:
    finding = scan_text("a", "sk-" + "z" * 30)[0]
    assert "zzz" not in repr(finding)


def test_redactor_masks_env_values_patterns_and_passwords() -> None:
    redact = Redactor([FAKE_ENV_KEY, "tiny"])
    text = f"auth {FAKE_ENV_KEY}\nother sk-or-v1-{'c' * 40}\npassword: hunter2\ntiny words stay\n"
    out = redact(text)
    assert FAKE_ENV_KEY not in out
    assert "c" * 40 not in out
    assert "hunter2" not in out
    assert "password: ***" in out
    assert "tiny words stay" in out  # values shorter than 8 chars are not masked
    assert out.count(MASK) == 3


def test_configured_secrets_reads_env_values() -> None:
    config = Config.model_validate(
        {
            "version": 1,
            "providers": {
                "router": {
                    "type": "openai_compat",
                    "base_url": "https://r.test",
                    "api_key_env": "ROUTER_KEY",
                    "models": [{"id": "m", "tier": 2}],
                },
                "local": {"type": "ollama", "models": [{"id": "m", "tier": 1}]},
            },
        }
    )
    assert configured_secrets(config, {"ROUTER_KEY": FAKE_ENV_KEY}) == [FAKE_ENV_KEY]
    assert configured_secrets(config, {}) == []


def test_run_log_is_redacted(tmp_path: Path) -> None:
    with run_log(tmp_path, Redactor([FAKE_ENV_KEY])) as log:
        log.warning("provider said: invalid key %s", FAKE_ENV_KEY)
        log.info("plain message")
    text = (tmp_path / "orkestra.log").read_text(encoding="utf-8")
    assert FAKE_ENV_KEY not in text
    assert "invalid key ***" in text
    assert "plain message" in text
    assert not logging.getLogger("orkestra").handlers  # handler removed afterwards
