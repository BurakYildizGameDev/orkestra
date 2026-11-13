"""Writing the config safely: round trip, validation, backup, atomic (Faz 11a, Mimari §22)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.config import loader, writer
from orkestra.errors import ConfigError
from orkestra.i18n import t

USER_FILE = """\
# my own notes at the top
version: 1
language: tr   # I read Turkish

providers:
  local:
    type: ollama          # the small box under my desk
    models:
      - id: qwen2.5-coder:7b
        tier: 1
    budget: {}
"""


def test_the_example_config_round_trips_byte_for_byte() -> None:
    document = writer.template_document()
    assert writer.render(document) == loader.example_config_text()


def test_a_user_file_round_trips_byte_for_byte(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(USER_FILE.encode("utf-8"))
    assert writer.render(writer.load_document(path)) == USER_FILE


def test_a_change_keeps_every_comment(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(USER_FILE.encode("utf-8"))
    document = writer.load_document(path)
    document["providers"]["local"]["budget"]["daily_requests"] = 100
    writer.save(path, document)
    text = path.read_text(encoding="utf-8")
    assert "# my own notes at the top" in text
    assert "# I read Turkish" in text
    assert "# the small box under my desk" in text
    assert "daily_requests: 100" in text


def test_an_invalid_value_is_not_saved_and_the_error_is_translated(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(USER_FILE.encode("utf-8"))
    document = writer.load_document(path)
    document["providers"]["local"]["budget"]["daily_requests"] = -5
    with pytest.raises(ConfigError) as exc_info:
        writer.save(path, document)
    assert exc_info.value.message == t("config.error.invalid", sources=path)
    assert any("daily_requests" in detail for detail in exc_info.value.details)
    assert path.read_bytes() == USER_FILE.encode("utf-8")
    assert not writer.backup_path(path).exists()
    assert list(tmp_path.iterdir()) == [path]  # no temporary file left behind


def test_saving_over_a_file_keeps_the_previous_version_as_bak(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(USER_FILE.encode("utf-8"))
    document = writer.load_document(path)
    document["language"] = "en"
    result = writer.save(path, document)
    backup = tmp_path / "config.yaml.bak"
    assert result.backup == backup
    assert backup.read_bytes() == USER_FILE.encode("utf-8")
    document["language"] = "auto"
    writer.save(path, document)
    assert "language: en" in backup.read_text(encoding="utf-8")  # one rolling backup


def test_a_new_file_has_no_backup(tmp_path: Path) -> None:
    path = tmp_path / "new" / "config.yaml"
    result = writer.save(path, writer.template_document())
    assert result.backup is None
    assert path.read_text(encoding="utf-8") == loader.example_config_text()
    assert result.config.version == 1


def test_a_crlf_file_stays_crlf(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(USER_FILE.replace("\n", "\r\n").encode("utf-8"))
    document = writer.load_document(path)
    document["language"] = "en"
    writer.save(path, document)
    raw = path.read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n")
    assert b"language: en" in raw


def test_a_project_file_is_validated_together_with_the_base_config(tmp_path: Path) -> None:
    """A project file only overrides; alone it may miss what the base config provides."""
    base = tmp_path / "config.yaml"
    base.write_bytes(USER_FILE.encode("utf-8"))
    project = tmp_path / "orkestra.yaml"
    document = writer.load_document(project)  # missing file: empty document
    document["providers"] = {"local": {"budget": {"daily_requests": 10}}}
    result = writer.save(project, document, base=base)
    assert result.config.providers["local"].budget.daily_requests == 10
    document["providers"]["local"]["budget"]["daily_requests"] = -1
    with pytest.raises(ConfigError):
        writer.save(project, document, base=base)


def test_a_file_that_is_not_a_mapping_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info:
        writer.load_document(path)
    assert exc_info.value.message == t("config.error.not_mapping", path=path)
