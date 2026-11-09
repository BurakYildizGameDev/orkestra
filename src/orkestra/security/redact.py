"""Mask secrets in everything Orkestra writes to its records and logs (Mimari §11, §14).

Masked: the values of every ``api_key_env`` variable in the config, and anything matching the
secret scan patterns.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable, Mapping

from orkestra.config.schema import Config, OpenAICompatProvider
from orkestra.security.secrets_scan import MIN_SECRET_LENGTH, PATTERNS

MASK = "***"
_PASSWORD_VALUE = re.compile(r"(?i)(password\s*[:=]\s*)\S+")


def configured_secrets(config: Config, environ: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    values: list[str] = []
    for provider in config.providers.values():
        if isinstance(provider, OpenAICompatProvider) and provider.api_key_env:
            value = env.get(provider.api_key_env, "").strip()
            if len(value) >= MIN_SECRET_LENGTH:
                values.append(value)
    return values


class Redactor:
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        # Longest first so a key that contains another key is masked whole.
        self._secrets = sorted(
            {s for s in secrets if len(s) >= MIN_SECRET_LENGTH}, key=len, reverse=True
        )

    def __call__(self, text: str) -> str:
        for value in self._secrets:
            text = text.replace(value, MASK)
        for _, severity, pattern in PATTERNS:
            if severity == "block":
                text = pattern.sub(MASK, text)
        return _PASSWORD_VALUE.sub(rf"\g<1>{MASK}", text)


class RedactFilter(logging.Filter):
    """Masks every log record before any handler writes it."""

    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self._redact = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(record.getMessage())
        record.args = None
        return True
