"""Loopback control API and its bounded client (spec section 3, Control API; DESIGN.md section 4, control 7).

Server: ``ThreadingHTTPServer`` bound to ``127.0.0.1`` only. Every request is checked in this order:

1. ``Host`` must be ``127.0.0.1:<port>`` or ``localhost:<port>`` (defeats DNS rebinding);
2. any ``Origin`` header is refused (the CLI is the only client; browsers send one cross-origin), and no
   CORS header is ever sent;
3. ``GET /v1/health`` is answered without a token; everything else is ``POST /v1/<noun>/<verb>``;
4. ``Authorization: Bearer <token>`` compared with ``hmac.compare_digest``; the token is random per start and
   written to ``<data_dir>/api.token`` with user-only permissions;
5. ``Content-Type: application/json``, no ``Transfer-Encoding``, ``Content-Length`` <= ``MAX_BODY_BYTES``
   (checked before reading), body a JSON object.

Responses use fixed headers only; ``safe_header`` rejects CR/LF (CPython's ``send_header`` does not). The
``Server`` header does not reveal the Python version. Request lines are never logged. A socket timeout stops
slow clients holding threads.

Client: reads ``api.port`` and ``api.token``, talks to ``127.0.0.1`` only, and reads at most
``MAX_RESPONSE_BYTES`` (an unbounded read trusts ``Content-Length``; CVE-2025-13836 class).
"""

from __future__ import annotations

import hmac
import http.client
import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from switchyard.errors import CapabilityDenied, SwitchyardError
from switchyard.ops import UsageError

MAX_BODY_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
SOCKET_TIMEOUT_S = 10.0
CLIENT_TIMEOUT_S = 60.0
LOOPBACK = "127.0.0.1"
_ROUTE = re.compile(r"/v1/([a-z]+)/([a-z_]+)\Z")
_STATUS_ERRORS: dict[int, type[SwitchyardError]] = {400: UsageError, 403: CapabilityDenied}


class ApiUnavailable(SwitchyardError):
    """No running daemon could be reached."""


def safe_header(key: str, value: str) -> tuple[str, str]:
    if any(c in key or c in value for c in "\r\n"):
        raise ValueError("header contains a line break")
    return key, value


