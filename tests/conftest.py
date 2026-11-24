from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from orkestra import i18n


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """No test sees the developer's home, locale, or project config from the repo cwd."""
    monkeypatch.chdir(tmp_path)
    for var in (i18n.LANG_ENV, "LC_ALL", "LC_MESSAGES", "LANG", "ORKESTRA_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n, "_platform_locale", lambda: None)
    monkeypatch.setenv("ORKESTRA_HOME", str(tmp_path / "orkestra-home"))
    # Claude Code's transcripts (``tokens``, the session hint in ``status``): never the real ones.
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    from orkestra.providers import cli_agent  # agy's files in the developer's home

    monkeypatch.setattr(cli_agent, "AGY_SETTINGS", tmp_path / "agy-home" / "settings.json")
    monkeypatch.setattr(cli_agent, "AGY_MCP_CONFIG", tmp_path / "agy-home" / "mcp_config.json")
    from orkestra import hardware  # doctor never runs the developer's nvidia-smi (Faz 13l)

    monkeypatch.setattr(hardware, "_run", lambda args: None)
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


@pytest.fixture(autouse=True)
def no_real_notifications(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """No test shows a desktop notification or posts to ntfy.sh; what would be sent is kept."""
    from orkestra.notify import notify

    sent: list[tuple[str, ...]] = []

    def desktop(title: str, message: str) -> None:
        raise ImportError("desktop_notifier is never used in tests")

    def post(url: str, title: str, message: str) -> None:
        sent.append((url, title, message))

    monkeypatch.setattr(notify, "desktop_send", desktop)
    monkeypatch.setattr(notify, "ntfy_post", post)
    return sent


class MemoryKeyring:
    """The OS credential store stand-in: no test reads or writes the developer's keyring."""

    def __init__(self) -> None:
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        import keyring.errors

        if self.passwords.pop((service, username), None) is None:
            raise keyring.errors.PasswordDeleteError("not found")


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch: pytest.MonkeyPatch) -> MemoryKeyring:
    """Keys read through ``chief.keys`` (env first, then keyring) never come from the real
    store: a key saved there by the web interface would change "key missing" tests (11c-d)."""
    import keyring

    store = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: store)
    monkeypatch.setattr(keyring, "get_password", store.get_password)
    monkeypatch.setattr(keyring, "set_password", store.set_password)
    monkeypatch.setattr(keyring, "delete_password", store.delete_password)
    return store


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
