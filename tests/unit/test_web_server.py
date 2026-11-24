from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Any

import keyring
import pytest

from orkestra import __version__
from orkestra.web.server import ServerConfig, WebHandler, WebServer, create_server


class MockSocket:
    def __init__(self, request_bytes: bytes) -> None:
        self.rfile = io.BytesIO(request_bytes)
        self.wfile = io.BytesIO()

    def makefile(self, mode: str, *args: Any, **kwargs: Any) -> io.BytesIO:
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, data: bytes) -> None:
        self.wfile.write(data)


def simulate_request(
    server: WebServer,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> tuple[int, dict[str, str], bytes]:
    port = server.server_port
    hdrs = {"Host": f"127.0.0.1:{port}"}
    if body:
        hdrs["Content-Length"] = str(len(body))
    if headers:
        hdrs.update(headers)

    req_lines = [f"{method} {path} HTTP/1.1"]
    for k, v in hdrs.items():
        req_lines.append(f"{k}: {v}")
    raw_request = "\r\n".join(req_lines).encode("utf-8") + b"\r\n\r\n" + body

    sock = MockSocket(raw_request)
    WebHandler(sock, ("127.0.0.1", 54321), server)  # type: ignore

    raw_response = sock.wfile.getvalue()
    parts = raw_response.split(b"\r\n\r\n", 1)
    header_part = parts[0].decode("utf-8", errors="replace")
    body_part = parts[1] if len(parts) > 1 else b""

    lines = header_part.split("\r\n")
    status_line = lines[0]
    status_code = int(status_line.split(" ")[1])

    resp_headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            hk, hv = line.split(":", 1)
            resp_headers[hk.strip().lower()] = hv.strip()

    return status_code, resp_headers, body_part


def test_server_binds_to_127_0_0_1_only() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="tok"))
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_server_generates_random_token_if_empty() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0))
    try:
        assert server.token
        assert len(server.token) >= 16
    finally:
        server.server_close()


def test_health_with_query_token() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="test-tok"))
    try:
        code, headers, body = simulate_request(server, "GET", f"/api/health?token={server.token}")
        assert code == 200
        assert "application/json" in headers.get("content-type", "")
        import json

        data = json.loads(body.decode("utf-8"))
        assert data["ok"] is True
        assert data["version"] == __version__
    finally:
        server.server_close()


def test_health_with_bearer_token() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="test-tok"))
    try:
        code, _, body = simulate_request(
            server,
            "GET",
            "/api/health",
            headers={"Authorization": f"Bearer {server.token}"},
        )
        assert code == 200
        import json

        assert json.loads(body.decode("utf-8"))["ok"] is True
    finally:
        server.server_close()


def test_health_with_x_orkestra_token() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="test-tok"))
    try:
        code, _, body = simulate_request(
            server,
            "GET",
            "/api/health",
            headers={"X-Orkestra-Token": server.token},
        )
        assert code == 200
        import json

        assert json.loads(body.decode("utf-8"))["ok"] is True
    finally:
        server.server_close()


def test_health_without_token_returns_403() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="test-tok"))
    try:
        code, _, body = simulate_request(server, "GET", "/api/health")
        assert code == 403
        import json

        assert "error" in json.loads(body.decode("utf-8"))
    finally:
        server.server_close()


def test_health_with_wrong_token_returns_403() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="test-tok"))
    try:
        code, _, body = simulate_request(server, "GET", "/api/health?token=bad-token")
        assert code == 403
        import json

        assert "error" in json.loads(body.decode("utf-8"))
    finally:
        server.server_close()


def test_root_page_with_token() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="test-tok"))
    try:
        code, headers, body = simulate_request(server, "GET", f"/?token={server.token}")
        assert code == 200
        assert "text/html" in headers.get("content-type", "")
        html_text = body.decode("utf-8")
        assert "<!DOCTYPE html>" in html_text
        assert "btn-test-all" in html_text
        assert "btn-notify-test" in html_text
        assert "providers-container" in html_text
        assert "status-card" in html_text
    finally:
        server.server_close()


