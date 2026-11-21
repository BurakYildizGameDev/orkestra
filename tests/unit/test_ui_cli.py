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
    assert "--window" in out


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


def test_ui_opens_the_browser_with_the_tokenized_address(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import webbrowser

    from orkestra.web import server

    mock_open = MagicMock()
    monkeypatch.setattr(webbrowser, "open", mock_open)
    monkeypatch.setattr(server.WebServer, "serve_forever", MagicMock(side_effect=KeyboardInterrupt))

    code, out, _ = _run(["ui"], capsys)
    assert code == 0
    mock_open.assert_called_once()
    url = mock_open.call_args.args[0]
    assert url.startswith("http://127.0.0.1:")
    assert "?token=" in url
    assert url in out


def test_ui_busy_port_is_a_clear_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import webbrowser

    from orkestra.web import server

    monkeypatch.setattr(webbrowser, "open", MagicMock())
    taken = server.create_server(server.ServerConfig(port=0, token="tok"))
    try:
        code, _, err = _run(["ui", "--no-browser", "--port", str(taken.server_port)], capsys)
    finally:
        taken.server_close()
    assert code == 2
    assert str(taken.server_port) in err
    assert "Traceback" not in err


def test_ui_window_flag_without_pywebview_falls_back_to_browser(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sys
    import webbrowser

    from orkestra.i18n import t
    from orkestra.web import server

    monkeypatch.setitem(sys.modules, "webview", None)
    mock_open = MagicMock()
    monkeypatch.setattr(webbrowser, "open", mock_open)
    monkeypatch.setattr(server.WebServer, "serve_forever", MagicMock(side_effect=KeyboardInterrupt))

    code, _, err = _run(["ui", "--window"], capsys)
    assert code == 0
    assert t("ui.web.window_fallback") in err
    mock_open.assert_called_once()
    url = mock_open.call_args.args[0]
    assert url.startswith("http://127.0.0.1:")


def test_ui_window_flag_with_pywebview_opens_window(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sys
    import types
    import webbrowser

    from orkestra.web import server

    mock_open = MagicMock()
    monkeypatch.setattr(webbrowser, "open", mock_open)

    mock_webview = types.ModuleType("webview")
    mock_webview.create_window = MagicMock()  # type: ignore[attr-defined]
    mock_webview.start = MagicMock()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "webview", mock_webview)

    mock_serve = MagicMock()
    mock_shutdown = MagicMock()
    monkeypatch.setattr(server.WebServer, "serve_forever", mock_serve)
    monkeypatch.setattr(server.WebServer, "shutdown", mock_shutdown)

    code, _, _ = _run(["ui", "--window"], capsys)
    assert code == 0
    mock_open.assert_not_called()
    mock_webview.create_window.assert_called_once()
    args = mock_webview.create_window.call_args[0]
    assert args[0] == "Orkestra"
    assert args[1].startswith("http://127.0.0.1:")
    mock_webview.start.assert_called_once()
    mock_shutdown.assert_called_once()
