from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from orkestra import i18n
from orkestra.config import loader
from orkestra.config.loader import ConfigSource, load_config, merge_dicts, read_yaml
from orkestra.config.schema import OllamaProvider
from orkestra.errors import ConfigError, ExitCode


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """ORKESTRA_HOME from conftest; global config lives here."""
    return tmp_path / "orkestra-home"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    return root


GLOBAL = """\
version: 1
defaults:
  timeout_s: 100
  max_retries: 3
providers:
  ollama:
    type: ollama
    models:
      - id: big
        tier: 1
      - id: small
        tier: 1
    budget:
      daily_tokens: 1000
      daily_requests: 50
  openrouter:
    type: openai_compat
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    models:
      - id: provider/model
        tier: 2
  codex:
    type: cli_agent
    command: codex
estimate:
  confirm_above_usd: 0.5
"""

PROJECT = """\
defaults:
  timeout_s: 200
providers:
  ollama:
    models:
      - id: only
        tier: 1
    budget:
      daily_tokens: 5000
  codex: null
estimate:
  confirm_above_usd: null
"""


# --- merge rules -----------------------------------------------------------------------


def test_merge_deep_merges_dicts() -> None:
    base = {"a": {"x": 1, "y": {"p": 1, "q": 2}}, "b": 1}
    override = {"a": {"y": {"q": 3}, "z": 4}}
    assert merge_dicts(base, override) == {"a": {"x": 1, "y": {"p": 1, "q": 3}, "z": 4}, "b": 1}


def test_merge_replaces_lists() -> None:
    assert merge_dicts({"l": [1, 2, 3]}, {"l": [9]}) == {"l": [9]}


def test_merge_null_removes_provider() -> None:
    base = {"providers": {"a": {"type": "ollama"}, "b": {"type": "ollama"}}}
    assert merge_dicts(base, {"providers": {"a": None}}) == {"providers": {"b": {"type": "ollama"}}}


def test_merge_null_removing_unknown_provider_is_noop() -> None:
    assert merge_dicts({"providers": {}}, {"providers": {"x": None}}) == {"providers": {}}


def test_merge_null_elsewhere_is_a_value() -> None:
    base = {"estimate": {"confirm_above_usd": 0.5}, "providers": {"c": {"model": "m"}}}
    override = {"estimate": {"confirm_above_usd": None}, "providers": {"c": {"model": None}}}
    assert merge_dicts(base, override) == {
        "estimate": {"confirm_above_usd": None},
        "providers": {"c": {"model": None}},
    }


def test_merge_does_not_mutate_inputs() -> None:
    base: dict[str, Any] = {"a": {"l": [1]}, "providers": {"x": {"k": 1}}}
    override: dict[str, Any] = {"a": {"m": 2}, "providers": {"x": None}}
    base_copy, override_copy = copy.deepcopy(base), copy.deepcopy(override)
    result = merge_dicts(base, override)
    result["a"]["l"].append(2)
    assert base == base_copy
    assert override == override_copy


# --- reading YAML ----------------------------------------------------------------------


def test_empty_yaml_is_empty_dict(tmp_path: Path) -> None:
    assert read_yaml(_write(tmp_path / "e.yaml", "")) == {}
    assert read_yaml(_write(tmp_path / "c.yaml", "# only a comment\n")) == {}


def test_yaml_error_shows_line_number(tmp_path: Path) -> None:
    path = _write(tmp_path / "bad.yaml", "version: 1\ndefaults:\n  profile: [unclosed\n")
    with pytest.raises(ConfigError) as exc_info:
        read_yaml(path)
    assert exc_info.value.exit_code == ExitCode.USAGE
    assert "line 4" in exc_info.value.message  # where the parser noticed it (end of file)
    assert "starts on line 3" in exc_info.value.message  # where the unclosed "[" is
    assert str(path) in exc_info.value.message


def test_yaml_error_translated(tmp_path: Path) -> None:
    i18n.set_language("tr")
    path = _write(tmp_path / "bad.yaml", "a: 1\na: 2\n")  # duplicate key
    with pytest.raises(ConfigError) as exc_info:
        read_yaml(path)
    assert "satır 2" in exc_info.value.message


