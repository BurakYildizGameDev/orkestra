"""Web server for the Orkestra graphical interface (Faz 11c-a, D-121).

Security rules:
- binds strictly to 127.0.0.1 (never 0.0.0.0);
- random empty port assigned by OS when port=0;
- per-session cryptographically random token in URL and headers (no unauthorized local access);
- Host header check: rejects requests if Host does not match 127.0.0.1:<port> or 127.0.0.1;
- CORS disabled: cross-origin browser requests (e.g. from malicious sites) are rejected;
- token must be provided via query param `?token=...`,
  `Authorization: Bearer ...`, or `X-Orkestra-Token: ...`;
- missing or invalid token yields 403 Forbidden.
"""

from __future__ import annotations

import http.server
import json
import secrets
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orkestra import __version__


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 0
    token: str = ""
    config_path: Path | None = None


class WebServer(http.server.ThreadingHTTPServer):
    server_port: int  # set by HTTPServer.server_bind

    def __init__(self, config: ServerConfig) -> None:
        if config.host != "127.0.0.1":
            raise ValueError(f"WebServer must bind strictly to 127.0.0.1, got {config.host!r}")
        self.token = config.token or secrets.token_urlsafe(24)
        self.config_path = config.config_path
        super().__init__((config.host, config.port), WebHandler)


class WebHandler(http.server.BaseHTTPRequestHandler):
    server_version = "Orkestra"
    sys_version = ""

    server: WebServer  # for type checker

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default stderr request logging to keep CLI output clean
        pass

    def _send_json(self, status_code: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # No CORS headers
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status_code: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # No CORS headers
        self.end_headers()
        self.wfile.write(body)

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

        if not token or not secrets.compare_digest(token, self.server.token):
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
    return WebServer(config)
