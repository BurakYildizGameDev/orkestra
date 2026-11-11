"""Faz 8a: response cache, templates, ``status`` and the savings counter, end to end."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest

from orkestra import paths
from orkestra.cli import app
from orkestra.config.loader import load_config
from orkestra.providers.base import CompletionRequest, CompletionResult, Usage
from orkestra.providers.ollama import OllamaChat
from orkestra.state import consent, db

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
MakeRepo = Callable[..., Path]

CONFIG = """\
version: 1
providers:
  ollama:
    type: ollama
    base_url: http://ollama.test:11434
    concurrency: 4
    models:
      - id: coder
        tier: 1
        edit_format: whole
"""


class FakeOllama:
    def __init__(self) -> None:
        self.calls: list[CompletionRequest] = []
        self.answers: dict[str, str] = {}  # prompt substring -> answer

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        self.calls.append(req)
        text = next((a for key, a in self.answers.items() if key in req.user), "fine answer")
        return CompletionResult(text, Usage(40, 12, 0.0), "stop")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeOllama:
    worker = FakeOllama()

    async def complete(self: OllamaChat, req: CompletionRequest) -> CompletionResult:
        return await worker.complete(req)

    monkeypatch.setattr(OllamaChat, "complete", complete)
    return worker


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str = CONFIG) -> Path:
    home = tmp_path / "orkestra-home"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(config, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    monkeypatch.chdir(work)
    loaded = load_config(cwd=work, environ={}).config
    with closing(db.connect()) as conn:
        consent.grant(conn, "ollama", loaded.providers["ollama"], db.local_now())
    return work


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


def _usage_rows() -> int:
    with closing(sqlite3.connect(paths.state_db_path())) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM usage WHERE kind = 'actual'").fetchone()[0])


# --- response cache ----------------------------------------------------------------------


def test_the_same_ask_twice_is_answered_from_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    (work / "a.py").write_text("x = 1\n", encoding="utf-8")
    argv = ["ask", "What is x?", "--context", "a.py", "--json"]
    code, out, _ = _run(argv, capsys)
    assert code == 0, out
    first = json.loads(out)
    assert first["cached"] is False and len(fake.calls) == 1
    code, out, _ = _run(argv, capsys)
    assert code == 0, out
    second = json.loads(out)
    assert len(fake.calls) == 1  # the provider was not asked again
    assert second["cached"] is True and second["status"] == "ok"
    assert second["usage"]["cost_usd"] in (0, None)
    assert second["usage"]["completion_tokens"] in (0, None)
    assert _usage_rows() == 1  # nothing was settled against the budget for the cached answer
    output = Path(second["output_path"]).read_text(encoding="utf-8")
    assert output.strip() == "fine answer"


def test_a_changed_context_file_is_a_new_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    (work / "a.py").write_text("x = 1\n", encoding="utf-8")
    argv = ["ask", "What is x?", "--context", "a.py", "--json"]
    assert _run(argv, capsys)[0] == 0
    (work / "a.py").write_text("x = 2\n", encoding="utf-8")
    code, out, _ = _run(argv, capsys)
    assert code == 0 and json.loads(out)["cached"] is False and len(fake.calls) == 2


def test_no_cache_and_a_disabled_cache_always_ask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    assert _run(["ask", "Hi?", "--json"], capsys)[0] == 0
    code, out, _ = _run(["ask", "Hi?", "--json", "--no-cache"], capsys)
    assert code == 0 and json.loads(out)["cached"] is False and len(fake.calls) == 2
    (tmp_path / "orkestra-home" / "config.yaml").write_text(
        CONFIG + "cache:\n  enabled: false\n", encoding="utf-8"
    )
    code, out, _ = _run(["ask", "Hi?", "--json"], capsys)
    assert code == 0 and json.loads(out)["cached"] is False and len(fake.calls) == 3


def test_an_answer_that_failed_its_checks_is_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    task = {"id": "q", "kind": "ask", "prompt": "Say yes.",
            "verify": [{"type": "regex", "must_match": ["^yes$"]}]}  # fmt: skip
    (work / "q.json").write_text(json.dumps(task), encoding="utf-8")
    fake.answers["Say yes."] = "no"
    code, _, _ = _run(["run", "q.json", "--json"], capsys)
    assert code == 1
    calls = len(fake.calls)
    code, _, _ = _run(["run", "q.json", "--json"], capsys)
    assert len(fake.calls) > calls  # asked again: nothing wrong was cached


def test_edit_tasks_are_never_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama, make_repo: MakeRepo,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    repo = make_repo({"a.py": "x = 1\n"})
    monkeypatch.chdir(repo)
    fake.answers["change it"] = json.dumps({"files": [{"path": "a.py", "content": "x = 2\n"}]})
    task = {"id": "e", "kind": "edit", "prompt": "change it", "context": {"files": ["a.py"]}}
    (tmp_path / "e.json").write_text(json.dumps(task), encoding="utf-8")
    assert _run(["run", str(tmp_path / "e.json"), "--json"], capsys)[0] == 0
    code, out, _ = _run(["run", str(tmp_path / "e.json"), "--json"], capsys)
    assert code == 0 and json.loads(out)["cached"] is False and len(fake.calls) == 2


def test_an_old_entry_expires_and_cache_clear_empties_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    from orkestra.cache import responses

    _setup(tmp_path, monkeypatch, CONFIG + "cache:\n  ttl_days: 3\n")
    assert _run(["ask", "Hi?", "--json"], capsys)[0] == 0
    old = (db.local_now() - timedelta(days=4)).isoformat()
    for entry in responses.cache_root().glob("*.json"):
        data = json.loads(entry.read_text(encoding="utf-8"))
        entry.write_text(json.dumps({**data, "created_at": old}), encoding="utf-8")
    code, out, _ = _run(["ask", "Hi?", "--json"], capsys)
    assert code == 0 and json.loads(out)["cached"] is False and len(fake.calls) == 2
    assert list(responses.cache_root().glob("*.json"))
    code, out, _ = _run(["cache", "clear", "--json"], capsys)
    assert code == 0 and json.loads(out)["removed"] >= 1
    assert not list(responses.cache_root().glob("*.json"))


# --- templates ---------------------------------------------------------------------------

BUILTIN = {"docstring", "type-hints", "tests", "summarize", "rename-refactor", "translate"}


def _docstring_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama, make_repo: MakeRepo,
    names: tuple[str, ...] = ("a.py", "b.py", "c.py"),
) -> Path:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    repo = make_repo({f"src/{n}": f"def f_{i}():\n    return {i}\n" for i, n in enumerate(names)})
    monkeypatch.chdir(repo)
    for i, name in enumerate(names):
        content = f'def f_{i}():\n    """Return {i}."""\n    return {i}\n'
        fake.answers[f"src/{name}"] = json.dumps(
            {"files": [{"path": f"src/{name}", "content": content}]}
        )
    return repo


def test_templates_list_and_show(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    work = _setup(tmp_path, monkeypatch)
    code, out, _ = _run(["templates", "list", "--json"], capsys)
    assert code == 0, out
    listed = {item["name"]: item for item in json.loads(out)["templates"]}
    assert set(listed) >= BUILTIN and all(listed[n]["source"] == "builtin" for n in BUILTIN)
    # A project template with the same name wins.
    project = work / ".orkestra" / "templates"
    project.mkdir(parents=True)
    (project / "docstring.yaml").write_text(
        "description: Our docstrings.\ntask:\n  kind: edit\n  prompt: Document $file.\n"
        "  context: {files: [$file]}\n",
        encoding="utf-8",
    )
    code, out, _ = _run(["templates", "show", "docstring", "--json"], capsys)
    assert code == 0, out
    shown = json.loads(out)
    assert shown["source"] == "project" and shown["description"] == "Our docstrings."
    code, out, _ = _run(["--lang", "en", "templates", "list"], capsys)
    assert code == 0 and "docstring" in out and "translate" in out
    code, out, _ = _run(["--lang", "tr", "templates", "list"], capsys)  # described per language
    assert code == 0 and "Bir dosyanın yorumlarını" in out
    assert _run(["templates", "show", "nope"], capsys)[0] == 2


def test_run_template_makes_one_task_per_file_and_runs_them_as_a_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama, make_repo: MakeRepo,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _docstring_repo(tmp_path, monkeypatch, fake, make_repo)
    argv = ["run", "--template", "docstring", "--files", "src/*.py", "--param", "style=numpy",
            "--json"]  # fmt: skip
    code, out, _ = _run(argv, capsys)
    assert code == 0, out
    doc = json.loads(out)
    assert len(doc["results"]) == 3 and doc["totals"]["ok"] == 3
    assert len({r["task_id"] for r in doc["results"]}) == 3
    assert all("numpy" in call.user for call in fake.calls)
    with closing(sqlite3.connect(paths.state_db_path())) as conn:
        tags = [json.loads(row[0]) for row in conn.execute("SELECT tags FROM runs")]
    assert len(tags) == 3 and all("docstring" in t for t in tags)


def test_run_template_dry_run_shows_the_tasks_and_sends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama, make_repo: MakeRepo,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    from ruamel.yaml import YAML

    _docstring_repo(tmp_path, monkeypatch, fake, make_repo, names=("a.py", "cost$x.py"))
    argv = ["run", "--template", "docstring", "--files", "src/*.py", "--dry-run"]
    code, out, _ = _run(argv, capsys)
    assert code == 0, out
    assert fake.calls == []
    data = YAML(typ="safe").load(out)
    prompts = [task["prompt"] for task in data["tasks"]]
    assert len(prompts) == 2
    assert any("src/cost$x.py" in p for p in prompts)  # a "$" in a file name stays as it is
    assert all(task["tags"][0] == "docstring" for task in data["tasks"])


@pytest.mark.parametrize(
    "argv",
    [
        ["run"],  # neither a task file nor a template
        ["run", "t.yaml", "--template", "docstring", "--files", "src/*.py"],  # both
        ["run", "--files", "src/*.py"],  # --files without --template
        ["run", "--template", "docstring"],  # no files
        ["run", "--template", "nope", "--files", "src/*.py"],
        ["run", "--template", "docstring", "--files", "src/*.py", "--param", "colour=red"],
        ["run", "--template", "docstring", "--files", "src/*.py", "--param", "novalue"],
        ["run", "--template", "translate", "--files", "src/*.py"],  # language is required
        ["run", "--template", "docstring", "--files", "nothing/*.py"],  # no file matches
    ],
)
def test_run_template_usage_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama, make_repo: MakeRepo,
    capsys: pytest.CaptureFixture[str], argv: list[str],
) -> None:  # fmt: skip
    _docstring_repo(tmp_path, monkeypatch, fake, make_repo)
    code, _, _ = _run(argv, capsys)
    assert code == 2 and fake.calls == []


def test_every_builtin_template_makes_valid_tasks(tmp_path: Path) -> None:
    from orkestra.tasks import templates

    (tmp_path / "x.py").write_text("x = 1\n", encoding="utf-8")
    params = {"rename-refactor": {"old": "x", "new": "y"}, "translate": {"language": "German"}}
    for name in BUILTIN:
        spec = templates.expand(
            templates.find(name, cwd=tmp_path), ["x.py"], params.get(name, {}), cwd=tmp_path
        )
        (task,) = spec.tasks
        assert name in task.tags and "x.py" in task.prompt


# --- status ------------------------------------------------------------------------------


def _many_providers(count: int) -> str:
    entries = "".join(
        f"  local{n:02d}:\n    type: ollama\n    base_url: http://ollama{n}.test:11434\n"
        f"    budget: {{daily_requests: 100}}\n    models:\n      - id: m\n        tier: 1\n"
        for n in range(count)
    )
    return CONFIG + entries


def test_status_never_goes_over_15_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch, _many_providers(30))
    code, out, _ = _run(["--lang", "en", "status"], capsys)
    assert code == 0, out
    lines = out.rstrip("\n").splitlines()
    assert 0 < len(lines) <= 15
    code, out, _ = _run(["status", "--json"], capsys)
    assert code == 0, out
    doc = json.loads(out)
    assert {"profile", "unapplied", "budget", "health"} <= set(doc["sections"])
    assert len(doc["sections"]["budget"]["providers"]) == 31  # JSON keeps everything


def test_status_lists_unapplied_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama, make_repo: MakeRepo,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _docstring_repo(tmp_path, monkeypatch, fake, make_repo, names=("a.py",))
    code, out, _ = _run(["run", "--template", "docstring", "--files", "src/a.py", "--json"],
                        capsys)  # fmt: skip
    assert code == 0, out
    run_id = json.loads(out)["results"][0]["run_id"]
    code, out, _ = _run(["--lang", "en", "status"], capsys)
    assert code == 0 and run_id in out
    code, out, _ = _run(["status", "--json"], capsys)
    unapplied = json.loads(out)["sections"]["unapplied"]["runs"]
    assert [r["run_id"] for r in unapplied] == [run_id]
    assert _run(["apply", run_id], capsys)[0] == 0
    code, out, _ = _run(["status", "--json"], capsys)
    assert json.loads(out)["sections"]["unapplied"]["runs"] == []


def test_status_sections_can_be_added_by_later_phases() -> None:
    from orkestra.chief import status

    @status.section("test-extra", order=999)
    def extra(ctx: status.StatusContext) -> status.Section:
        return status.Section(lines=["extra line"], data={"x": 1})

    try:
        assert "test-extra" in [name for name, _, _ in status.registered()]
    finally:
        status.unregister("test-extra")
    assert "test-extra" not in [name for name, _, _ in status.registered()]


# --- savings counter ---------------------------------------------------------------------


def test_stats_shows_the_estimated_savings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOllama,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _setup(tmp_path, monkeypatch)
    assert _run(["ask", "Hi?", "--json"], capsys)[0] == 0
    code, out, _ = _run(["stats", "--json"], capsys)
    assert code == 0, out
    savings = json.loads(out)["savings"]
    assert savings["worker_output_tokens"] == 12 and savings["envelope_chars"] > 0
    assert savings["envelope_tokens"] > 0 and savings["estimated"] is True
    code, out, _ = _run(["--lang", "en", "stats"], capsys)
    assert code == 0 and "estimated" in out.lower()
