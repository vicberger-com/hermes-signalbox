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
import sys
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
CONNECT_TIMEOUT_S = 0.5  # loopback: a refused or dead port must not cost seconds (H1 D-9)
LOOPBACK = "127.0.0.1"
_ROUTE = re.compile(r"/v1/([a-z]+)/([a-z_]+)\Z")
_STATUS_ERRORS: dict[int, type[SwitchyardError]] = {400: UsageError, 403: CapabilityDenied}


class ApiUnavailable(SwitchyardError):
    """No running daemon could be reached."""


class ApiRestricted(CapabilityDenied):
    """The hosting process's API does not serve this operation (the restricted profile Hermes runs)."""


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
    """Drop the inherited ACL; only this user (plus SYSTEM/Administrators, if set explicitly) keeps access.

    Fails closed: the token file is deleted.
    """
    import getpass
    import subprocess  # nosec B404

    user = getpass.getuser()
    from switchyard.process import system_program

    exe = system_program("icacls")
    try:
        if exe is None:
            raise OSError("icacls not found")
        # Fixed argv, no shell; the user name comes from this process's own account.
        subprocess.run(  # noqa: S603 # nosec B603
            # Drop inherited entries, grant this user, and remove broad groups (Everyone, Authenticated Users,
            # Users) in case they were set explicitly. SYSTEM and Administrators can read any file anyway.
            [exe, str(path), "/inheritance:r", "/grant:r", f"{user}:F",
             "/remove:g", "*S-1-1-0", "*S-1-5-11", "*S-1-5-32-545"],
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
        if getattr(self, "_body_read", False):
            return
        self._body_read = True
        if "Transfer-Encoding" not in self.headers:
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return
            if 0 < length <= MAX_BODY_BYTES:
                self.rfile.read(length)
        else:  # unknown length (usually no Content-Length at all): discard what arrives, briefly, bounded
            self.connection.settimeout(0.5)
            remaining = MAX_BODY_BYTES
            try:
                while remaining > 0:
                    chunk = self.rfile.read1(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except OSError:
                pass  # timed out: nothing more is coming

    def _origin_ok(self) -> bool:
        port = self.control.port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self._fail(403, "forbidden", "unexpected Host header")
            return False
        if "Origin" in self.headers:
            self._fail(403, "forbidden", "cross-origin requests are not accepted")
            return False
        return True

    def _unsupported(self) -> None:
        if self._origin_ok():  # every request is checked, whatever the method (H1 B-20)
            self._fail(501, "not_implemented")

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _unsupported  # drain the body, reply 501 as JSON

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
        core = self.control.core
        redact = core.redactor.redact
        actor = self.control.actor_for(noun, verb, params)
        if actor is None:
            # 1.1 S-4: the restricted profile runs inside Hermes; name the routes that do work.
            self._fail(
                403,
                NOT_SERVED,
                (
                    f"'{noun} {verb}' is not served by the Switchyard API inside Hermes: run it as "
                    f"/switchyard {noun} {verb} in a Hermes chat, "
                    "or stop Hermes and use 'switchyard api serve'"
                ),
            )
            return
        try:
            result = core.redactor.redact_obj(core.run(noun, verb, params, actor=actor))  # M9: panels too
        except UsageError as exc:
            self._fail(400, "usage", redact(str(exc)))
        except CapabilityDenied as exc:
            self._fail(403, "capability_denied", redact(str(exc)))
        except SwitchyardError as exc:
            self._fail(409, type(exc).__name__, redact(str(exc)))
        except Exception as exc:  # never echo unexpected messages: they may carry data
            self._fail(500, type(exc).__name__)
        else:
            self._reply(200, {"ok": True, "result": result})


# Operations the dashboard profile serves (M9 review): reads, module lifecycle on/off, reports, and the inbox
# actions. Grants, modes, installs, updates, removal and config are CLI-only. Any other module action runs as
# the model actor, so only read-only actions succeed.
DASHBOARD_OPS = frozenset({
    ("module", "list"), ("module", "show"), ("module", "panel"), ("module", "activate"),
    ("module", "deactivate"), ("module", "action"), ("report", "show"), ("audit", "tail"),
    ("audit", "verify"), ("host", "profile"), ("module", "health"),
})  # fmt: skip
NOT_SERVED = "not_served"
DASHBOARD_ACTIONS = frozenset({("inbox", "list"), ("inbox", "ack"), ("inbox", "ack_all")})


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False  # Windows SO_REUSEADDR would let a second socket bind a held port (M9 review)

    def handle_error(self, request: Any, client_address: Any) -> None:
        """No tracebacks (H1 B-24): a dropped connection is normal; anything else is one line, class only."""
        exc = sys.exc_info()[1]
        if exc is None or isinstance(exc, ConnectionError | TimeoutError):
            return
        sys.stderr.write(f"switchyard API: request failed ({type(exc).__name__})\n")


class ControlServer:
    def __init__(self, core: Any, *, port: int = 0, host: str = LOOPBACK, profile: str = "full") -> None:
        if host != LOOPBACK:
            raise SwitchyardError("the control API binds to loopback (127.0.0.1) only")
        if profile not in ("full", "dashboard"):
            raise SwitchyardError("profile must be 'full' or 'dashboard'")
        self.core = core
        self.host = host
        self.profile = profile
        self.token = secrets.token_urlsafe(32)
        handler = type("Handler", (_Handler,), {"control": self})
        self._httpd = _Server((host, port), handler)
        self._httpd.daemon_threads = True
        self.port: int = self._httpd.server_address[1]
        self._thread: threading.Thread | None = None

    def actor_for(self, noun: str, verb: str, params: dict[str, Any]) -> str | None:
        """Who a request runs as, or ``None`` when this server does not offer it. ``switchyard serve`` (full)
        is the operator's own CLI transport; the copy Hermes starts for the dashboard is ``dashboard``: a
        token reachable from inside Hermes must not grant capabilities or change config (M9 review)."""
        if self.profile == "full":
            return "api"
        if (noun, verb) not in DASHBOARD_OPS:
            return None
        if (noun, verb) == ("module", "action"):
            return "api" if (params.get("id"), params.get("action")) in DASHBOARD_ACTIONS else "hermes"
        return "api"

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


def clear_stale_files(data_dir: Path) -> bool:
    """True when no process hosts ``data_dir`` (nobody holds ``host.lock``); leftover ``api.port`` and
    ``api.token`` from a daemon that died are then removed, under the lock, so no client sends the token to
    whatever listens on that port now (H1 D-9). False when a hosting process runs."""
    from switchyard.hostlock import HostLock

    if not data_dir.is_dir():
        return True
    lock = HostLock(data_dir / "host.lock")
    try:
        if not lock.acquire():
            return False
    except OSError:
        return False  # cannot tell: leave the files alone
    try:
        for name in ("api.port", "api.token"):
            (data_dir / name).unlink(missing_ok=True)
    finally:
        lock.release()
    return True


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
        conn = http.client.HTTPConnection(LOOPBACK, self.port, timeout=CONNECT_TIMEOUT_S)
        try:
            conn.connect()
            if conn.sock is not None:
                conn.sock.settimeout(CLIENT_TIMEOUT_S)
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
        if resp.status == 403 and isinstance(payload, dict) and payload.get("error") == NOT_SERVED:
            raise ApiRestricted(message)
        raise _STATUS_ERRORS.get(resp.status, SwitchyardError)(message or f"API error HTTP {resp.status}")
