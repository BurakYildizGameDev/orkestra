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
