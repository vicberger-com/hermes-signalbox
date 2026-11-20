"""Loopback control API: server hardening and the bounded client (spec section 3, Control API)."""

from __future__ import annotations

import getpass
import http.client
import http.server
import json
import os
import stat
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sy_testing import write_module

from switchyard.api import (
    MAX_BODY_BYTES,
    MAX_RESPONSE_BYTES,
    ApiClient,
    ApiUnavailable,
    ControlServer,
    safe_header,
)
from switchyard.core import Core
from switchyard.errors import CapabilityDenied, SwitchyardError
from switchyard.ops import UsageError


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[ControlServer, Path]]:
    data = tmp_path / "data"
    write_module(data / "modules", "ext", isolation="subprocess")
    core = Core(data_dir=data)
    server = ControlServer(core)
    server.start()
    try:
        yield server, data
    finally:
        server.shutdown()
        core.close()


def _raw(
    server: ControlServer,
    method: str,
    path: str,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
    *,
    auth: bool = True,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    h = {"Host": f"127.0.0.1:{server.port}", "Content-Type": "application/json"}
    if auth:
        h["Authorization"] = f"Bearer {server.token}"
    h.update(headers or {})
    conn.request(method, path, body=body, headers=h)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data


# client happy path ----------------------------------------------------------------------------------------


def test_client_runs_operations(served: tuple[ControlServer, Path]) -> None:
    _, data = served
    client = ApiClient.from_data_dir(data)
    [row] = client.request("module", "list", {})
    assert row["id"] == "ext" and row["status"] == "verified"
    client.request("module", "activate", {"id": "ext"})
    assert client.request("module", "health", {"id": "ext"}) == {"ok": True, "detail": "ok"}
    client.request("module", "deactivate", {"id": "ext"})
    actors = {r["actor"] for r in client.request("audit", "tail", {"n": 20})}
    assert "api" in actors


def test_client_maps_errors(served: tuple[ControlServer, Path]) -> None:
    _, data = served
    client = ApiClient.from_data_dir(data)
    with pytest.raises(UsageError, match="missing parameter"):
        client.request("module", "activate", {})
    with pytest.raises(CapabilityDenied):
        client.request("module", "grant", {"id": "ext", "capability": "net.outbound"})
    with pytest.raises(SwitchyardError, match="unknown module"):
        client.request("module", "activate", {"id": "ghost"})


def test_health_needs_no_token(served: tuple[ControlServer, Path]) -> None:
    server, _ = served
    status, _, body = _raw(server, "GET", "/v1/health", auth=False)
    assert status == 200 and json.loads(body) == {"ok": True}


# hardening ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("headers", "auth", "expected"),
    [
        ({}, False, 401),
        ({"Authorization": "Bearer wrong"}, False, 401),
        ({"Authorization": "Basic abc"}, False, 401),
        ({"Host": "evil.example:80"}, True, 403),
        ({"Host": "127.0.0.1"}, True, 403),
        ({"Origin": "http://127.0.0.1"}, True, 403),
        ({"Origin": "null"}, True, 403),
        ({"Content-Type": "text/plain"}, True, 415),
    ],
    ids=["no-token", "wrong-token", "basic", "foreign-host", "host-without-port", "origin", "null-origin",
         "content-type"],
)  # fmt: skip
def test_request_checks(
    served: tuple[ControlServer, Path], headers: dict[str, str], auth: bool, expected: int
) -> None:
    server, _ = served
    status, _, body = _raw(server, "POST", "/v1/module/list", b"{}", headers, auth=auth)
    assert status == expected
    assert server.token not in body.decode("utf-8", "replace")


def test_localhost_host_is_accepted(served: tuple[ControlServer, Path]) -> None:
    server, _ = served
    status, _, _ = _raw(server, "POST", "/v1/module/list", b"{}", {"Host": f"localhost:{server.port}"})
    assert status == 200


@pytest.mark.parametrize(
    ("path", "body", "headers", "expected"),
    [
        ("/v1/module/list", b"[]", {}, 400),
        ("/v1/module/list", b"not json", {}, 400),
        ("/v1/module", b"{}", {}, 404),
        ("/v1/Module/List", b"{}", {}, 404),
        ("/v1/module/list/extra", b"{}", {}, 404),
        ("/v1/module/launch", b"{}", {}, 400),
        ("/v1/module/list", b"{}", {"Transfer-Encoding": "chunked"}, 400),
    ],
)
def test_bad_requests(served: tuple[ControlServer, Path], path: str, body: bytes, headers: dict[str, str],
                      expected: int) -> None:  # fmt: skip
    server, _ = served
    status, _, _ = _raw(server, "POST", path, body, headers)
    assert status == expected


