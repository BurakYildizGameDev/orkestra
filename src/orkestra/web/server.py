"""Web server for the Orkestra graphical interface (Faz 11c-a, Faz 11c-b, D-121).

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

import asyncio
import http.server
import json
import secrets
import socket
import sys
import threading
import urllib.parse
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orkestra import __version__
from orkestra.chief import team
from orkestra.chief.home import home_summary
from orkestra.config.loader import load_config
from orkestra.config.schema import NotifyCfg
from orkestra.doctor import DoctorReport
from orkestra.errors import ConfigError, InternalError, UsageError
from orkestra.i18n import t
from orkestra.notify import notify
from orkestra.notify.notify import Delivery
from orkestra.state import db
from orkestra.web.ui import render_home_html

_SECURITY_HEADERS = (
    ("Cache-Control", "no-store"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
)


def _default_doctor_runner(*, config_flag: Path | None = None) -> DoctorReport:
    from orkestra import doctor

    return asyncio.run(doctor.run_doctor(config_flag=config_flag))


def _default_notify_send(config: NotifyCfg, title: str, message: str) -> list[Delivery]:
    return notify.send(config, title, message)


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
        self.doctor_report: DoctorReport | None = None
        self.doctor_error: str | None = None
        self.doctor_running: bool = False
        self.doctor_runner: Callable[..., DoctorReport] = _default_doctor_runner
        self.notify_sender: Callable[..., list[Delivery]] = _default_notify_send
        self._doctor_lock = threading.RLock()
        super().__init__((config.host, config.port), WebHandler)

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()

    def run_doctor_background(self) -> None:
        with self._doctor_lock:
            if self.doctor_running:
                return
            self.doctor_running = True
            self.doctor_report = None
            self.doctor_error = None

        def _worker() -> None:
            try:
                report = self.doctor_runner(config_flag=self.config_path)
                with self._doctor_lock:
                    self.doctor_report = report
                    self.doctor_error = None
            except Exception as exc:
                with self._doctor_lock:
                    self.doctor_report = None
                    self.doctor_error = str(exc)
            finally:
                with self._doctor_lock:
                    self.doctor_running = False

        threading.Thread(target=_worker, daemon=True).start()


def _team_json(summary: team.TeamSummary) -> dict[str, Any]:
    return {
        "patron": summary.patron,
        "chiefs": [
            {
                "name": c.name,
                "is_default": c.is_default,
                "launch": list(c.launch),
                "prompt_mode": c.prompt_mode,
            }
            for c in summary.chiefs
        ],
        "workers": [
            {
                "name": w.name,
                "type": w.type,
                "enabled": w.enabled,
                "local": w.local,
                "tier": w.tier,
                "models": list(w.models),
                "selected_model": w.selected_model,
                "base_url": w.base_url,
                "api_key_env": w.api_key_env,
                "command": w.command,
                "consent_state": w.consent_state,
                "consent_description": list(w.consent_description),
            }
            for w in summary.workers
        ],
    }


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

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                return {}
            return data
        except Exception as exc:
            raise UsageError(str(exc)) from exc

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
            self._send_html(200, render_home_html(self.server.token))
            return

        if parsed == "/api/health":
            self._send_json(200, {"ok": True, "version": __version__})
            return

        if parsed == "/api/home":
            try:
                loaded = load_config(self.server.config_path)
                with closing(db.connect()) as conn:
                    summary = home_summary(
                        loaded.config,
                        conn,
                        db.local_now(),
                        doctor_report=self.server.doctor_report,
                    )
                self._send_json(200, summary.to_dict())
            except Exception as exc:
                self._send_error_json(500, str(exc))
            return

        if parsed == "/api/doctor":
            with self.server._doctor_lock:
                if self.server.doctor_running:
                    self._send_json(200, {"status": "running", "checks": []})
                    return
                if self.server.doctor_error is not None:
                    self._send_json(200, {"status": "failed", "error": self.server.doctor_error})
                    return
                if self.server.doctor_report is not None:
                    checks = [
                        {"name": c.name, "status": c.status, "message": c.message}
                        for c in self.server.doctor_report.checks
                    ]
                    self._send_json(200, {"status": "done", "checks": checks})
                    return
                self._send_json(200, {"status": "idle", "checks": []})
                return

        if parsed == "/api/team":
            try:
                loaded = load_config(self.server.config_path)
                with closing(db.connect()) as conn:
                    summary = team.team_summary(loaded.config, conn)
                self._send_json(200, _team_json(summary))
            except Exception as exc:
                self._send_error_json(500, str(exc))
            return

        self._send_error_json(404, "Not found")

    def do_POST(self) -> None:
        if not self._check_security():
            return

        parsed = urllib.parse.urlsplit(self.path).path
        if parsed == "/api/doctor":
            self.server.run_doctor_background()
            with self.server._doctor_lock:
                running = self.server.doctor_running
            self._send_json(200, {"status": "running" if running else "done"})
            return

        if parsed == "/api/notify/test":
            try:
                loaded = load_config(self.server.config_path)
                deliveries = self.server.notify_sender(
                    loaded.config.notify,
                    t("notify.title.test"),
                    t("notify.test.message"),
                )
                lines = notify.delivery_lines(deliveries, loaded.config.notify)
                data = {
                    "ok": True,
                    "deliveries": [
                        {"channel": d.channel, "state": d.state, "reason": d.reason}
                        for d in deliveries
                    ],
                    "lines": lines,
                }
                self._send_json(200, data)
            except Exception as exc:
                self._send_error_json(500, str(exc))
            return

        if parsed.startswith("/api/team/"):
            try:
                body = self._read_json()
                if parsed == "/api/team/patron":
                    chief = str(body.get("chief", "")).strip()
                    team.set_patron(self.server.config_path, chief)
                elif parsed == "/api/team/worker/toggle":
                    name = str(body.get("name", "")).strip()
                    enabled = bool(body.get("enabled", True))
                    team.toggle_worker(self.server.config_path, name, enabled)
                elif parsed == "/api/team/worker/tier":
                    name = str(body.get("name", "")).strip()
                    tier = int(body.get("tier", 2))
                    team.set_worker_tier(self.server.config_path, name, tier)
                elif parsed == "/api/team/worker/model":
                    name = str(body.get("name", "")).strip()
                    model = str(body.get("model", "")).strip()
                    team.set_worker_model(self.server.config_path, name, model)
                elif parsed == "/api/team/worker/reorder":
                    names = [str(n).strip() for n in body.get("names", []) if str(n).strip()]
                    team.reorder_workers(self.server.config_path, names)
                elif parsed == "/api/team/worker/add":
                    name = str(body.get("name", "")).strip()
                    ptype = str(body.get("type", "openai_compat")).strip()
                    model = str(body.get("model", "")).strip()
                    tier = int(body.get("tier", 2))
                    base_url = body.get("base_url")
                    api_key_env = body.get("api_key_env")
                    command = body.get("command")
                    force = bool(body.get("force", False))
                    team.add_worker(
                        self.server.config_path,
                        name=name,
                        provider_type=ptype,
                        model=model,
                        tier=tier,
                        base_url=str(base_url) if base_url else None,
                        api_key_env=str(api_key_env) if api_key_env else None,
                        command=str(command) if command else None,
                        force=force,
                    )
                elif parsed == "/api/team/worker/remove":
                    name = str(body.get("name", "")).strip()
                    with closing(db.connect()) as conn:
                        team.remove_worker(self.server.config_path, name, conn=conn)
                elif parsed == "/api/team/consent":
                    name = str(body.get("name", "")).strip()
                    loaded = load_config(self.server.config_path)
                    with closing(db.connect()) as conn:
                        team.grant_consent(conn, loaded.config, name, db.local_now())
                else:
                    self._send_error_json(404, "Not found")
                    return

                loaded = load_config(self.server.config_path)
                with closing(db.connect()) as conn:
                    summary = team.team_summary(loaded.config, conn)
                self._send_json(200, _team_json(summary))
            except (UsageError, ConfigError, ValueError) as exc:
                self._send_error_json(400, str(exc))
            except Exception as exc:
                self._send_error_json(500, str(exc))
            return

        self._send_error_json(404, "Not found")


def create_server(config: ServerConfig) -> WebServer:
    try:
        return WebServer(config)
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise UsageError(t("ui.web.error.port", port=config.port, reason=reason)) from exc
