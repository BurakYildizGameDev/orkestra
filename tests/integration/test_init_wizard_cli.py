"""``orkestra init --defaults`` and ``init --plain`` end to end (Faz 11a)."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from orkestra import cli, paths
from orkestra.cli import app
from orkestra.config import loader
from orkestra.config.schema import OllamaProvider
from orkestra.i18n import t, t_in
from orkestra.tui import detect, wizard

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    return (
        (code if isinstance(code, int) else 0),
        _ANSI.sub("", captured.out),
        _ANSI.sub("", captured.err),
    )


def _found(*, models: tuple[str, ...] = (), agents: tuple[str, ...] = (),
           keys: tuple[str, ...] = ()) -> detect.Detection:  # fmt: skip
    return detect.Detection(
        ollama=detect.OllamaFound(detect.OLLAMA_URL, bool(models), models),
        agents=tuple(
            detect.AgentFound(name, f"/bin/{name}" if name in agents else None, None)
            for name in detect.AGENTS
        ),
        keys=tuple(detect.KeyFound(api, api.env in keys) for api in detect.KNOWN_APIS),
    )


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    monkeypatch.chdir(path)
    return path


def _detect_returns(monkeypatch: pytest.MonkeyPatch, found: detect.Detection) -> None:
    def fake(**kwargs: object) -> detect.Detection:
        return found

    monkeypatch.setattr(detect, "detect", fake)


def test_init_defaults_turns_on_what_was_found_without_consent(
    work: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _detect_returns(monkeypatch, _found(models=("qwen2.5-coder:14b",), agents=("codex",),
                                        keys=("OPENROUTER_API_KEY",)))  # fmt: skip
    code, out, err = _run(["init", "--defaults"], capsys)
    assert code == 0, err
    target = paths.orkestra_home() / "config.yaml"
    config = loader.load_config(target).config
    assert set(config.providers) == {"ollama", "codex"}
    assert t("wizard.note.key_needs_model", env="OPENROUTER_API_KEY") in out
    code, out, _ = _run(["providers", "list", "--json"], capsys)
    assert code == 0
    consent = {row["name"]: row["consent"] for row in json.loads(out)["providers"]}
    assert consent == {"ollama": "missing", "codex": "missing"}


def test_init_defaults_json_reports_what_it_wrote(
    work: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _detect_returns(monkeypatch, _found(agents=("codex",)))
    code, out, err = _run(["init", "--defaults", "--json"], capsys)
    assert code == 0, err
    document = json.loads(out)
    assert document["path"] == str(paths.orkestra_home() / "config.yaml")
    assert document["written"] is True
    assert document["backup"] is None
    assert document["providers"] == ["codex"]
    assert document["consent"] == []


def test_init_defaults_never_overwrites_without_force(
    work: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _detect_returns(monkeypatch, _found(agents=("codex",)))
    target = paths.orkestra_home() / "config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("version: 1\n# mine\n", encoding="utf-8")
    code, out, _ = _run(["init", "--defaults"], capsys)
    assert code == 0
    assert target.read_text(encoding="utf-8") == "version: 1\n# mine\n"
    assert t("init.exists", path=target) in out
    code, _, err = _run(["init", "--defaults", "--force"], capsys)
    assert code == 0, err
    assert (target.with_name("config.yaml.bak")).read_text(encoding="utf-8") == (
        "version: 1\n# mine\n"
    )
    assert "codex" in loader.load_config(target).config.providers


def test_plain_and_defaults_together_is_a_usage_error(
    work: Path, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    code, _, err = _run(["init", "--plain", "--defaults"], capsys)
    assert code == 2
    assert t("wizard.error.plain_and_defaults") in err


def test_plain_with_json_is_a_usage_error(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["init", "--plain", "--json"], capsys)
    assert code == 2
    assert json.loads(out)["error"]["message"] == t("wizard.error.plain_json")  # --json errors


def test_init_plain_writes_the_answers_and_grants_only_the_confirmed_consent(
    work: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _detect_returns(monkeypatch, _found(models=("small:1b",), agents=("codex",)))
    answers = [
        "en",   # language
        "",     # providers: detected default (ollama, codex)
        "",     # ollama models: all
        "",     # tier
        "7",    # codex daily runs
        "",     # chief
        "",     # project? no
        "y",    # consent ollama (asked after saving, for the saved entry)
        "n",    # consent codex
        "n",    # run doctor now? no
    ]  # fmt: skip
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(answers) + "\n"))
    code, out, err = _run(["init", "--plain"], capsys)
    assert code == 0, err
    target = paths.orkestra_home() / "config.yaml"
    config = loader.load_config(target).config
    assert config.providers["codex"].budget.daily_runs == 7
    ollama = config.providers["ollama"]
    assert isinstance(ollama, OllamaProvider)
    assert [m.id for m in ollama.models] == ["small:1b"]
    assert config.language == "en"
    code, out, _ = _run(["providers", "list", "--json"], capsys)
    consent = {row["name"]: row["consent"] for row in json.loads(out)["providers"]}
    assert consent == {"ollama": "granted", "codex": "missing"}


def test_init_plain_into_a_project_file_adds_the_gitignore_entry(
    work: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    (work / ".git").mkdir()
    _detect_returns(monkeypatch, _found(agents=("codex",)))
    number = str(wizard.candidate_names().index("codex") + 1)
    answers = ["en", number, "", "", "y", "n", "n"]  # runs, chief, project, consent, doctor
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(answers) + "\n"))
    code, _, err = _run(["init", "--plain"], capsys)
    assert code == 0, err
    assert (work / "orkestra.yaml").is_file()
    assert not (paths.orkestra_home() / "config.yaml").exists()
    assert loader.GITIGNORE_ENTRY in (work / ".gitignore").read_text(encoding="utf-8")


def test_init_plain_without_input_is_a_clear_error(
    work: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _detect_returns(monkeypatch, _found())
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    code, _, err = _run(["init", "--plain"], capsys)
    assert code == 2
    assert t("wizard.error.no_input") in err
    assert not (paths.orkestra_home() / "config.yaml").exists()


def test_a_turkish_user_answers_evet_and_hayir_and_sees_turkish_hints(
    work: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    """``typer.confirm`` only knows y/n and says "invalid input" in English."""
    _detect_returns(monkeypatch, _found(agents=("codex",)))
    number = str(wizard.candidate_names().index("codex") + 1)
    answers = ["tr", number, "", "", "h", "belki", "e", "hayır"]  # runs, chief, project, ...
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(answers) + "\n"))
    code, out, err = _run(["init", "--plain"], capsys)
    assert code == 0, err
    assert t_in("tr", "wizard.yes_no.default_no") in out
    assert t_in("tr", "wizard.error.yes_no") in out
    assert "invalid input" not in out + err
    consent = json.loads(_run(["providers", "list", "--json"], capsys)[1])["providers"]
    assert {row["name"]: row["consent"] for row in consent} == {"codex": "granted"}


# --- code review of PR #21 ------------------------------------------------------------------


def test_a_bare_init_at_a_terminal_never_edits_an_existing_file(
    work: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    """The help promises "never overwrites without --force"; editing is ``init --plain``."""
    monkeypatch.setattr(cli, "_at_terminal", lambda: True)
    target = paths.orkestra_home() / "config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("version: 1\n# mine\n", encoding="utf-8")
    code, out, _ = _run(["init"], capsys)
    assert code == 0
    assert target.read_text(encoding="utf-8") == "version: 1\n# mine\n"
    assert t("init.exists", path=target) in out
    assert t("wizard.hint.edit") in out


def test_a_bare_init_at_a_terminal_without_a_file_opens_the_wizard(
    work: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    monkeypatch.setattr(cli, "_at_terminal", lambda: True)
    _detect_returns(monkeypatch, _found(agents=("codex",)))
    number = str(wizard.candidate_names().index("codex") + 1)
    answers = ["tr", number, "", "", "h", "h", "h"]  # runs, chief, project, consent, doctor
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(answers) + "\n"))
    code, _, err = _run(["init"], capsys)
    assert code == 0, err
    assert loader.load_config(paths.orkestra_home() / "config.yaml").config.language == "tr"


def test_plain_with_force_starts_again_from_the_example_and_keeps_the_old_file(
    work: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _detect_returns(monkeypatch, _found(agents=("codex",)))
    target = paths.orkestra_home() / "config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("version: 1\nlanguage: tr   # mine\n", encoding="utf-8")
    number = str(wizard.candidate_names().index("codex") + 1)
    answers = ["en", number, "", "", "n", "n", "n"]
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(answers) + "\n"))
    code, _, err = _run(["init", "--plain", "--force"], capsys)
    assert code == 0, err
    text = target.read_text(encoding="utf-8")
    assert "# mine" not in text
    assert text.startswith("# Orkestra configuration.")
    assert (target.with_name("config.yaml.bak")).read_text(encoding="utf-8") == (
        "version: 1\nlanguage: tr   # mine\n"
    )
