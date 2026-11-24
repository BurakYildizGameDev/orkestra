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
from orkestra.chief import advanced, keys, team, usage
from orkestra.chief.home import home_summary
from orkestra.config.loader import load_config
from orkestra.config.schema import Config, NotifyCfg
from orkestra.doctor import Check, DoctorReport
from orkestra.errors import ConfigError, InternalError, KeyringUnavailable, UsageError
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


def _default_provider_checker(name: str, config: Config) -> list[Check]:
    from orkestra import doctor

    return asyncio.run(doctor.check_one(name, config))


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
        # The Keys screen's "try" button: the doctor checks of one provider (network).
        self.provider_checker: Callable[[str, Config], list[Check]] = _default_provider_checker
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
        "handoff_order": list(summary.handoff_order),
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


USAGE_DAYS = (7, 30)


def _usage_days(path: str) -> int:
    """``?days=7`` (default) or ``?days=30``: the usage screen's two periods."""
    raw = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query).get("days", ["7"])[0]
    if not raw.isdigit() or int(raw) not in USAGE_DAYS:
        raise UsageError(t("usage.error.days", value=raw[:20]))
    return int(raw)


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

    def _content_length(self) -> int:
        try:
            return int(self.headers.get("Content-Length", 0))
        except ValueError:
            return 0

    def _read_json(self) -> dict[str, Any]:
        length = self._content_length()
        if length <= 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:  # B-15: no raw parser message
            raise UsageError(t("web.error.bad_json")) from exc
        return data if isinstance(data, dict) else {}

    def _check_security(self) -> bool:
        """Validate Host, Origin, and Token. Returns True if request is allowed."""
        # 1. Host header validation
        host_header = self.headers.get("Host", "").strip()
        port = self.server.server_port
        # localhost too (B-16): a rebinding attack's Host is the attacker's name, never these.
        allowed_hosts = {f"127.0.0.1:{port}", "127.0.0.1", f"localhost:{port}", "localhost"}
        if host_header not in allowed_hosts:
            self._send_error_json(403, "Invalid Host header")
            return False

        # 2. CORS / Origin check
        origin_header = self.headers.get("Origin")
        if origin_header is not None:
            allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
            if origin_header.rstrip("/") not in allowed_origins:
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

    def _key_test(self, config: Config, var_name: str) -> list[dict[str, str]]:
        """The checks of every provider whose key is ``var_name`` (only messages, no key)."""
        names = next((s.providers for s in keys.keys_status(config) if s.var_name == var_name), ())
        names = tuple(name for name in names if name in config.providers)
        if not names:
            raise UsageError(t("keys.error.not_used", var=var_name[:64]))
        return [
            {"provider": name, "status": check.status, "message": check.message}
            for name in names
            for check in self.server.provider_checker(name, config)
        ]

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

        if parsed == "/api/keys":
            try:
                loaded = load_config(self.server.config_path)
                status_list = keys.keys_status(loaded.config)
                self._send_json(200, {"keys": [s.as_dict() for s in status_list]})
            except Exception as exc:
                self._send_error_json(500, str(exc))
            return

        if parsed == "/api/usage":
            try:
                days = _usage_days(self.path)
                with closing(db.connect()) as conn:
                    summary = usage.usage_summary(conn, days=days, now=db.local_now())
                self._send_json(200, summary)
            except UsageError as exc:
                self._send_error_json(400, str(exc))
            except Exception as exc:
                self._send_error_json(500, str(exc))
            return

        if parsed == "/api/advanced":
            try:
                loaded = load_config(self.server.config_path)
                with closing(db.connect()) as conn:
                    summary = advanced.advanced_summary(loaded.config, conn, now=db.local_now())
                self._send_json(200, summary)
            except Exception as exc:
                self._send_error_json(500, str(exc))
            return

        self._send_error_json(404, "Not found")

    def do_POST(self) -> None:
        if not self._check_security():
            return
        if self._content_length() > MAX_BODY_BYTES:  # B-15
            self._send_error_json(413, t("web.error.too_large"))
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
                    enabled = body.get("enabled")
                    if not isinstance(enabled, bool):
                        raise UsageError(t("team.error.enabled_bool"))
                    team.toggle_worker(self.server.config_path, name, enabled)
                elif parsed == "/api/team/worker/tier":
                    name = str(body.get("name", "")).strip()
                    team.set_worker_tier(self.server.config_path, name, _tier(body))
                elif parsed == "/api/team/worker/model":
                    name = str(body.get("name", "")).strip()
                    model = str(body.get("model", "")).strip()
                    team.set_worker_model(self.server.config_path, name, model)
                elif parsed == "/api/team/worker/reorder":
                    raw_names = body.get("names", [])
                    if not isinstance(raw_names, list):  # B-15: a string is not a list of names
                        raise UsageError(t("web.error.bad_field", field="names"))
                    names = [str(n).strip() for n in raw_names if str(n).strip()]
                    team.reorder_workers(self.server.config_path, names)
                elif parsed == "/api/team/worker/add":
                    name = str(body.get("name", "")).strip()
                    ptype = str(body.get("type", "openai_compat")).strip()
                    model = str(body.get("model", "")).strip()
                    tier = _tier(body)
                    base_url = body.get("base_url")
                    api_key_env = body.get("api_key_env")
                    command = body.get("command")
                    no_key = body.get("no_key") is True
                    force_value = body.get("force", False)
                    if not isinstance(force_value, bool):
                        raise UsageError(t("web.error.bad_field", field="force"))
                    force = force_value
                    team.add_worker(
                        self.server.config_path,
                        name=name,
                        provider_type=ptype,
                        model=model,
                        tier=tier,
                        base_url=str(base_url) if base_url else None,
                        api_key_env=str(api_key_env) if api_key_env else None,
                        command=str(command) if command else None,
                        no_key=no_key,
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

        if parsed.startswith("/api/keys/"):
            try:
                body = self._read_json()
                if parsed == "/api/keys/set":
                    var_name = str(body.get("var_name", "")).strip()
                    key_val = str(body.get("key", "")).strip()
                    keys.set_key(var_name, key_val)
                elif parsed == "/api/keys/delete":
                    var_name = str(body.get("var_name", "")).strip()
                    keys.delete_key(var_name)
                elif parsed == "/api/keys/test":
                    var_name = str(body.get("var_name", "")).strip()
                    config = load_config(self.server.config_path).config
                    self._send_json(200, {"results": self._key_test(config, var_name)})
                    return
                else:
                    self._send_error_json(404, "Not found")
                    return

                loaded = load_config(self.server.config_path)
                status_list = keys.keys_status(loaded.config)
                self._send_json(200, {"ok": True, "keys": [s.as_dict() for s in status_list]})
            except (UsageError, ConfigError, KeyringUnavailable, ValueError) as exc:
                self._send_error_json(400, str(exc))
            except Exception as exc:
                self._send_error_json(500, str(exc))
            return

        self._send_error_json(404, "Not found")


MAX_BODY_BYTES = 1_000_000  # the interface sends small JSON; more is refused (413)


def _tier(body: dict[str, Any]) -> int:
    """The ``tier`` field as a number, or a readable error (B-15)."""
    try:
        return int(body.get("tier", 2))
    except (TypeError, ValueError) as exc:
        raise UsageError(t("team.error.invalid_tier")) from exc


def create_server(config: ServerConfig) -> WebServer:
    try:
        return WebServer(config)
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise UsageError(t("ui.web.error.port", port=config.port, reason=reason)) from exc
