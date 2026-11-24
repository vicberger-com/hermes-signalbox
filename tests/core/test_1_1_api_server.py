"""1.1 backlog batch 6: API server limits and the token file (H1 B-7 #100, B-17 #108).

B-7: the control API runs at most ``MAX_CONNECTIONS`` handler threads (more connections are closed at once),
and a request must arrive whole within ``REQUEST_READ_DEADLINE_S``: a slow drip no longer holds a thread.
B-17: the token file is restricted before the token is written into it.
"""

from __future__ import annotations

import http.client
import os
import socket
import stat
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from switchyard import api
from switchyard.api import ControlServer
from switchyard.core import Core


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


@pytest.fixture
def small_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ControlServer]:
    monkeypatch.setattr(api, "DEFAULT_MAX_CONNECTIONS", 4)
    monkeypatch.setattr(api, "DEFAULT_REQUEST_READ_DEADLINE_S", 1.0)
    core = Core(data_dir=tmp_path / "data")
    # Set config values for the test (dataclasses are frozen, so create new instances)
    core.config = core.config.__class__(
        data_dir=core.config.data_dir,
        api=core.config.api.__class__(enabled=True, port=0, max_connections=4, request_read_deadline_s=1.0),
        log_level=core.config.log_level,
        host_profile=core.config.host_profile,
        modules=core.config.modules,
        git=core.config.git,
    )
    server = ControlServer(core)
    server.start()
    try:
        yield server
    finally:
        server.shutdown()
        core.close()


def _health(port: int) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", "/v1/health", headers={"Host": f"127.0.0.1:{port}"})
        return conn.getresponse().status
    finally:
        conn.close()


def _stalled(port: int) -> socket.socket:
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"POST /v1/module/list HTTP/1.1\r\nHost: 127.0.0.1\r\n")  # head never finished
    return s


def test_h1_b7_handler_threads_are_bounded(small_server: ControlServer) -> None:
    before = threading.active_count()
    sockets = [_stalled(small_server.port) for _ in range(30)]
    try:
        time.sleep(0.3)
        assert threading.active_count() - before <= api.DEFAULT_MAX_CONNECTIONS
    finally:
        for s in sockets:
            s.close()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:  # slots come back once the stalled clients go away
        try:
            if _health(small_server.port) == 200:
                break
        except OSError:
            time.sleep(0.1)
    else:
        pytest.fail("health check never answered after the stalled clients left")


def test_h1_b7_a_slow_drip_is_cut_off_by_the_total_deadline(small_server: ControlServer) -> None:
    s = socket.create_connection(("127.0.0.1", small_server.port), timeout=5)
    started = time.monotonic()
    try:  # one byte every 50 ms for 2.5 s: each read is well inside the per-read timeout
        for byte in (b"POST /v1/module/list HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Pad: " + b"a" * 200)[:50]:
            s.sendall(bytes([byte]))
            time.sleep(0.05)
    except OSError:
        pass  # the server already closed: that is the expected outcome
    s.settimeout(2)
    try:
        s.recv(1024)  # EOF, a reply or a reset all mean the server stopped waiting for this request
        stopped = True
    except TimeoutError:
        stopped = False  # still waiting for the rest of the head: the drip holds a thread
    except OSError:
        stopped = True
    finally:
        s.close()
    assert stopped and time.monotonic() - started < 6


def test_h1_b7_normal_requests_still_work(small_server: ControlServer) -> None:
    client = api.ApiClient.from_data_dir(small_server.core.data_dir)
    for _ in range(10):
        assert isinstance(client.request("module", "list", {}), list)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL order")
def test_h1_b17_windows_acl_is_applied_to_an_empty_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []
    monkeypatch.setattr(api, "_restrict_windows_acl", lambda p: seen.append(p.stat().st_size))
    token = tmp_path / "api.token"
    token.write_text("stale", encoding="utf-8")
    api._write_private(token, "secret-token-value")
    assert seen == [0]
    assert token.read_text(encoding="utf-8") == "secret-token-value"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode order")
def test_h1_b17_posix_mode_is_user_only_before_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    modes: list[int] = []
    real_write = os.write

    def watch(fd: int, data: Any) -> int:
        modes.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return real_write(fd, data)

    monkeypatch.setattr(os, "umask", os.umask)  # keep the real umask
    old = os.umask(0)
    try:
        monkeypatch.setattr(api.os, "write", watch)
        token = tmp_path / "api.token"
        token.write_text("stale", encoding="utf-8")
        token.chmod(0o644)
        api._write_private(token, "secret-token-value")
    finally:
        os.umask(old)
    assert modes and all(m == 0o600 for m in modes)