def test_root_page_without_token_returns_403() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="test-tok"))
    try:
        code, _, _ = simulate_request(server, "GET", "/")
        assert code == 403
    finally:
        server.server_close()


def test_invalid_host_header_rejected() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="test-tok"))
    try:
        code, _, body = simulate_request(
            server,
            "GET",
            f"/api/health?token={server.token}",
            headers={"Host": "attacker.com"},
        )
        assert code == 403
        import json

        assert "error" in json.loads(body.decode("utf-8"))
    finally:
        server.server_close()


def test_cross_origin_request_rejected() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="test-tok"))
    try:
        code, _, body = simulate_request(
            server,
            "GET",
            f"/api/health?token={server.token}",
            headers={"Origin": "http://evil.example.com"},
        )
        assert code == 403
        import json

        assert "error" in json.loads(body.decode("utf-8"))
    finally:
        server.server_close()


def test_cors_header_is_not_present() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="test-tok"))
    try:
        code, headers, _ = simulate_request(server, "GET", f"/api/health?token={server.token}")
        assert code == 200
        assert "access-control-allow-origin" not in headers
    finally:
        server.server_close()


def test_not_found_endpoint() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="test-tok"))
    try:
        code, _, _ = simulate_request(server, "GET", f"/api/nonexistent?token={server.token}")
        assert code == 404
    finally:
        server.server_close()


def test_server_refuses_a_host_other_than_127_0_0_1() -> None:
    import pytest

    from orkestra.errors import InternalError

    with pytest.raises(InternalError):
        create_server(ServerConfig(host="0.0.0.0", port=0, token="tok"))


def test_non_ascii_token_returns_403_instead_of_dropping_the_connection() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="test-tok"))
    try:
        code, _, _ = simulate_request(server, "GET", "/api/health?token=%C3%A9")
        assert code == 403
        code, _, _ = simulate_request(
            server, "GET", "/api/health", headers={"X-Orkestra-Token": "é"}
        )
        assert code == 403
    finally:
        server.server_close()


def test_busy_port_is_a_usage_error_and_never_shares_the_port() -> None:
    import pytest

    from orkestra.errors import UsageError

    first = create_server(ServerConfig(host="127.0.0.1", port=0, token="tok"))
    try:
        with pytest.raises(UsageError) as exc_info:
            create_server(ServerConfig(host="127.0.0.1", port=first.server_port, token="tok"))
        assert str(first.server_port) in exc_info.value.message
    finally:
        first.server_close()


def test_responses_are_not_cached_framed_or_leaked_by_referrer() -> None:
    server = create_server(ServerConfig(host="127.0.0.1", port=0, token="test-tok"))
    try:
        for path in (f"/?token={server.token}", f"/api/health?token={server.token}", "/api/health"):
            _, headers, _ = simulate_request(server, "GET", path)
            assert headers.get("cache-control") == "no-store"
            assert headers.get("referrer-policy") == "no-referrer"
            assert headers.get("x-frame-options") == "DENY"
            assert headers.get("x-content-type-options") == "nosniff"
    finally:
        server.server_close()


def test_get_home_api_returns_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from orkestra.config.schema import Config, ModelSpec, OllamaProvider
    from orkestra.state import consent, db

    db_file = tmp_path / "state.db"
    monkeypatch.setattr("orkestra.paths.state_db_path", lambda: db_file)
    cfg_file = tmp_path / "config.yaml"
    cfg = Config(
        version=1,
        providers={
            "ollama": OllamaProvider(
                type="ollama",
                base_url="http://localhost:11434",
                models=[ModelSpec(id="m1", tier=1)],
            )
        },
    )
    cfg_file.write_text(
        "version: 1\nproviders:\n  ollama:\n    type: ollama\n"
        "    base_url: http://localhost:11434\n    models:\n      - id: m1\n        tier: 1\n",
        encoding="utf-8",
    )

    with db.connect(db_file) as conn:
        consent.grant(conn, "ollama", cfg.providers["ollama"], db.local_now())

    server = create_server(
        ServerConfig(host="127.0.0.1", port=0, token="test-tok", config_path=cfg_file)
    )
    try:
        code, headers, body = simulate_request(server, "GET", f"/api/home?token={server.token}")
        assert code == 200
        assert "application/json" in headers.get("content-type", "")
        data = json.loads(body.decode("utf-8"))
        assert "status" in data
        assert "providers" in data
        assert len(data["providers"]) == 1
        assert data["providers"][0]["name"] == "ollama"
        assert "today" in data
        assert "pending" in data
        assert "next_step" in data
    finally:
        server.server_close()