def test_oversize_body_is_refused_before_reading(served: tuple[ControlServer, Path]) -> None:
    server, _ = served
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    conn.putrequest("POST", "/v1/module/list", skip_host=True)
    conn.putheader("Host", f"127.0.0.1:{server.port}")
    conn.putheader("Authorization", f"Bearer {server.token}")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
    conn.endheaders()
    assert conn.getresponse().status == 413
    conn.close()


def test_other_methods_and_paths(served: tuple[ControlServer, Path]) -> None:
    server, _ = served
    assert _raw(server, "PUT", "/v1/module/list", b"{}")[0] == 501
    assert _raw(server, "OPTIONS", "/v1/module/list")[0] == 501
    assert _raw(server, "GET", "/v1/module/list")[0] == 404


def test_response_headers(served: tuple[ControlServer, Path]) -> None:
    server, _ = served
    _, headers, _ = _raw(server, "POST", "/v1/module/list", b"{}")
    assert not any(k.startswith("access-control-") for k in headers)
    assert headers["server"] == "switchyard" and "python" not in headers["server"].lower()
    assert headers["x-content-type-options"] == "nosniff" and headers["cache-control"] == "no-store"


def test_header_values_with_line_breaks_are_refused() -> None:
    with pytest.raises(ValueError, match="line break"):
        safe_header("X-Test", "a\r\nSet-Cookie: x=1")
    with pytest.raises(ValueError, match="line break"):
        safe_header("X-\nTest", "a")
    assert safe_header("X-Test", "fine") == ("X-Test", "fine")


def test_binds_loopback_only(served: tuple[ControlServer, Path]) -> None:
    server, _ = served
    assert server.host == "127.0.0.1"
    with pytest.raises(SwitchyardError, match="loopback"):
        ControlServer(None, host="0.0.0.0")  # type: ignore[arg-type]  # noqa: S104


def test_token_rotates_and_files_are_removed(tmp_path: Path) -> None:
    data = tmp_path / "data"
    with Core(data_dir=data) as core:
        first = ControlServer(core)
        first.start()
        token1 = (data / "api.token").read_text(encoding="utf-8")
        assert token1 == first.token and int((data / "api.port").read_text(encoding="utf-8")) == first.port
        if sys.platform != "win32":
            assert stat.S_IMODE(os.stat(data / "api.token").st_mode) == 0o600
        first.shutdown()
        assert not (data / "api.token").exists() and not (data / "api.port").exists()
        second = ControlServer(core)
        second.start()
        assert second.token != token1
        second.shutdown()


# client limits --------------------------------------------------------------------------------------------


def test_client_unavailable_without_files_or_server(tmp_path: Path) -> None:
    with pytest.raises(ApiUnavailable):
        ApiClient.from_data_dir(tmp_path)
    (tmp_path / "api.port").write_text("1", encoding="utf-8")
    (tmp_path / "api.token").write_text("t", encoding="utf-8")
    with pytest.raises(ApiUnavailable):
        ApiClient.from_data_dir(tmp_path).request("module", "list", {})
    (tmp_path / "api.port").write_text("not-a-port", encoding="utf-8")
    with pytest.raises(ApiUnavailable):
        ApiClient.from_data_dir(tmp_path)


class _Huge(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(MAX_RESPONSE_BYTES + 10))
        self.end_headers()
        self.wfile.write(b'"' + b"x" * (MAX_RESPONSE_BYTES + 8) + b'"')

    def log_message(self, format: str, *args: Any) -> None:
        pass


def test_client_caps_response_size(tmp_path: Path) -> None:
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Huge)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        client = ApiClient(httpd.server_address[1], "token")
        with pytest.raises(SwitchyardError, match="too large"):
            client.request("module", "list", {})
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL check")
def test_token_file_acl_is_user_only_on_windows(served: tuple[ControlServer, Path]) -> None:
    _, data = served
    cmd = ["icacls", str(data / "api.token")]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout  # noqa: S603
    token = str(data / "api.token")
    # Lines: "<path> DOMAIN\\name:(F)" first, then "    DOMAIN\\name:(F)"; the path may contain spaces.
    principals = [line.replace(token, "").split(":(")[0].strip() for line in out.splitlines() if ":(" in line]
    # OWNER RIGHTS is the file's owner, i.e. this user; SYSTEM and Administrators can read any file anyway.
    allowed = {getpass.getuser().lower(), "system", "administrators", "owner rights"}
    assert principals and all(p.split("\\")[-1].lower() in allowed for p in principals), out
    assert "(I)" not in out, out
