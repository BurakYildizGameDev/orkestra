from __future__ import annotations

from pathlib import Path

import pytest

from orkestra import paths


def test_home_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "custom"))
    assert paths.orkestra_home() == tmp_path / "custom"


@pytest.mark.parametrize("value", ["", "   "])
def test_home_default_when_env_empty(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(paths.HOME_ENV, value)
    assert paths.orkestra_home() == Path.home() / ".orkestra"


def test_home_default_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(paths.HOME_ENV, raising=False)
    assert paths.orkestra_home() == Path.home() / ".orkestra"


def test_derived_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path))
    assert paths.global_config_path() == tmp_path / "config.yaml"
    assert paths.state_db_path() == tmp_path / "state.db"
    assert paths.runs_dir() == tmp_path / "runs"
    assert paths.run_dir("20261107-101500-a1b2") == tmp_path / "runs" / "20261107-101500-a1b2"
    assert paths.worktrees_dir() == tmp_path / "worktrees"


def test_paths_do_not_create_directories(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "not-yet"
    monkeypatch.setenv(paths.HOME_ENV, str(home))
    paths.state_db_path()
    paths.runs_dir()
    assert not home.exists()