def test_post_doctor_triggers_in_background(tmp_path: Path) -> None:
    import json
    import threading
    import time

    from orkestra.doctor import Check, DoctorReport

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("version: 1\nproviders: {}\n", encoding="utf-8")

    server = create_server(
        ServerConfig(host="127.0.0.1", port=0, token="test-tok", config_path=cfg_file)
    )
    try:
        doctor_called = threading.Event()
        doctor_proceed = threading.Event()

        def fake_run_doctor(**kwargs: Any) -> DoctorReport:
            doctor_called.set()
            doctor_proceed.wait(timeout=5.0)
            return DoctorReport(checks=(Check("config", "ok", "mock ok"),))

        server.doctor_runner = fake_run_doctor  # type: ignore

        code, _, body = simulate_request(server, "POST", f"/api/doctor?token={server.token}")
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert data["status"] in ("running", "done")

        # Non-blocking check
        code_h, _, body_h = simulate_request(server, "GET", f"/api/health?token={server.token}")
        assert code_h == 200
        assert json.loads(body_h.decode("utf-8"))["ok"] is True

        assert doctor_called.wait(timeout=5.0)
        doctor_proceed.set()

        deadline = time.monotonic() + 5.0
        data_d = {}
        while time.monotonic() < deadline:
            code_d, _, body_d = simulate_request(server, "GET", f"/api/doctor?token={server.token}")
            assert code_d == 200
            data_d = json.loads(body_d.decode("utf-8"))
            if data_d.get("status") == "done":
                break
            time.sleep(0.02)
        assert data_d.get("status") == "done"
        assert len(data_d.get("checks", [])) >= 1
    finally:
        server.server_close()


def test_post_notify_test(tmp_path: Path) -> None:
    import json

    from orkestra.notify.notify import Delivery

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("version: 1\nnotify:\n  desktop: true\nproviders: {}\n", encoding="utf-8")

    server = create_server(
        ServerConfig(host="127.0.0.1", port=0, token="test-tok", config_path=cfg_file)
    )
    try:

        def fake_notify_send(*args: Any, **kwargs: Any) -> list[Delivery]:
            return [Delivery(channel="desktop", state="sent")]

        server.notify_sender = fake_notify_send  # type: ignore

        code, _, body = simulate_request(server, "POST", f"/api/notify/test?token={server.token}")
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert data["ok"] is True
        assert "deliveries" in data
    finally:
        server.server_close()


def test_doctor_error_returns_failed_and_does_not_lock(tmp_path: Path) -> None:
    import json
    import time

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("version: 1\nproviders: {}\n", encoding="utf-8")

    server = create_server(
        ServerConfig(host="127.0.0.1", port=0, token="test-tok", config_path=cfg_file)
    )
    try:

        def failing_doctor(**kwargs: Any) -> Any:
            raise RuntimeError("Doctor crash test")

        server.doctor_runner = failing_doctor  # type: ignore

        code, _, _ = simulate_request(server, "POST", f"/api/doctor?token={server.token}")
        assert code == 200

        deadline = time.monotonic() + 5.0
        data_d = {}
        while time.monotonic() < deadline:
            code_d, _, body_d = simulate_request(server, "GET", f"/api/doctor?token={server.token}")
            assert code_d == 200
            data_d = json.loads(body_d.decode("utf-8"))
            if data_d.get("status") == "failed":
                break
            time.sleep(0.02)

        assert data_d.get("status") == "failed"
        assert "Doctor crash test" in data_d.get("error", "")
    finally:
        server.server_close()


