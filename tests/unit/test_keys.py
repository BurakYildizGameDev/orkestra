"""Tests for keys and OS credential store (keyring) integration (Faz 11c-d, Mimari §11, D-122).

Verifies precedence (os.environ > keyring), validation, safe error handling,
isolation (secrets never exposed in status/API/logs), and provider/doctor/redact integration.
"""

from __future__ import annotations

from pathlib import Path

import keyring
import keyring.backend
import keyring.errors
import pytest

from orkestra.chief import keys
from orkestra.config import loader
from orkestra.config.schema import Config, ModelSpec, OpenAICompatProvider
from orkestra.errors import KeyringUnavailable, UsageError
from orkestra.providers.openai_compat import read_api_key
from orkestra.security import redact


class DummyKeyring(keyring.backend.KeyringBackend):
    """In-memory keyring backend for isolated unit testing."""

    @property
    def priority(self) -> float:
        return 1.0

    def __init__(self) -> None:
        self._passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) in self._passwords:
            del self._passwords[(service, username)]
        else:
            raise keyring.errors.PasswordDeleteError("Password not found")


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> DummyKeyring:
    dummy = DummyKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: dummy)
    monkeypatch.setattr(keyring, "get_password", dummy.get_password)
    monkeypatch.setattr(keyring, "set_password", dummy.set_password)
    monkeypatch.setattr(keyring, "delete_password", dummy.delete_password)
    return dummy


SAMPLE_CONFIG = """\
version: 1
language: en
providers:
  remote1:
    type: openai_compat
    base_url: https://api.one.test/v1
    api_key_env: OPENROUTER_API_KEY
    models:
      - id: model-1
        tier: 1
  remote2:
    type: openai_compat
    base_url: https://api.two.test/v1
    api_key_env: OPENROUTER_API_KEY
    models:
      - id: model-2
        tier: 2
  remote3:
    type: openai_compat
    base_url: https://api.three.test/v1
    api_key_env: CUSTOM_KEY
    models:
      - id: model-3
        tier: 3
  local:
    type: ollama
    base_url: http://localhost:11434
    models:
      - id: local-model
        tier: 1
"""


def _load_sample_config() -> Config:
    parsed = loader.read_yaml_text(Path("sample.yaml"), SAMPLE_CONFIG)
    return Config.model_validate(parsed)


def test_get_key_prefers_environ(fake_keyring: DummyKeyring) -> None:
    fake_keyring.set_password("orkestra", "TEST_KEY", "from_keyring")
    environ = {"TEST_KEY": "from_env"}
    assert keys.get_key("TEST_KEY", environ=environ) == "from_env"


def test_get_key_falls_back_to_keyring(fake_keyring: DummyKeyring) -> None:
    fake_keyring.set_password("orkestra", "TEST_KEY", "from_keyring")
    environ: dict[str, str] = {}
    assert keys.get_key("TEST_KEY", environ=environ) == "from_keyring"

    # Also falls back when environ has empty string
    assert keys.get_key("TEST_KEY", environ={"TEST_KEY": "   "}) == "from_keyring"


def test_get_key_returns_none_if_absent_in_both(fake_keyring: DummyKeyring) -> None:
    assert keys.get_key("ABSENT_KEY", environ={}) is None


def test_set_key_stores_in_keyring(fake_keyring: DummyKeyring) -> None:
    keys.set_key("OPENROUTER_API_KEY", "sk-secret-token")
    assert fake_keyring.get_password("orkestra", "OPENROUTER_API_KEY") == "sk-secret-token"


def test_set_key_validates_var_name() -> None:
    with pytest.raises(UsageError):
        keys.set_key("invalid-name-with-dashes!", "val")
    with pytest.raises(UsageError):
        keys.set_key("", "val")


def test_set_key_validates_empty_value() -> None:
    with pytest.raises(UsageError):
        keys.set_key("VALID_VAR", "   ")


def test_delete_key_removes_from_keyring(fake_keyring: DummyKeyring) -> None:
    fake_keyring.set_password("orkestra", "FOO_KEY", "secret")
    keys.delete_key("FOO_KEY")
    assert fake_keyring.get_password("orkestra", "FOO_KEY") is None

    # Deleting non-existent key does not raise
    keys.delete_key("FOO_KEY")


def test_keyring_error_raises_keyring_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_set(service: str, username: str, password: str) -> None:
        raise keyring.errors.KeyringError("Backend broken")

    monkeypatch.setattr(keyring, "set_password", failing_set)
    with pytest.raises(KeyringUnavailable):
        keys.set_key("FOO_KEY", "secret")


def test_keys_status_collects_providers_and_sources(fake_keyring: DummyKeyring) -> None:
    cfg = _load_sample_config()
    fake_keyring.set_password("orkestra", "CUSTOM_KEY", "keyring-val")
    environ = {"OPENROUTER_API_KEY": "env-val"}

    statuses = keys.keys_status(cfg, environ=environ)
    assert len(statuses) == 2

    s_openrouter = next(s for s in statuses if s.var_name == "OPENROUTER_API_KEY")
    assert s_openrouter.source == "env"
    assert s_openrouter.defined is True
    assert sorted(s_openrouter.providers) == ["remote1", "remote2"]

    s_custom = next(s for s in statuses if s.var_name == "CUSTOM_KEY")
    assert s_custom.source == "keyring"
    assert s_custom.defined is True
    assert s_custom.providers == ("remote3",)


def test_keys_status_never_exposes_secret_value(fake_keyring: DummyKeyring) -> None:
    cfg = _load_sample_config()
    secret_token = "ultra-secret-test-value-12345"
    fake_keyring.set_password("orkestra", "CUSTOM_KEY", secret_token)

    statuses = keys.keys_status(cfg, environ={})
    for s in statuses:
        d = s.as_dict()
        repr_str = repr(s)
        dict_str = str(d)
        assert secret_token not in repr_str
        assert secret_token not in dict_str
        assert "value" not in d
        assert "secret" not in d
        assert "key" not in d


def test_read_api_key_uses_keyring_integration(fake_keyring: DummyKeyring) -> None:
    fake_keyring.set_password("orkestra", "TEST_KEY", "keyring-token")
    provider = OpenAICompatProvider(
        type="openai_compat",
        base_url="https://api.test/v1",
        api_key_env="TEST_KEY",
        models=[ModelSpec(id="model-test", tier=1)],
    )
    # When environ has no key, read_api_key falls back to keyring
    assert read_api_key(provider, environ={}) == "keyring-token"


def test_redact_masks_keyring_secret(fake_keyring: DummyKeyring) -> None:
    secret = "sk-keyring-secret-999"
    fake_keyring.set_password("orkestra", "OPENROUTER_API_KEY", secret)
    cfg = _load_sample_config()

    secrets = redact.configured_secrets(cfg, environ={})
    assert secret in secrets
    redactor = redact.Redactor(secrets=secrets)
    redacted = redactor(f"Request failed with {secret} inside")
    assert secret not in redacted
    assert redact.MASK in redacted
