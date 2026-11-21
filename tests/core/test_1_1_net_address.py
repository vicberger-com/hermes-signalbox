"""#111 part 2 (H1 B-22, operator decision Q-SY-1.1-2 option a).

net.outbound resolves the host once, refuses link-local addresses (cloud metadata endpoints) and connects
to the addresses it checked, so a second DNS answer cannot redirect the request (DNS rebinding). Loopback and
private addresses stay allowed: the bundled connectors call local services on purpose.
"""

from __future__ import annotations

import http.server
import socket
import threading
from collections.abc import Iterator
from typing import Any, ClassVar

import pytest

from switchyard import net
from switchyard.errors import SwitchyardError


class _AllowAll:
    def require_host(self, module_id: str, host: str) -> None:
        pass


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def append(self, **kw: Any) -> None:
        self.records.append(kw)


class _Echo(http.server.BaseHTTPRequestHandler):
    hosts: ClassVar[list[str]] = []

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        self.hosts.append(self.headers.get("Host", ""))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")


@pytest.fixture
def local_server() -> Iterator[int]:
    _Echo.hosts.clear()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()


def _resolver(monkeypatch: pytest.MonkeyPatch, answers: dict[str, list[str]]) -> list[str]:
    """Fake DNS for the names in ``answers`` (each lookup pops the next address); returns the lookups made."""
    real = socket.getaddrinfo
    asked: list[str] = []

    def fake(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        if host in answers:
            asked.append(host)
            addr = answers[host][min(len(asked) - 1, len(answers[host]) - 1)]
            family = socket.AF_INET6 if ":" in addr else socket.AF_INET
            sockaddr = (addr, int(port or 0), 0, 0) if family == socket.AF_INET6 else (addr, int(port or 0))
            return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return asked


@pytest.mark.parametrize("address", ["169.254.169.254", "169.254.0.1", "fe80::1", "::ffff:169.254.169.254"])
def test_b22_link_local_addresses_are_refused(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    _resolver(monkeypatch, {"metadata.example": [address]})
    audit = _Audit()
    broker = net.NetBroker(_AllowAll(), audit)  # type: ignore[arg-type]
    with pytest.raises(SwitchyardError, match="link-local"):
        broker.request("demo", "GET", "http://metadata.example/latest")
    assert audit.records and audit.records[-1]["detail"]["result"] == "refused_address"


def test_b22_the_connection_goes_to_the_address_that_was_checked(
    monkeypatch: pytest.MonkeyPatch, local_server: int
) -> None:
    # First answer: loopback (allowed). Any later lookup would get the metadata address: DNS rebinding.
    asked = _resolver(monkeypatch, {"svc.example": ["127.0.0.1", "169.254.169.254"]})
    broker = net.NetBroker(_AllowAll(), _Audit())  # type: ignore[arg-type]
    resp = broker.request("demo", "GET", f"http://svc.example:{local_server}/x", timeout=5)
    assert resp.status == 200 and resp.body == "ok"
    assert asked == ["svc.example"]  # resolved once; the connection used that answer
    assert _Echo.hosts == [f"svc.example:{local_server}"]  # the Host header still names the host


def test_b22_loopback_and_private_stay_allowed(monkeypatch: pytest.MonkeyPatch, local_server: int) -> None:
    broker = net.NetBroker(_AllowAll(), _Audit())  # type: ignore[arg-type]
    assert broker.request("demo", "GET", f"http://127.0.0.1:{local_server}/x", timeout=5).status == 200
    assert net._refused_address("10.0.0.5") is None and net._refused_address("192.168.1.2") is None
