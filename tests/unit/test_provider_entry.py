"""Adding any OpenAI-compatible provider, by hand or from OpenCode's config (Faz 13o)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from orkestra.config import provider_entry as entry
from orkestra.config.schema import Config, OpenAICompatProvider
from orkestra.errors import ConfigError, UsageError

FAKE_KEY = "sk-FAKE-opencode-key-never-copied-0000000000000000"

USER_FILE = """\
# my notes
version: 1

providers:
  ollama:
    type: ollama          # the box under my desk
    models:
      - id: qwen2.5-coder:14b
        tier: 1
"""


def _api(name: str = "evren", **kwargs: object) -> entry.ApiProvider:
    values: dict[str, object] = {
        "name": name,
        "base_url": "https://llm.example.test/v1",
        "api_key_env": "EVREN_API_KEY",
        "models": ("deepseek-v4.1-flash", "glm-5.3"),
    }
    values.update(kwargs)
    return entry.ApiProvider(**values)  # type: ignore[arg-type]


def _chat(config: Config, name: str = "evren") -> OpenAICompatProvider:
    cfg = config.providers[name]
    assert isinstance(cfg, OpenAICompatProvider)
    return cfg


def _user_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_bytes(USER_FILE.encode("utf-8"))
    return path


# --- add -----------------------------------------------------------------------------------


def test_add_writes_a_generic_openai_compatible_entry(tmp_path: Path) -> None:
    path = _user_file(tmp_path)
    result = entry.add(path, _api(context_window=64000))
    cfg = _chat(result.config, "evren")
    assert cfg.type == "openai_compat"
    assert cfg.base_url == "https://llm.example.test/v1"
    assert cfg.api_key_env == "EVREN_API_KEY"
    assert [(m.id, m.tier, m.context_window) for m in cfg.models] == [
        ("deepseek-v4.1-flash", 2, 64000),
        ("glm-5.3", 2, 64000),
    ]
    assert result.backup is not None and result.backup.read_text(encoding="utf-8") == USER_FILE


def test_add_keeps_comments_and_the_existing_indentation(tmp_path: Path) -> None:
    path = _user_file(tmp_path)
    entry.add(path, _api())
    text = path.read_text(encoding="utf-8")
    assert text.startswith(USER_FILE)  # nothing above the new entry moved or changed
    assert "# the box under my desk" in text


def test_add_without_a_context_window_uses_the_schema_default(tmp_path: Path) -> None:
    result = entry.add(_user_file(tmp_path), _api())
    assert "context_window" not in (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert _chat(result.config, "evren").models[0].context_window == 8192


def test_a_keyless_server_has_no_key_variable(tmp_path: Path) -> None:
    result = entry.add(_user_file(tmp_path), _api("lmstudio", api_key_env=None))
    assert _chat(result.config, "lmstudio").api_key_env is None


def test_an_existing_name_is_refused_unless_forced(tmp_path: Path) -> None:
    path = _user_file(tmp_path)
    entry.add(path, _api())
    with pytest.raises(UsageError):
        entry.add(path, _api(models=("other",)))
    result = entry.add(path, _api(models=("other",)), force=True)
    assert [m.id for m in _chat(result.config, "evren").models] == ["other"]


def test_an_invalid_name_is_a_config_error_and_nothing_is_written(tmp_path: Path) -> None:
    path = _user_file(tmp_path)
    with pytest.raises(ConfigError):
        entry.add(path, _api("Not Valid"))
    assert path.read_text(encoding="utf-8") == USER_FILE


def test_a_model_is_required(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        entry.add(_user_file(tmp_path), _api(models=()))


def test_a_base_url_must_be_http(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        entry.add(_user_file(tmp_path), _api(base_url="ftp://llm.example.test"))


def test_add_creates_a_missing_config_file(tmp_path: Path) -> None:
    path = tmp_path / "new" / "config.yaml"
    result = entry.add(path, _api())
    assert result.backup is None
    assert set(result.config.providers) == {"evren"}


def test_a_project_file_is_validated_with_the_base_config(tmp_path: Path) -> None:
    base = _user_file(tmp_path)
    project = tmp_path / "orkestra.yaml"
    result = entry.add(project, _api(), base=base)
    assert set(result.config.providers) == {"ollama", "evren"}
    assert "ollama" not in project.read_text(encoding="utf-8")


# --- remove --------------------------------------------------------------------------------


def test_remove_deletes_only_that_entry(tmp_path: Path) -> None:
    path = _user_file(tmp_path)
    entry.add(path, _api())
    result = entry.remove(path, "evren")
    assert set(result.config.providers) == {"ollama"}
    assert path.read_text(encoding="utf-8") == USER_FILE


def test_removing_a_provider_that_is_not_in_the_file_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        entry.remove(_user_file(tmp_path), "evren")


# --- names ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "variable"),
    [("evren", "EVREN_API_KEY"), ("my-api", "MY_API_API_KEY"), ("x_1", "X_1_API_KEY")],
)
def test_the_suggested_key_variable(name: str, variable: str) -> None:
    assert entry.suggest_key_env(name) == variable


# --- OpenCode ------------------------------------------------------------------------------


def _opencode(tmp_path: Path, providers: Mapping[str, object]) -> Path:
    path = tmp_path / "opencode.json"
    data = {"$schema": "https://opencode.ai/config.json", "provider": dict(providers)}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


OPENCODE = {
    "evren": {
        "npm": "@ai-sdk/openai-compatible",
        "name": "EVREN API",
        "options": {"baseURL": "https://llm.example.test/v1", "apiKey": FAKE_KEY},
        "models": {"deepseek-v4.1-flash": {"name": "DeepSeek"}, "glm-5.3": {"name": "GLM"}},
    },
    "lab": {
        "npm": "@ai-sdk/openai-compatible",
        "options": {"baseURL": "http://localhost:1234/v1", "apiKey": "{env:LAB_TOKEN}"},
        "models": {"local-model": {}},
    },
    "claude": {"npm": "@ai-sdk/anthropic", "models": {"x": {}}},
}


def test_opencode_providers_are_read_without_keeping_a_plain_key(tmp_path: Path) -> None:
    found = {p.name: p for p in entry.read_opencode(_opencode(tmp_path, OPENCODE))}
    evren = found["evren"]
    assert evren.supported
    assert evren.base_url == "https://llm.example.test/v1"
    assert evren.models == ("deepseek-v4.1-flash", "glm-5.3")
    assert evren.key_env is None and evren.plain_key is True
    assert FAKE_KEY not in repr(evren)
    lab = found["lab"]
    assert lab.key_env == "LAB_TOKEN" and lab.plain_key is False
    assert found["claude"].supported is False


def test_an_opencode_provider_becomes_an_api_provider(tmp_path: Path) -> None:
    evren = next(p for p in entry.read_opencode(_opencode(tmp_path, OPENCODE)) if p.name == "evren")
    api = entry.from_opencode(evren)
    assert api.api_key_env == "EVREN_API_KEY"  # suggested: the plain key is never copied
    assert api.models == ("deepseek-v4.1-flash", "glm-5.3")
    lab = next(p for p in entry.read_opencode(_opencode(tmp_path, OPENCODE)) if p.name == "lab")
    assert entry.from_opencode(lab).api_key_env == "LAB_TOKEN"
    assert entry.from_opencode(lab, api_key_env="OTHER").api_key_env == "OTHER"


def test_the_plain_key_never_reaches_the_orkestra_config(tmp_path: Path) -> None:
    evren = next(p for p in entry.read_opencode(_opencode(tmp_path, OPENCODE)) if p.name == "evren")
    path = _user_file(tmp_path)
    entry.add(path, entry.from_opencode(evren))
    assert FAKE_KEY not in path.read_text(encoding="utf-8")


def test_comment_lines_in_opencode_jsonc_are_allowed(tmp_path: Path) -> None:
    path = tmp_path / "opencode.jsonc"
    path.write_text(
        '{\n  // my providers\n  "provider": {"lab": {"npm": "@ai-sdk/openai-compatible",'
        ' "options": {"baseURL": "http://localhost:1234/v1"}, "models": {"m": {}}}}\n}\n',
        encoding="utf-8",
    )
    assert [p.name for p in entry.read_opencode(path)] == ["lab"]


def test_a_broken_opencode_file_is_a_config_error_without_its_content(tmp_path: Path) -> None:
    path = tmp_path / "opencode.json"
    path.write_text('{"provider": {"apiKey": "' + FAKE_KEY + '",', encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        entry.read_opencode(path)
    assert FAKE_KEY not in str(info.value)


def test_a_missing_opencode_file_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        entry.read_opencode(tmp_path / "nope.json")


def test_the_opencode_path_follows_its_environment_variable(tmp_path: Path) -> None:
    custom = tmp_path / "elsewhere.json"
    assert entry.opencode_path({"OPENCODE_CONFIG": str(custom)}, home=tmp_path) == custom
    assert entry.opencode_path({}, home=tmp_path) == (
        tmp_path / ".config" / "opencode" / "opencode.json"
    )
    jsonc = tmp_path / ".config" / "opencode" / "opencode.jsonc"
    jsonc.parent.mkdir(parents=True)
    jsonc.write_text("{}", encoding="utf-8")
    assert entry.opencode_path({}, home=tmp_path) == jsonc
    xdg = tmp_path / "xdg"
    assert entry.opencode_path({"XDG_CONFIG_HOME": str(xdg)}, home=tmp_path) == (
        xdg / "opencode" / "opencode.json"
    )