def test_doctor_new_run_fails_after_previous_success(tmp_path: Path) -> None:
    import json
    import time

    from orkestra.doctor import Check, DoctorReport

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("version: 1\nproviders: {}\n", encoding="utf-8")

    server = create_server(
        ServerConfig(host="127.0.0.1", port=0, token="test-tok", config_path=cfg_file)
    )
    try:
        # Prepopulate with a previous success report
        server.doctor_report = DoctorReport(checks=(Check("config", "ok", "previous ok"),))

        def failing_doctor(**kwargs: Any) -> Any:
            raise RuntimeError("New run failed")

        server.doctor_runner = failing_doctor  # type: ignore

        code, _, _ = simulate_request(server, "POST", f"/api/doctor?token={server.token}")
        assert code == 200

        deadline = time.monotonic() + 5.0
        data_d = {}
        while time.monotonic() < deadline:
            code_d, _, body_d = simulate_request(server, "GET", f"/api/doctor?token={server.token}")
            assert code_d == 200
            data_d = json.loads(body_d.decode("utf-8"))
            if data_d.get("status") == "failed":
                break
            time.sleep(0.02)

        assert data_d.get("status") == "failed"
        assert data_d.get("status") != "done"
        assert "New run failed" in data_d.get("error", "")
    finally:
        server.server_close()


def test_render_home_html_no_inner_html_injection_and_escaped() -> None:
    from orkestra.web.ui import render_home_html

    html = render_home_html("my-test-token")
    # Verify that innerHTML is not used to insert provider data or claude windows
    assert "textContent" in html or "esc(" in html
    assert "pCont.innerHTML" not in html
    assert "cont.innerHTML = data.claude_windows" not in html


def test_render_home_html_translation_escaping(monkeypatch: pytest.MonkeyPatch) -> None:
    import orkestra.web.ui as ui_mod
    from orkestra.web.ui import render_home_html

    # Monkeypatch t to return quotes, backslashes, and </script> tags
    malicious = 'Test "quote" \\slash </script><script>alert(1)</script>'
    monkeypatch.setattr(ui_mod, "t", lambda key, **kwargs: malicious)

    html = render_home_html("safe-tok")
    # </script> should not appear unescaped inside <script> blocks
    parts = html.split("<script>")
    for script_part in parts[1:]:
        content = script_part.split("</script>")[0]
        assert "<script>" not in content
        assert "alert(1)" not in content or "\\u003c" in content or "\\/" in content


def test_render_home_html_i18n_and_lang() -> None:
    from orkestra.i18n import get_language
    from orkestra.web.ui import render_home_html

    current_lang = get_language()
    html = render_home_html("test-tok")
    assert f'lang="{current_lang}"' in html
    assert "I18N =" in html or "const I18N" in html


def test_ui_css_has_doc_info_style() -> None:
    from orkestra.web.ui import render_home_html

    html = render_home_html("test-tok")
    assert ".doc-info" in html


