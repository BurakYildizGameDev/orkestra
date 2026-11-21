from __future__ import annotations

import io
from typing import Any

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
        assert "<!DOCTYPE html>" in body.decode("utf-8")
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