def test_top_level_must_be_mapping(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        read_yaml(_write(tmp_path / "l.yaml", "- a\n- b\n"))
    assert "mapping" in exc_info.value.message


# --- finding config files --------------------------------------------------------------


def test_no_files_gives_builtin_defaults(tmp_path: Path) -> None:
    loaded = load_config(cwd=tmp_path, environ={})
    assert loaded.sources == ()
    assert loaded.config.version == 1
    assert loaded.config.providers == {}


def test_global_config_used(home: Path, tmp_path: Path) -> None:
    _write(home / "config.yaml", GLOBAL)
    loaded = load_config(cwd=tmp_path, environ={})
    assert loaded.sources == (ConfigSource(home / "config.yaml", "global"),)
    assert set(loaded.config.providers) == {"ollama", "openrouter", "codex"}


def test_env_beats_global(home: Path, tmp_path: Path) -> None:
    _write(home / "config.yaml", GLOBAL)
    env_file = _write(tmp_path / "env.yaml", "version: 1\n")
    loaded = load_config(cwd=tmp_path, environ={"ORKESTRA_CONFIG": str(env_file)})
    assert loaded.sources == (ConfigSource(env_file, "env"),)
    assert loaded.config.providers == {}


def test_flag_beats_env(tmp_path: Path) -> None:
    env_file = _write(tmp_path / "env.yaml", GLOBAL)
    flag_file = _write(tmp_path / "flag.yaml", "version: 1\n")
    loaded = load_config(
        config_flag=flag_file, cwd=tmp_path, environ={"ORKESTRA_CONFIG": str(env_file)}
    )
    assert loaded.sources == (ConfigSource(flag_file, "flag"),)


def test_missing_flag_file_is_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_config(config_flag=tmp_path / "nope.yaml", cwd=tmp_path, environ={})
    assert exc_info.value.exit_code == ExitCode.USAGE
    assert "nope.yaml" in exc_info.value.message


def test_missing_env_file_is_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(cwd=tmp_path, environ={"ORKESTRA_CONFIG": str(tmp_path / "nope.yaml")})


def test_project_config_in_cwd(repo: Path) -> None:
    project = _write(repo / "orkestra.yaml", "version: 1\n")
    loaded = load_config(cwd=repo, environ={})
    assert loaded.sources == (ConfigSource(project, "project"),)


def test_project_config_found_up_to_git_root(repo: Path) -> None:
    project = _write(repo / "orkestra.yaml", "version: 1\n")
    sub = repo / "src" / "pkg"
    sub.mkdir(parents=True)
    loaded = load_config(cwd=sub, environ={})
    assert loaded.sources == (ConfigSource(project, "project"),)


def test_project_config_nearest_wins(repo: Path) -> None:
    _write(repo / "orkestra.yaml", "version: 1\n")
    nearer = _write(repo / "sub" / "orkestra.yaml", "version: 1\n")
    loaded = load_config(cwd=repo / "sub", environ={})
    assert loaded.sources == (ConfigSource(nearer, "project"),)


def test_project_config_not_searched_above_git_root(tmp_path: Path, repo: Path) -> None:
    _write(tmp_path / "orkestra.yaml", "version: 1\n")  # outside the repo
    loaded = load_config(cwd=repo, environ={})
    assert loaded.sources == ()


def test_outside_git_only_cwd_is_checked(tmp_path: Path) -> None:
    _write(tmp_path / "orkestra.yaml", "version: 1\n")
    sub = tmp_path / "plain" / "dir"
    sub.mkdir(parents=True)
    assert load_config(cwd=sub, environ={}).sources == ()
    assert len(load_config(cwd=tmp_path, environ={}).sources) == 1


def test_git_file_marks_root(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    _write(root / ".git", "gitdir: elsewhere\n")  # worktrees use a .git file
    project = _write(root / "orkestra.yaml", "version: 1\n")
    (root / "a").mkdir()
    assert load_config(cwd=root / "a", environ={}).sources == (ConfigSource(project, "project"),)


def test_same_file_as_global_and_project_loaded_once(repo: Path) -> None:
    project = _write(repo / "orkestra.yaml", "version: 1\n")
    loaded = load_config(config_flag=project, cwd=repo, environ={})
    assert loaded.sources == (ConfigSource(project, "flag"),)


# --- project overrides global ----------------------------------------------------------


def test_project_overrides_global(home: Path, repo: Path) -> None:
    _write(home / "config.yaml", GLOBAL)
    _write(repo / "orkestra.yaml", PROJECT)
    loaded = load_config(cwd=repo, environ={})
    cfg = loaded.config
    assert [s.kind for s in loaded.sources] == ["global", "project"]
    # scalar override, sibling kept (dict merge)
    assert cfg.defaults.timeout_s == 200
    assert cfg.defaults.max_retries == 3
    # list replaced, not appended
    ollama = cfg.providers["ollama"]
    assert isinstance(ollama, OllamaProvider)
    assert [m.id for m in ollama.models] == ["only"]
    # nested dict merged
    assert ollama.budget.daily_tokens == 5000
    assert ollama.budget.daily_requests == 50
    # provider removed with null
    assert "codex" not in cfg.providers
    assert "openrouter" in cfg.providers
    # null as a value elsewhere
    assert cfg.estimate.confirm_above_usd is None


def test_project_file_without_version_on_top_of_global(home: Path, repo: Path) -> None:
    _write(home / "config.yaml", "version: 1\n")
    _write(repo / "orkestra.yaml", "")
    assert load_config(cwd=repo, environ={}).config.version == 1


def test_validation_error_is_config_error(home: Path, tmp_path: Path) -> None:
    _write(
        home / "config.yaml",
        "version: 1\nproviders:\n  x:\n    type: ollama\n    models: [{id: m, tier: 7}]\n",
    )
    with pytest.raises(ConfigError) as exc_info:
        load_config(cwd=tmp_path, environ={})
    err = exc_info.value
    assert err.exit_code == ExitCode.USAGE
    assert str(home / "config.yaml") in err.message
    assert err.details == ("providers.x.models[0].tier: must be 1, 2 or 3",)


# --- language peek ---------------------------------------------------------------------


def test_read_language(home: Path, tmp_path: Path) -> None:
    _write(home / "config.yaml", "version: 1\nlanguage: tr\n")
    assert loader.read_language(cwd=tmp_path, environ={}) == "tr"


def test_read_language_ignores_broken_config(home: Path, tmp_path: Path) -> None:
    _write(home / "config.yaml", "version: [\n")
    assert loader.read_language(cwd=tmp_path, environ={}) is None


def test_read_language_missing(tmp_path: Path) -> None:
    assert loader.read_language(cwd=tmp_path, environ={}) is None


# --- code review fixes (Faz 1, PR #2) ---------------------------------------------------


def test_merge_null_removes_provider_without_base_providers() -> None:
    merged = merge_dicts({}, {"providers": {"agy": None, "local": {"type": "ollama"}}})
    assert merged == {"providers": {"local": {"type": "ollama"}}}


def test_merge_null_in_only_source_is_dropped(tmp_path: Path) -> None:
    project = _write(
        tmp_path / "orkestra.yaml",
        "version: 1\nproviders:\n  agy: null\n  local:\n    type: ollama\n"
        "    models: [{id: m, tier: 1}]\n",
    )
    loaded = load_config(config_flag=project, cwd=tmp_path, environ={})
    assert list(loaded.config.providers) == ["local"]


def test_config_flag_expands_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _write(tmp_path / "my.yaml", "version: 1\nlanguage: tr\n")
    loaded = load_config(config_flag=Path("~/my.yaml"), cwd=tmp_path, environ={})
    assert loaded.config.language == "tr"


def test_read_language_survives_os_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: Any, **__: Any) -> Any:
        raise PermissionError("denied")

    monkeypatch.setattr(loader, "find_sources", broken)
    assert loader.read_language() is None


def test_read_yaml_is_cached_until_file_changes(tmp_path: Path) -> None:
    path = _write(tmp_path / "c.yaml", "version: 1\n")
    first = read_yaml(path)
    first["mutated"] = True  # callers get their own copy
    assert read_yaml(path) == {"version": 1}
    _write(path, "version: 1\nlanguage: tr\n")
    assert read_yaml(path) == {"version": 1, "language": "tr"}


def test_unmapped_validation_error_is_translated(home: Path, tmp_path: Path) -> None:
    i18n.set_language("tr")
    _write(home / "config.yaml", "version: 1\nchiefs:\n  x:\n    launch: []\n")
    with pytest.raises(ConfigError) as exc_info:
        load_config(cwd=tmp_path, environ={})
    assert exc_info.value.details == ("chiefs.x.launch: en az 1 öğe olmalı",)


def test_init_force_twice_keeps_the_original_backup(tmp_path: Path) -> None:
    target = _write(tmp_path / "config.yaml", "version: 1\n# mine\n")
    first = loader.init_config(target, force=True, cwd=tmp_path)
    assert first.backup == tmp_path / "config.yaml.bak"
    target.write_text("version: 1\n# edited again\n", encoding="utf-8")
    second = loader.init_config(target, force=True, cwd=tmp_path)
    assert second.backup == tmp_path / "config.yaml.bak.1"
    assert (tmp_path / "config.yaml.bak").read_text(encoding="utf-8") == "version: 1\n# mine\n"
    edited = (tmp_path / "config.yaml.bak.1").read_text(encoding="utf-8")
    assert edited == "version: 1\n# edited again\n"


def test_init_force_on_untouched_example_makes_no_backup(tmp_path: Path) -> None:
    target = tmp_path / "config.yaml"
    loader.init_config(target, cwd=tmp_path)
    result = loader.init_config(target, force=True, cwd=tmp_path)
    assert result.written and result.backup is None
    assert not (tmp_path / "config.yaml.bak").exists()


def test_gitignore_that_is_not_utf8_is_kept_byte_for_byte(repo: Path) -> None:
    original = b"# T\xfcrk\xe7e yorum\nnode_modules/\n"
    (repo / ".gitignore").write_bytes(original)
    loader.init_config(repo / "orkestra.yaml", project=True, cwd=repo)
    assert (repo / ".gitignore").read_bytes() == original + b".orkestra/cache/\n"


def test_global_init_does_not_touch_the_cwd_repository(repo: Path, tmp_path: Path) -> None:
    loader.init_config(tmp_path / "home" / "config.yaml", cwd=repo)
    assert not (repo / ".gitignore").exists()
