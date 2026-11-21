"""Key management and OS credential store (keyring) service (Faz 11c-d, Mimari §11, D-122).

Provides access to API keys and secrets stored securely in the operating system's
credential store (Windows Credential Locker, macOS Keychain, Linux SecretService)
with precedence: os.environ > keyring.

Secrets are never written to config files, git repositories, or API responses.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import keyring
import keyring.errors

from orkestra.config import provider_entry
from orkestra.config.schema import Config
from orkestra.errors import KeyringUnavailable, UsageError
from orkestra.i18n import t

SERVICE_NAME = "orkestra"


@dataclass(frozen=True)
class KeyStatus:
    """Safe metadata for an environment variable key without exposing secret content."""

    var_name: str
    source: str  # "env" | "keyring" | "none"
    defined: bool
    providers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "var_name": self.var_name,
            "source": self.source,
            "defined": self.defined,
            "providers": list(self.providers),
        }


def get_key(var_name: str, environ: Mapping[str, str] | None = None) -> str | None:
    """Retrieve secret value with precedence: environ > keyring.

    Returns None if the key is not defined in either source or if the keyring is unavailable.
    """
    env = os.environ if environ is None else environ
    val = env.get(var_name, "").strip()
    if val:
        return val

    try:
        raw = keyring.get_password(SERVICE_NAME, var_name)
        if raw:
            return raw.strip() or None
    except keyring.errors.KeyringError:
        return None
    return None


def set_key(var_name: str, value: str) -> None:
    """Save an API key to the OS credential store."""
    clean_name = var_name.strip()
    if not clean_name or not provider_entry.valid_key_env(clean_name):
        raise UsageError(t("keys.error.invalid_name", name=var_name))

    clean_val = value.strip()
    if not clean_val:
        raise UsageError(t("keys.error.empty_value"))

    try:
        keyring.set_password(SERVICE_NAME, clean_name, clean_val)
    except keyring.errors.KeyringError as exc:
        raise KeyringUnavailable(t("keys.error.keyring_unavailable", err=str(exc))) from exc


def delete_key(var_name: str) -> None:
    """Remove an API key from the OS credential store."""
    clean_name = var_name.strip()
    if not clean_name:
        return

    try:
        keyring.delete_password(SERVICE_NAME, clean_name)
    except keyring.errors.PasswordDeleteError:
        pass
    except keyring.errors.KeyringError as exc:
        raise KeyringUnavailable(t("keys.error.keyring_unavailable", err=str(exc))) from exc


def keys_status(config: Config, environ: Mapping[str, str] | None = None) -> list[KeyStatus]:
    """Inspect all environment variable names referenced by providers and notifications.

    Returns safe status objects indicating definition status and source without secret values.
    """
    mapping: dict[str, list[str]] = {}
    for name, p in config.providers.items():
        env_var = getattr(p, "api_key_env", None)
        if env_var:
            mapping.setdefault(env_var, []).append(name)

    if config.notify and config.notify.ntfy_topic_env:
        mapping.setdefault(config.notify.ntfy_topic_env, []).append("notify")

    env = os.environ if environ is None else environ
    statuses: list[KeyStatus] = []

    for var_name in sorted(mapping.keys()):
        in_env = bool(env.get(var_name, "").strip())
        in_keyring = False
        if not in_env:
            try:
                pw = keyring.get_password(SERVICE_NAME, var_name)
                in_keyring = bool(pw and pw.strip())
            except keyring.errors.KeyringError:
                in_keyring = False

        source = "env" if in_env else ("keyring" if in_keyring else "none")
        defined = in_env or in_keyring
        statuses.append(
            KeyStatus(
                var_name=var_name,
                source=source,
                defined=defined,
                providers=tuple(sorted(mapping[var_name])),
            )
        )

    return statuses