def test_team_api_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    db_file = tmp_path / "state.db"
    monkeypatch.setattr("orkestra.paths.state_db_path", lambda: db_file)
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "version: 1\ndefaults:\n  chief: claude\n"
        "chiefs:\n  claude:\n    launch: ['claude']\n  agy:\n    launch: ['agy']\n"
        "providers:\n  ollama:\n    type: ollama\n"
        "    base_url: http://localhost:11434\n    models:\n      - id: m1\n        tier: 1\n",
        encoding="utf-8",
    )

    server = create_server(
        ServerConfig(host="127.0.0.1", port=0, token="test-tok", config_path=cfg_file)
    )
    try:
        # 1. Unauthorized GET /api/team
        code, _, _ = simulate_request(server, "GET", "/api/team")
        assert code == 403

        # 2. Authorized GET /api/team
        code, _headers, body = simulate_request(server, "GET", f"/api/team?token={server.token}")
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert data["patron"] == "claude"
        assert len(data["chiefs"]) == 3
        assert len(data["workers"]) == 1
        assert data["workers"][0]["name"] == "ollama"

        # 3. POST /api/team/patron
        code, _, body = simulate_request(
            server,
            "POST",
            f"/api/team/patron?token={server.token}",
            body=json.dumps({"chief": "agy"}).encode("utf-8"),
        )
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert data["patron"] == "agy"

        # 4. POST /api/team/worker/toggle
        code, _, body = simulate_request(
            server,
            "POST",
            f"/api/team/worker/toggle?token={server.token}",
            body=json.dumps({"name": "ollama", "enabled": False}).encode("utf-8"),
        )
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert data["workers"][0]["enabled"] is False

        # 5. POST /api/team/worker/tier
        code, _, body = simulate_request(
            server,
            "POST",
            f"/api/team/worker/tier?token={server.token}",
            body=json.dumps({"name": "ollama", "tier": 2}).encode("utf-8"),
        )
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert data["workers"][0]["tier"] == 2

        # 6. POST /api/team/worker/model
        code, _, body = simulate_request(
            server,
            "POST",
            f"/api/team/worker/model?token={server.token}",
            body=json.dumps({"name": "ollama", "model": "new-model"}).encode("utf-8"),
        )
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert data["workers"][0]["selected_model"] == "new-model"

        # 7. POST /api/team/worker/add (openai_compat)
        code, _, body = simulate_request(
            server,
            "POST",
            f"/api/team/worker/add?token={server.token}",
            body=json.dumps(
                {
                    "name": "cloud-api",
                    "type": "openai_compat",
                    "base_url": "https://api.example.test/v1",
                    "model": "deepseek-v3",
                    "api_key_env": "CLOUD_API_KEY",
                    "tier": 2,
                }
            ).encode("utf-8"),
        )
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        worker_names = [w["name"] for w in data["workers"]]
        assert "cloud-api" in worker_names

        # A string must not be coerced to True and silently enable overwrite behavior.
        code, _, _ = simulate_request(
            server,
            "POST",
            f"/api/team/worker/add?token={server.token}",
            body=json.dumps(
                {
                    "name": "invalid-force",
                    "type": "openai_compat",
                    "base_url": "https://api.example.test/v1",
                    "model": "model",
                    "api_key_env": "CLOUD_API_KEY",
                    "force": "false",
                }
            ).encode("utf-8"),
        )
        assert code == 400
        from orkestra.config.loader import load_config

        assert "invalid-force" not in load_config(cfg_file).config.providers

        # 8. POST /api/team/worker/reorder
        code, _, body = simulate_request(
            server,
            "POST",
            f"/api/team/worker/reorder?token={server.token}",
            body=json.dumps({"names": ["cloud-api", "ollama"]}).encode("utf-8"),
        )
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert [w["name"] for w in data["workers"]] == ["cloud-api", "ollama"]

        # 9. POST /api/team/consent
        code, _, body = simulate_request(
            server,
            "POST",
            f"/api/team/consent?token={server.token}",
            body=json.dumps({"name": "cloud-api"}).encode("utf-8"),
        )
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        cloud_worker = next(w for w in data["workers"] if w["name"] == "cloud-api")
        assert cloud_worker["consent_state"] == "granted"

        # 10. POST /api/team/worker/remove
        code, _, body = simulate_request(
            server,
            "POST",
            f"/api/team/worker/remove?token={server.token}",
            body=json.dumps({"name": "cloud-api"}).encode("utf-8"),
        )
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert "cloud-api" not in [w["name"] for w in data["workers"]]
    finally:
        server.server_close()


