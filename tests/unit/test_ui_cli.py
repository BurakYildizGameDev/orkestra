from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

from orkestra.cli import app


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    out, err = ansi.sub("", captured.out), ansi.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


def test_ui_help_shows_new_options(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["ui", "--help"], capsys)
    assert code == 0
    assert "--tui" in out
    assert "--no-browser" in out
    assert "--port" in out


def test_ui_tui_flag_invokes_terminal_app(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from orkestra.tui import app as tui_app

    monkeypatch.setattr(tui_app, "usable_terminal", lambda: True)
    mock_run = MagicMock()
    monkeypatch.setattr(tui_app.OrkestraApp, "run", mock_run)

    code, _, _ = _run(["ui", "--tui"], capsys)
    assert code == 0
    mock_run.assert_called_once()


def test_ui_no_browser_starts_server_and_does_not_open_browser(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import webbrowser

    mock_open = MagicMock()
    monkeypatch.setattr(webbrowser, "open", mock_open)

    from orkestra.web import server

    orig_create = server.create_server

    class MockServer:
        def __init__(self, s: server.WebServer) -> None:
            self._s = s
            self.server_port = s.server_port
            self.token = s.token
            self.server_address = s.server_address

        def serve_forever(self) -> None:
            # Simulate immediate exit (as if user pressed Ctrl+C)
            raise KeyboardInterrupt

        def server_close(self) -> None:
            self._s.server_close()

    def fake_create(config: server.ServerConfig) -> server.WebServer:
        real = orig_create(config)
        return MockServer(real)  # type: ignore

    monkeypatch.setattr(server, "create_server", fake_create)

    code, out, _ = _run(["ui", "--no-browser"], capsys)
    assert code == 0
    assert "127.0.0.1" in out
    assert "token=" in out
    mock_open.assert_not_called()