def _write_private(path: Path, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    if os.name == "posix":
        os.chmod(path, 0o600)
    else:
        _restrict_windows_acl(path)


def _restrict_windows_acl(path: Path) -> None:
    """Replace the inherited ACL with one entry for the current user. Fails closed: the token is deleted."""
    import getpass
    import shutil
    import subprocess  # nosec B404

    user = getpass.getuser()
    exe = shutil.which("icacls")
    try:
        if exe is None:
            raise OSError("icacls not found")
        # Fixed argv, no shell; the user name comes from this process's own account.
        subprocess.run(  # noqa: S603 # nosec B603
            [exe, str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True, timeout=30, check=True,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError) as exc:
        path.unlink(missing_ok=True)
        raise SwitchyardError(f"could not restrict access to {path.name}: {type(exc).__name__}") from None


class _Handler(BaseHTTPRequestHandler):
    server_version = "switchyard"
    sys_version = ""
    timeout = SOCKET_TIMEOUT_S
    control: ControlServer  # set on the subclass created per server

    def log_message(self, format: str, *args: Any) -> None:  # request lines can carry data; never log them
        pass

    def version_string(self) -> str:
        return self.server_version

    def send_header(self, keyword: str, value: str) -> None:
        super().send_header(*safe_header(keyword, value))

    def _reply(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, status: int, error: str, message: str = "") -> None:
        self._drain()
        self._reply(status, {"ok": False, "error": error, "message": message})

    def _drain(self) -> None:
        """Discard an unread request body within the size limit before an early reply; replying with unread
        bytes in the socket makes some stacks (Windows) reset the connection before the client reads."""
        if self.command != "POST" or getattr(self, "_body_read", False):
            return
        self._body_read = True
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return
        if 0 < length <= MAX_BODY_BYTES and "Transfer-Encoding" not in self.headers:
            self.rfile.read(length)

    def _origin_ok(self) -> bool:
        port = self.control.port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self._fail(403, "forbidden", "unexpected Host header")
            return False
        if "Origin" in self.headers:
            self._fail(403, "forbidden", "cross-origin requests are not accepted")
            return False
        return True

    def do_GET(self) -> None:
        if not self._origin_ok():
            return
        if self.path == "/v1/health":
            self._reply(200, {"ok": True})
        else:
            self._fail(404, "not_found")

    def do_POST(self) -> None:
        if not self._origin_ok():
            return
        auth = self.headers.get("Authorization", "")
        expected = f"Bearer {self.control.token}"
        if not hmac.compare_digest(auth.encode("utf-8", "replace"), expected.encode("utf-8")):
            self._fail(401, "unauthorized")
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self._fail(415, "unsupported_media_type", "use application/json")
            return
        if "Transfer-Encoding" in self.headers:
            self._fail(400, "bad_request", "Transfer-Encoding is not accepted; send Content-Length")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._fail(411, "length_required")
            return
        if not 0 <= length <= MAX_BODY_BYTES:
            self._fail(413, "too_large", f"body limit is {MAX_BODY_BYTES} bytes")
            return
        route = _ROUTE.match(self.path)
        if route is None:
            self._fail(404, "not_found")
            return
        self._body_read = True
        try:
            params = json.loads(self.rfile.read(length) or b"{}")
        except (UnicodeDecodeError, ValueError):
            self._fail(400, "bad_request", "body is not valid JSON")
            return
        if not isinstance(params, dict):
            self._fail(400, "bad_request", "body must be a JSON object")
            return
        self._dispatch(route.group(1), route.group(2), params)

    def _dispatch(self, noun: str, verb: str, params: dict[str, Any]) -> None:
        try:
            result = self.control.core.run(noun, verb, params, actor="api")
        except UsageError as exc:
            self._fail(400, "usage", str(exc))
        except CapabilityDenied as exc:
            self._fail(403, "capability_denied", str(exc))
        except SwitchyardError as exc:
            self._fail(409, type(exc).__name__, str(exc))
        except Exception as exc:  # never echo unexpected messages: they may carry data
            self._fail(500, type(exc).__name__)
        else:
            self._reply(200, {"ok": True, "result": result})


class ControlServer:
    def __init__(self, core: Any, *, port: int = 0, host: str = LOOPBACK) -> None:
        if host != LOOPBACK:
            raise SwitchyardError("the control API binds to loopback (127.0.0.1) only")
        self.core = core
        self.host = host
        self.token = secrets.token_urlsafe(32)
        handler = type("Handler", (_Handler,), {"control": self})
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._httpd.daemon_threads = True
        self.port: int = self._httpd.server_address[1]
        self._thread: threading.Thread | None = None

    def _files(self) -> tuple[Path, Path]:
        return self.core.data_dir / "api.port", self.core.data_dir / "api.token"

    def start(self) -> None:
        port_file, token_file = self._files()
        _write_private(token_file, self.token)
        _write_private(port_file, str(self.port))
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()

    def shutdown(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        for path in self._files():
            path.unlink(missing_ok=True)


class ApiClient:
    def __init__(self, port: int, token: str) -> None:
        self.port = port
        self._token = token

    @classmethod
    def from_data_dir(cls, data_dir: Path) -> ApiClient:
        try:
            port = int((data_dir / "api.port").read_text(encoding="utf-8").strip())
            token = (data_dir / "api.token").read_text(encoding="utf-8").strip()
        except (OSError, ValueError) as exc:
            raise ApiUnavailable(f"no running daemon for {data_dir}") from exc
        return cls(port, token)

    def request(self, noun: str, verb: str, params: dict[str, Any]) -> Any:
        body = json.dumps(params).encode("utf-8")
        conn = http.client.HTTPConnection(LOOPBACK, self.port, timeout=CLIENT_TIMEOUT_S)
        try:
            conn.request("POST", f"/v1/{noun}/{verb}", body=body, headers={
                "Host": f"{LOOPBACK}:{self.port}", "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            })  # fmt: skip
            resp = conn.getresponse()
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
        except (ConnectionError, TimeoutError, OSError) as exc:
            raise ApiUnavailable(
                f"daemon on port {self.port} is not reachable: {type(exc).__name__}"
            ) from None
        finally:
            conn.close()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise SwitchyardError(f"API response too large (limit {MAX_RESPONSE_BYTES} bytes)")
        try:
            payload = json.loads(raw)
        except ValueError:
            raise SwitchyardError(f"API returned HTTP {resp.status} with a non-JSON body") from None
        if isinstance(payload, dict) and payload.get("ok") is True:
            return payload.get("result")
        message = str(payload.get("message", "")) if isinstance(payload, dict) else ""
        raise _STATUS_ERRORS.get(resp.status, SwitchyardError)(message or f"API error HTTP {resp.status}")