def test_team_api_serializes_concurrent_config_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    db_file = tmp_path / "state.db"
    monkeypatch.setattr("orkestra.paths.state_db_path", lambda: db_file)
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "version: 1\ndefaults:\n  chief: claude\n"
        "chiefs:\n  claude:\n    launch: ['claude']\n  agy:\n    launch: ['agy']\n"
        "providers: {}\n",
        encoding="utf-8",
    )
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    second_started = threading.Event()

    def hold_first_write(_path: Path, chief: str) -> None:
        if chief == "agy":
            first_entered.set()
            assert release_first.wait(timeout=3)
        else:
            second_entered.set()

    monkeypatch.setattr("orkestra.chief.team.set_patron", hold_first_write)
    server = create_server(ServerConfig(port=0, token="tok", config_path=cfg_file))
    results: list[int] = []

    def post(chief: str, *, started: threading.Event | None = None) -> None:
        if started is not None:
            started.set()
        body = json.dumps({"chief": chief}).encode("utf-8")
        code, _, _ = simulate_request(server, "POST", "/api/team/patron?token=tok", body=body)
        results.append(code)

    first = threading.Thread(target=post, args=("agy",))
    second = threading.Thread(target=post, args=("claude",), kwargs={"started": second_started})
    try:
        first.start()
        assert first_entered.wait(timeout=2)
        second.start()
        assert second_started.wait(timeout=2)
        assert not second_entered.wait(timeout=0.2)
        release_first.set()
        first.join(timeout=3)
        second.join(timeout=3)
        assert not first.is_alive() and not second.is_alive()
        assert second_entered.is_set()
        assert results == [200, 200]
    finally:
        release_first.set()
        server.server_close()


def test_keys_api_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    passwords: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "get_password", lambda s, u: passwords.get((s, u)))
    monkeypatch.setattr(keyring, "set_password", lambda s, u, p: passwords.update({(s, u): p}))

    def fake_del(s: str, u: str) -> None:
        passwords.pop((s, u), None)

    monkeypatch.setattr(keyring, "delete_password", fake_del)

    cfg_content = """\
version: 1
language: en
providers:
  remote:
    type: openai_compat
    base_url: https://api.example.test/v1
    api_key_env: REMOTE_KEY
    models:
      - id: m1
        tier: 1
"""
    cfg_file = tmp_path / "orkestra.yaml"
    cfg_file.write_text(cfg_content, encoding="utf-8")

    server = create_server(ServerConfig(port=0, config_path=cfg_file))
    try:
        # 1. 403 when token missing
        code, _, _ = simulate_request(server, "GET", "/api/keys")
        assert code == 403

        # 2. GET /api/keys returns initial state
        code, _, body = simulate_request(server, "GET", f"/api/keys?token={server.token}")
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert len(data["keys"]) == 1
        assert data["keys"][0]["var_name"] == "REMOTE_KEY"
        assert data["keys"][0]["source"] == "none"
        assert data["keys"][0]["defined"] is False
        assert data["keys"][0]["providers"] == ["remote"]

        # 3. POST /api/keys/set without token is 403
        code, _, _ = simulate_request(
            server,
            "POST",
            "/api/keys/set",
            body=json.dumps({"var_name": "REMOTE_KEY", "key": "secret-val"}).encode("utf-8"),
        )
        assert code == 403

        # 4. POST /api/keys/set saves to keyring
        secret_val = "ultra-secret-test-token-777"
        code, _, body = simulate_request(
            server,
            "POST",
            f"/api/keys/set?token={server.token}",
            body=json.dumps({"var_name": "REMOTE_KEY", "key": secret_val}).encode("utf-8"),
        )
        assert code == 200
        assert secret_val not in body.decode("utf-8")  # secret NEVER exposed in response
        data = json.loads(body.decode("utf-8"))
        assert data["ok"] is True
        assert data["keys"][0]["source"] == "keyring"
        assert data["keys"][0]["defined"] is True
        assert passwords.get(("orkestra", "REMOTE_KEY")) == secret_val

        # 5. POST /api/keys/delete removes from keyring
        code, _, body = simulate_request(
            server,
            "POST",
            f"/api/keys/delete?token={server.token}",
            body=json.dumps({"var_name": "REMOTE_KEY"}).encode("utf-8"),
        )
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert data["keys"][0]["source"] == "none"
        assert data["keys"][0]["defined"] is False
        assert passwords.get(("orkestra", "REMOTE_KEY")) is None

        # 6. POST /api/keys/set with invalid name returns 400
        code, _, body = simulate_request(
            server,
            "POST",
            f"/api/keys/set?token={server.token}",
            body=json.dumps({"var_name": "invalid-name!", "key": "val"}).encode("utf-8"),
        )
        assert code == 400
    finally:
        server.server_close()
