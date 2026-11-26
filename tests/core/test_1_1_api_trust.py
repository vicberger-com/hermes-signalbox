"""1.1 backlog batch 2: CLI to daemon trust (H1 B-8 #101, B-9 #102).

B-8: the client proves the daemon's identity (an HMAC of a fresh challenge, keyed with the token) before it
sends the token. B-9: only a failure before the request is sent falls back to a local run; a failure after it
is an unknown outcome and nothing runs again.
"""

from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest

from hermes_signalbox import api, cli
from hermes_signalbox.api import ApiClient, ApiOutcomeUnknown, ApiUnavailable, ApiUntrusted, ControlServer
from hermes_signalbox.core import Core

TOKEN = "tok-" + "9b2c7d1e5f3a8b4c6d0e2f1a3b5c7d9e"


def _proof(token: str, challenge: str) -> str:
    return hmac.new(token.encode(), ("signalbox-api-v1:" + challenge).encode(), hashlib.sha256).hexdigest()


class _Fake(http.server.BaseHTTPRequestHandler):
    """A listener on the daemon's port. ``mode``: impostor (no proof), forger (wrong proof), dropper (proves
    identity with the right token, reads the POST body, closes without replying)."""

    mode = "impostor"
    received: ClassVar[list[bytes]] = []

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send(self, payload: Any) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self.received.append(str(self.headers).encode())
        challenge = self.headers.get(api.CHALLENGE_HEADER, "")
        if self.mode == "impostor":
            self._send({"ok": True})
        elif self.mode == "forger":
            self._send({"ok": True, "proof": _proof("guess", challenge)})
        else:
            self._send({"ok": True, "proof": _proof(TOKEN, challenge)})

    def do_POST(self) -> None:
        self.received.append(str(self.headers).encode())
        self.received.append(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if self.mode == "dropper":
            self.close_connection = True
            self.connection.close()  # applied, then the connection dropped before any reply
            return
        self._send({"ok": True, "result": "forged"})


@pytest.fixture
def fake(request: pytest.FixtureRequest) -> Iterator[tuple[int, list[bytes]]]:
    handler = type("H", (_Fake,), {"mode": request.param, "received": []})
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1], handler.received
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.parametrize("fake", ["impostor", "forger"], indirect=True)
def test_h1_b8_token_is_never_sent_to_a_listener_that_cannot_prove_it_holds_it(
    fake: tuple[int, list[bytes]],
) -> None:
    port, received = fake
    with pytest.raises(ApiUntrusted, match="token not sent"):
        ApiClient(port, TOKEN).request("module", "list", {})
    assert received, "the client should have asked for proof"
    assert not any(TOKEN.encode() in r for r in received)


def test_h1_b8_the_real_daemon_proves_its_identity(tmp_path: Path) -> None:
    with Core(data_dir=tmp_path / "data") as core:
        server = ControlServer(core)
        server.start()
        try:
            assert isinstance(ApiClient.from_data_dir(core.data_dir).request("module", "list", {}), list)
            challenge = "ab" * 16
            assert server.proof(challenge) == _proof(server.token, challenge)
        finally:
            server.shutdown()


@pytest.mark.parametrize("fake", ["dropper"], indirect=True)
def test_h1_b9_a_failure_after_sending_is_an_unknown_outcome(fake: tuple[int, list[bytes]]) -> None:
    port, received = fake
    with pytest.raises(ApiOutcomeUnknown, match="may have"):
        ApiClient(port, TOKEN).request("module", "grant", {"id": "x", "capability": "fs.read"})
    assert any(b'"capability"' in r for r in received)  # the request did arrive
    assert not issubclass(ApiOutcomeUnknown, ApiUnavailable)  # so the CLI does not fall back


def test_h1_b9_cli_does_not_rerun_an_offline_operation_after_an_unknown_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "clear_stale_files", lambda d: False)

    def unknown(self: Any, noun: str, verb: str, params: dict[str, Any]) -> Any:
        raise ApiOutcomeUnknown("the daemon may have applied it")

    monkeypatch.setattr(ApiClient, "from_data_dir", classmethod(lambda cls, d: cls(1, TOKEN)))
    monkeypatch.setattr(ApiClient, "request", unknown)

    class NoLocalRun:
        def __init__(self, **kw: Any) -> None:
            raise AssertionError("must not run the operation locally")

    monkeypatch.setattr(cli, "Core", NoLocalRun)
    operation = cli.OPERATIONS[("module", "grant")]
    assert operation.offline
    with pytest.raises(ApiOutcomeUnknown):
        cli._run(operation, {"id": "x", "capability": "fs.read"}, tmp_path)


def test_h1_b9_a_refused_connection_still_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(cli, "clear_stale_files", lambda d: False)
    (data / "api.port").write_text("1", encoding="utf-8")  # nothing listens on port 1
    (data / "api.token").write_text(TOKEN, encoding="utf-8")
    result = cli._run(cli.OPERATIONS[("module", "list")], {}, data)
    assert isinstance(result, list)
