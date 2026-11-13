"""Single-value config edits for the terminal interface (Faz 11b, Mimari §22)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.config import edits, loader
from orkestra.errors import ConfigError
from orkestra.i18n import t

BASE = """\
# my global config
version: 1
language: en   # keep it English
providers:
  local:
    type: ollama          # the box under my desk
    models:
      - id: qwen2.5-coder:7b
        tier: 1
    budget:
      daily_requests: 100   # be gentle
  codex:
    type: cli_agent
    command: codex
"""

PROJECT = """\
version: 1
providers:
  codex:
    budget:
      daily_runs: 3   # this project is small
"""


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "home" / "config.yaml"
    path.parent.mkdir()
    path.write_bytes(BASE.encode("utf-8"))
    return path


def test_turning_a_provider_off_keeps_every_comment(base: Path, tmp_path: Path) -> None:
    result = edits.set_value(("providers", "local", "enabled"), False, config_flag=base,
                             cwd=tmp_path)  # fmt: skip
    assert result.path == base
    assert result.config.providers["local"].enabled is False
    text = base.read_text(encoding="utf-8")
    for comment in ("# my global config", "# keep it English", "# the box under my desk",
                    "# be gentle"):  # fmt: skip
        assert comment in text


def test_a_budget_limit_is_set_and_none_removes_it(base: Path, tmp_path: Path) -> None:
    path = ("providers", "local", "budget", "daily_requests")
    assert (
        edits.set_value(path, 50, config_flag=base, cwd=tmp_path)
        .config.providers["local"]
        .budget.daily_requests
        == 50
    )
    result = edits.set_value(path, None, config_flag=base, cwd=tmp_path)
    assert result.config.providers["local"].budget.daily_requests is None
    assert "daily_requests" not in base.read_text(encoding="utf-8")


def test_an_invalid_value_is_not_saved_and_says_why_in_the_chosen_language(
    base: Path, tmp_path: Path,
) -> None:  # fmt: skip
    from orkestra import i18n

    i18n.set_language("tr")
    before = base.read_bytes()
    with pytest.raises(ConfigError) as exc_info:
        edits.set_value(("providers", "local", "budget", "daily_requests"), -5,
                        config_flag=base, cwd=tmp_path)  # fmt: skip
    assert exc_info.value.message == i18n.t_in("tr", "config.error.invalid", sources=base)
    assert base.read_bytes() == before
    i18n.set_language("en")


def test_a_value_the_project_file_defines_is_changed_there(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    work = tmp_path / "work"
    work.mkdir()
    (work / ".git").mkdir()
    project = work / loader.PROJECT_CONFIG_NAME
    project.write_bytes(PROJECT.encode("utf-8"))
    monkeypatch.chdir(work)
    result = edits.set_value(("providers", "codex", "budget", "daily_runs"), 4,
                             config_flag=base, cwd=work)  # fmt: skip
    assert result.path == project
    assert result.config.providers["codex"].budget.daily_runs == 4
    assert "# this project is small" in project.read_text(encoding="utf-8")
    assert base.read_bytes() == BASE.encode("utf-8")


def test_a_new_key_goes_into_the_base_config(base: Path, tmp_path: Path) -> None:
    result = edits.set_value(("defaults", "profile"), "cheap", config_flag=base, cwd=tmp_path)
    assert result.path == base
    assert result.config.defaults.profile == "cheap"


def test_without_any_config_file_there_is_nothing_to_edit(tmp_path: Path) -> None:
    missing = tmp_path / "none" / "config.yaml"
    with pytest.raises(ConfigError) as exc_info:
        edits.set_value(("language",), "tr", config_flag=missing, cwd=tmp_path)
    assert exc_info.value.message == t("config.error.not_found", path=missing)


# --- code review of PR #22 ------------------------------------------------------------------


def test_clearing_a_limit_removes_it_where_it_is_defined(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """The project file names the provider, but the limit lives in the base config."""
    work = tmp_path / "work"
    work.mkdir()
    (work / ".git").mkdir()
    project = work / loader.PROJECT_CONFIG_NAME
    project.write_bytes(b"version: 1\nproviders:\n  local:\n    enabled: true\n")
    monkeypatch.chdir(work)
    result = edits.set_value(("providers", "local", "budget", "daily_requests"), None,
                             config_flag=base, cwd=work)  # fmt: skip
    assert result.config.providers["local"].budget.daily_requests is None
    assert "daily_requests" not in base.read_text(encoding="utf-8")
    assert project.read_bytes() == b"version: 1\nproviders:\n  local:\n    enabled: true\n"


def test_clearing_a_limit_that_is_not_set_writes_nothing(base: Path, tmp_path: Path) -> None:
    before = base.read_bytes()
    result = edits.set_value(("providers", "codex", "budget", "daily_runs"), None,
                             config_flag=base, cwd=tmp_path)  # fmt: skip
    assert result.config.providers["codex"].budget.daily_runs is None
    assert base.read_bytes() == before
    assert sorted(p.name for p in base.parent.iterdir()) == ["config.yaml"]  # no backup


def test_several_values_for_one_file_are_one_save(base: Path, tmp_path: Path) -> None:
    results = edits.set_values(
        [(("defaults", "profile"), "cheap"), (("defaults", "max_retries"), 1)],
        config_flag=base, cwd=tmp_path,
    )  # fmt: skip
    assert len(results) == 1
    assert results[0].config.defaults.profile == "cheap"
    assert results[0].config.defaults.max_retries == 1
    assert sorted(p.name for p in base.parent.iterdir()) == ["config.yaml", "config.yaml.bak"]
