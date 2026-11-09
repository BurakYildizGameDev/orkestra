"""Mask secrets in everything Orkestra writes to its records and logs (Mimari §11, §14).

Masked: the values of every ``api_key_env`` variable in the config, and anything matching the
secret scan patterns.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable, Mapping
from typing import Any

from orkestra.config.schema import Config, OpenAICompatProvider
from orkestra.security.secrets_scan import MIN_SECRET_LENGTH, PATTERNS

MASK = "***"
_PASSWORD_VALUE = re.compile(r"(?i)(password\s*[:=]\s*)\S+")
# Header names whose values are credentials (Authorization, x-api-key, X-Auth-Token, Cookie…).
_SECRET_HEADER = re.compile(r"(?i)auth|key|token|secret|cookie|session|password")


def configured_secrets(config: Config, environ: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    values: list[str] = []
    for provider in config.providers.values():
        if isinstance(provider, OpenAICompatProvider) and provider.api_key_env:
            value = env.get(provider.api_key_env, "").strip()
            if len(value) >= MIN_SECRET_LENGTH:
                values.append(value)
    return values


def config_for_display(config: Config) -> dict[str, Any]:
    """The config as JSON data for ``config show``, with header credentials masked.

    ``extra_headers`` may hold tokens (``Authorization: Bearer …``); values of headers with a
    credential-like name, and any value that looks like a key, become ``***``.
    """
    data = config.model_dump(mode="json")
    redact = Redactor()
    for provider in data.get("providers", {}).values():
        headers = provider.get("extra_headers")
        if not isinstance(headers, dict):
            continue
        for name, value in headers.items():
            masked = MASK if _SECRET_HEADER.search(name) else redact(str(value))
            headers[name] = masked
    return data


class Redactor:
    """Masks configured key values, key-like patterns and (``passwords``) ``password=…``.

    ``passwords=False`` is for a worker's answer: an example ``password: changeme`` in it is
    content, and masking it would corrupt the answer (and JSON in it).
    """

    def __init__(self, secrets: Iterable[str] = (), *, passwords: bool = True) -> None:
        # Longest first so a key that contains another key is masked whole.
        self._secrets = sorted(
            {s for s in secrets if len(s) >= MIN_SECRET_LENGTH}, key=len, reverse=True
        )
        self._passwords = passwords

    def __call__(self, text: str) -> str:
        for value in self._secrets:
            text = text.replace(value, MASK)
        for _, severity, pattern in PATTERNS:
            if severity == "block":
                text = pattern.sub(MASK, text)
        return _PASSWORD_VALUE.sub(rf"\g<1>{MASK}", text) if self._passwords else text


class RedactFilter(logging.Filter):
    """Masks every log record before any handler writes it."""

    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self._redact = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(record.getMessage())
        record.args = None
        return True
