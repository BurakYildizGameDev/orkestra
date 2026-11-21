"""Web server for the Orkestra graphical interface (Faz 11c-a, D-121).

Security rules:
- binds strictly to 127.0.0.1 (never 0.0.0.0);
- random empty port assigned by OS when port=0;
- per-session cryptographically random token in URL and headers (no unauthorized local access);
- Host header check: rejects requests if Host does not match 127.0.0.1:<port> or 127.0.0.1;
- CORS disabled: cross-origin browser requests (e.g. from malicious sites) are rejected;
- token must be provided via query param `?token=...`,
  `Authorization: Bearer ...`, or `X-Orkestra-Token: ...`;
- missing or invalid token yields 403 Forbidden;
- responses are never cached, framed or sent as a referrer (the address carries the token);
- on Windows the port is bound exclusively, so a second server cannot share it.
"""

from __future__ import annotations

import http.server
import json
import secrets
import socket
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orkestra import __version__
from orkestra.errors import InternalError, UsageError
from orkestra.i18n import t

_SECURITY_HEADERS = (
    ("Cache-Control", "no-store"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
)


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 0
    token: str = ""
    config_path: Path | None = None


class WebServer(http.server.ThreadingHTTPServer):
    server_port: int  # set by HTTPServer.server_bind
    # On Windows SO_REUSEADDR lets a second socket bind a port that is already listening.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, config: ServerConfig) -> None:
        if config.host != "127.0.0.1":
            raise InternalError(f"WebServer must bind strictly to 127.0.0.1, got {config.host!r}")
        self.token = config.token or secrets.token_urlsafe(24)
        self.config_path = config.config_path
        super().__init__((config.host, config.port), WebHandler)

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class WebHandler(http.server.BaseHTTPRequestHandler):
    server_version = "Orkestra"
    sys_version = ""

    server: WebServer  # for type checker

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default stderr request logging to keep CLI output clean
        pass

    def _send(self, status_code: int, content_type: str, body: bytes) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in _SECURITY_HEADERS:
            self.send_header(name, value)
        # No CORS headers
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status_code: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=True).encode("utf-8")
        self._send(status_code, "application/json; charset=utf-8", body)

    def _send_html(self, status_code: int, html: str) -> None:
        self._send(status_code, "text/html; charset=utf-8", html.encode("utf-8"))

    def _send_error_json(self, status_code: int, message: str) -> None:
        self._send_json(status_code, {"error": message})

    def _check_security(self) -> bool:
        """Validate Host, Origin, and Token. Returns True if request is allowed."""
        # 1. Host header validation
        host_header = self.headers.get("Host", "").strip()
        port = self.server.server_port
        allowed_hosts = {f"127.0.0.1:{port}", "127.0.0.1"}
        if host_header not in allowed_hosts:
            self._send_error_json(403, "Invalid Host header")
            return False

        # 2. CORS / Origin check
        origin_header = self.headers.get("Origin")
        if origin_header is not None:
            allowed_origin = f"http://127.0.0.1:{port}"
            if origin_header.rstrip("/") != allowed_origin:
                self._send_error_json(403, "Cross-origin requests forbidden")
                return False

        # 3. Token validation
        parsed_url = urllib.parse.urlsplit(self.path)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        token_query = query_params.get("token", [None])[0]

        auth_header = self.headers.get("Authorization", "").strip()
        token_auth = auth_header[7:].strip() if auth_header.startswith("Bearer ") else None

        token_custom = self.headers.get("X-Orkestra-Token", "").strip() or None

        token = token_query or token_auth or token_custom

        # compare_digest rejects non-ASCII str with TypeError; compare bytes instead.
        if not token or not secrets.compare_digest(
            token.encode("utf-8"), self.server.token.encode("utf-8")
        ):
            self._send_error_json(403, "Forbidden")
            return False

        return True

    def do_GET(self) -> None:
        if not self._check_security():
            return

        parsed = urllib.parse.urlsplit(self.path).path
        if parsed in ("/", "/index.html"):
            html = (
                "<!DOCTYPE html>\n"
                '<html lang="en">\n'
                "<head>\n"
                '    <meta charset="utf-8">\n'
                "    <title>Orkestra</title>\n"
                "</head>\n"
                "<body>\n"
                "    <h1>Orkestra</h1>\n"
                "</body>\n"
                "</html>\n"
            )
            self._send_html(200, html)
            return

        if parsed == "/api/health":
            self._send_json(200, {"ok": True, "version": __version__})
            return

        self._send_error_json(404, "Not found")

    def do_POST(self) -> None:
        if not self._check_security():
            return
        self._send_error_json(404, "Not found")


def create_server(config: ServerConfig) -> WebServer:
    try:
        return WebServer(config)
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise UsageError(t("ui.web.error.port", port=config.port, reason=reason)) from exc
