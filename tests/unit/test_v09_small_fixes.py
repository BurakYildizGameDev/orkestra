"""The small problems of the v0.9 break test (2026-11-23, D-141)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from orkestra.errors import UsageError
from tests.unit.test_web_11c_review import cfg_file, state_db  # noqa: F401  (fixtures)
from tests.unit.test_web_server import simulate_request


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


# --- B-10 / B-11: find ---------------------------------------------------------------


def test_find_says_which_files_were_too_large_to_search(tmp_path: Path) -> None:
    from orkestra.chief import finder

    repo = _repo(tmp_path)
    (repo / "small.txt").write_text("needle\n", encoding="utf-8")
    (repo / "huge.log").write_bytes(b"x\n" * (finder.MAX_FILE_BYTES // 2 + 10) + b"needle\n")
    result = finder.find("needle", cwd=repo, config=None)
    assert result.skipped_large == ["huge.log"]
    assert "huge.log" in finder.render(result)
    assert finder.to_dict(result)["skipped_large"] == ["huge.log"]


def test_find_with_an_empty_pattern_is_a_usage_error(tmp_path: Path) -> None:
    from orkestra.chief import finder

    with pytest.raises(UsageError):
        finder.find("", cwd=_repo(tmp_path), config=None)


# --- B-12: a folder given as a file ---------------------------------------------------


def test_a_folder_as_context_says_it_is_a_folder(tmp_path: Path) -> None:
    from orkestra.i18n import t
    from orkestra.tasks import context

    (tmp_path / "sub").mkdir()
    with pytest.raises(UsageError) as exc_info:
        context.collect_context([Path("sub")], max_bytes=10_000, cwd=tmp_path)
    assert exc_info.value.message == t("context.error.is_folder", path=Path("sub"))


# --- B-14: config backups -------------------------------------------------------------


def test_saving_an_unchanged_config_writes_nothing(tmp_path: Path) -> None:
    from orkestra.config import writer

    path = tmp_path / "config.yaml"
    path.write_text("version: 1\n", encoding="utf-8")
    result = writer.save(path, writer.load_document(path))
    assert result.backup is None
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.yaml"]


def test_only_the_last_numbered_backups_are_kept(tmp_path: Path) -> None:
    from orkestra.config import writer

    path = tmp_path / "config.yaml"
    path.write_text("version: 1\n", encoding="utf-8")
    for n in range(writer.KEEP_BACKUPS + 4):
        doc = writer.load_document(path)
        doc["language"] = "en" if n % 2 else "tr"
        writer.save(path, doc)
    numbered = [p for p in tmp_path.iterdir() if ".bak." in p.name]
    assert len(numbered) == writer.KEEP_BACKUPS
    assert (tmp_path / "config.yaml.bak").is_file()  # the first, original backup stays


# --- B-15 / B-16: the web interface's API ---------------------------------------------


def _post(cfg: Path, path: str, body: bytes) -> tuple[int, dict[str, str]]:
    from orkestra.web.server import ServerConfig, create_server

    server = create_server(ServerConfig(port=0, token="tok", config_path=cfg))
    try:
        code, _, raw = simulate_request(server, "POST", f"{path}?token=tok", body=body)
    finally:
        server.server_close()
    return code, json.loads(raw)


def test_web_tier_that_is_not_a_number_gets_a_readable_error(
    cfg_file: Path,  # noqa: F811
    state_db: Path,  # noqa: F811
) -> None:
    code, data = _post(cfg_file, "/api/team/worker/tier", b'{"name": "local", "tier": "abc"}')
    assert code == 400
    assert "int()" not in data["error"]


def test_web_body_that_is_not_json_gets_a_readable_error(
    cfg_file: Path,  # noqa: F811
    state_db: Path,  # noqa: F811
) -> None:
    code, data = _post(cfg_file, "/api/team/worker/tier", b"not json")
    assert code == 400
    assert "Expecting value" not in data["error"]


def test_web_reorder_needs_a_list(cfg_file: Path, state_db: Path) -> None:  # noqa: F811
    code, _ = _post(cfg_file, "/api/team/worker/reorder", b'{"names": "abc"}')
    assert code == 400


def test_web_model_name_with_a_line_break_is_refused(
    cfg_file: Path,  # noqa: F811
    state_db: Path,  # noqa: F811
) -> None:
    before = cfg_file.read_text(encoding="utf-8")
    code, data = _post(
        cfg_file, "/api/team/worker/model", b'{"name": "local", "model": "m\\nfoo: bar"}'
    )
    assert code == 400
    assert "--model" not in data["error"]
    assert cfg_file.read_text(encoding="utf-8") == before


def test_web_refuses_a_huge_body(cfg_file: Path, state_db: Path) -> None:  # noqa: F811
    from orkestra.web import server as web

    code, _ = _post(cfg_file, "/api/team/worker/tier", b"x" * (web.MAX_BODY_BYTES + 1))
    assert code == 413


def test_web_answers_on_localhost_too(cfg_file: Path, state_db: Path) -> None:  # noqa: F811
    from orkestra.web.server import ServerConfig, create_server

    server = create_server(ServerConfig(port=0, token="tok", config_path=cfg_file))
    try:
        port = server.server_port
        code, _, _ = simulate_request(
            server, "GET", "/api/team?token=tok", headers={"Host": f"localhost:{port}"}
        )
        evil, _, _ = simulate_request(
            server, "GET", "/api/team?token=tok", headers={"Host": "evil.test"}
        )
    finally:
        server.server_close()
    assert code == 200
    assert evil == 403


# --- B-21: a run that never finished --------------------------------------------------


def test_show_of_a_run_without_an_envelope_says_it_did_not_finish() -> None:
    from orkestra import paths
    from orkestra.i18n import t
    from orkestra.workspace import service

    run_dir = paths.run_dir("20261123-120000-abcd")
    run_dir.mkdir(parents=True)
    (run_dir / "orkestra.log").write_text("attempt 1\n", encoding="utf-8")
    with pytest.raises(UsageError) as exc_info:
        service.show("20261123-120000-abcd", "envelope")
    assert exc_info.value.message == t("show.unfinished", run_id="20261123-120000-abcd")


# --- B-22: Orkestra's own files stay out of the user's git status ---------------------


def test_map_file_does_not_show_up_in_git_status(tmp_path: Path) -> None:
    from orkestra.chief import repomap

    repo = _repo(tmp_path)
    repomap.write_map_file(repo, "# map\n")
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    )
    assert status.stdout == ""


def test_the_handoff_file_and_templates_stay_visible_to_git(tmp_path: Path) -> None:
    from orkestra import paths

    repo = _repo(tmp_path)
    local = paths.ensure_project_dir(repo)
    (local / "HANDOFF.md").write_text("# handoff\n", encoding="utf-8")
    (local / "templates").mkdir()
    (local / "templates" / "mine.yaml").write_text("x: 1\n", encoding="utf-8")
    status = subprocess.run(
        ["git", "status", "--porcelain", "-uall"],
        cwd=repo, capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert ".orkestra/HANDOFF.md" in status.stdout
    assert ".orkestra/templates/mine.yaml" in status.stdout


# --- B-23: typer's own help texts follow the language ---------------------------------


def test_help_panels_follow_the_language(capsys: pytest.CaptureFixture[str]) -> None:
    from orkestra.cli import app
    from orkestra.i18n import set_language, t

    with pytest.raises(SystemExit):
        app(["--lang", "tr", "budget", "--help"])
    out = capsys.readouterr().out
    set_language("tr")
    assert t("cli.typer.options") in out
    assert "Options" not in out
