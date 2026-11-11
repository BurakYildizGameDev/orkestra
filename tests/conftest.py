from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from orkestra import i18n


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """No test sees the developer's home, language or locale."""
    for var in (i18n.LANG_ENV, "LC_ALL", "LC_MESSAGES", "LANG", "ORKESTRA_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n, "_platform_locale", lambda: None)
    monkeypatch.setenv("ORKESTRA_HOME", str(tmp_path / "orkestra-home"))
    from orkestra.providers import cli_agent  # agy's files in the developer's home

    monkeypatch.setattr(cli_agent, "AGY_SETTINGS", tmp_path / "agy-home" / "settings.json")
    monkeypatch.setattr(cli_agent, "AGY_MCP_CONFIG", tmp_path / "agy-home" / "mcp_config.json")
    monkeypatch.setenv(i18n.STRICT_ENV, "1")
    # Wide terminal so rich does not wrap help text in assertions.
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    i18n.set_language("en")
    yield
    i18n.set_language("en")


@pytest.fixture(autouse=True)
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Retry backoff never really waits in tests; the requested delays are recorded."""
    from orkestra.tasks import runner

    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(runner, "_sleep", fake_sleep)
    return recorded


@pytest.fixture(autouse=True)
def no_real_agents(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the fake agent (run by this Python) may start; real codex/agy only in live tests."""
    if request.node.get_closest_marker("live") is not None:
        return
    import sys

    from orkestra.providers import cli_agent

    def which(command: str, environ: object) -> str | None:
        return sys.executable if command == sys.executable else None

    monkeypatch.setattr(cli_agent, "_which", which)


GIT_ENV = {
    "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
}  # fmt: skip


def git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` for test setup; returns stdout."""
    import subprocess

    env = {**__import__("os").environ, **GIT_ENV}
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=repo, capture_output=True, check=True, env=env,
    )  # fmt: skip
    return done.stdout.decode("utf-8", errors="replace")


@pytest.fixture
def make_repo(tmp_path: Path) -> object:
    """``make_repo(files, name="repo", autocrlf="false")``: a git repo with one commit."""

    def factory(files: dict[str, str | bytes], name: str = "repo", autocrlf: str = "false") -> Path:
        repo = tmp_path / name
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "core.autocrlf", autocrlf)
        for rel, content in files.items():
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "init")
        return repo

    return factory
