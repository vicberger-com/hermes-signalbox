"""Framing and the symmetric JSON-RPC channel (spec section 3, T2 subprocess host)."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest

from switchyard.errors import CapabilityDenied, StateError, SwitchyardError
from switchyard.rpc import MAX_FRAME_BYTES, Channel, ProtocolError, RemoteError, read_frame, write_frame


def test_frame_round_trip() -> None:
    buf = io.BytesIO()
    write_frame(buf, {"jsonrpc": "2.0", "id": 1, "method": "x", "params": {"k": "v"}})
    buf.seek(0)
    assert read_frame(buf) == {"jsonrpc": "2.0", "id": 1, "method": "x", "params": {"k": "v"}}
    assert read_frame(buf) is None  # clean EOF


def test_oversize_frames_are_refused_both_ways() -> None:
    with pytest.raises(ProtocolError, match="large"):
        write_frame(io.BytesIO(), {"blob": "x" * MAX_FRAME_BYTES})
    with pytest.raises(ProtocolError, match="large"):
        read_frame(io.BytesIO((MAX_FRAME_BYTES + 1).to_bytes(4, "big") + b"{}"))


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        (b"\x00\x00", "truncated"),
        ((10).to_bytes(4, "big") + b"{}", "truncated"),
        ((3).to_bytes(4, "big") + b"abc", "invalid"),
        ((2).to_bytes(4, "big") + b"[]", "object"),
        ((2).to_bytes(4, "big") + b"\xff\xfe", "invalid"),
    ],
)
def test_bad_frames(raw: bytes, fragment: str) -> None:
    with pytest.raises(ProtocolError, match=fragment):
        read_frame(io.BytesIO(raw))


def test_non_json_values_cannot_be_sent() -> None:
    with pytest.raises(ProtocolError, match="JSON"):
        write_frame(io.BytesIO(), {"x": object()})
    with pytest.raises(ProtocolError, match="JSON"):
        write_frame(io.BytesIO(), {"x": float("nan")})


class Pair:
    """Two channels wired back to back through in-memory queues."""

    def __init__(
        self, handler_a: Any, handler_b: Any, *, expose_a: bool = True, expose_b: bool = False
    ) -> None:
        self.a_to_b: list[dict[str, Any]] = []
        self.b_to_a: list[dict[str, Any]] = []
        self.a = Channel(
            self.a_to_b.append, self._recv(self.b_to_a, "b"), handler_a, expose_messages=expose_a
        )
        self.b = Channel(
            self.b_to_a.append, self._recv(self.a_to_b, "a"), handler_b, expose_messages=expose_b
        )

    def _recv(self, inbox: list[dict[str, Any]], peer: str) -> Any:
        def recv(timeout: float | None) -> dict[str, Any] | None:
            # Single-threaded simulation: while waiting, let the peer serve what it has been sent.
            peer_inbox = self.a_to_b if peer == "b" else self.b_to_a
            peer_channel = self.b if peer == "b" else self.a
            while not inbox:
                if not peer_inbox:
                    return None
                peer_channel.dispatch(peer_inbox.pop(0))
            return inbox.pop(0)

        return recv


def test_request_and_nested_callback() -> None:
    calls: list[str] = []

    def a_handler(method: str, params: dict[str, Any]) -> Any:
        calls.append(f"a:{method}")
        return {"echo": params["v"]}

    def b_handler(method: str, params: dict[str, Any]) -> Any:
        calls.append(f"b:{method}")
        # while serving A's request, B calls back into A (nested)
        inner = pair.b.request("inner", {"v": 7})
        return {"outer": params["v"], "inner": inner["echo"]}

    pair = Pair(a_handler, b_handler)
    assert pair.a.request("outer", {"v": 1}) == {"outer": 1, "inner": 7}
    assert calls == ["b:outer", "a:inner"]


def test_remote_errors_keep_type_and_filter_messages() -> None:
    def a_handler(method: str, params: dict[str, Any]) -> Any:
        if method == "denied":
            raise CapabilityDenied("module 'x' does not hold capability 'ui.panel'")
        raise StateError("table denied")

    def b_handler(method: str, params: dict[str, Any]) -> Any:
        if method == "module_error":
            raise ValueError("token=sk-secret")
        return pair.b.request(method, {})

    pair = Pair(a_handler, b_handler)
    with pytest.raises(RemoteError) as info:
        pair.a.request("module_error", {})
    assert info.value.remote_type == "ValueError" and "sk-secret" not in str(info.value)
    # core errors raised in A arrive in B as the same class, with the core-written message
    with pytest.raises(RemoteError) as info:
        pair.a.request("denied", {})
    assert info.value.remote_type == "CapabilityDenied"


def test_core_errors_are_rebuilt_as_their_class() -> None:
    err = RemoteError("CapabilityDenied", "nope").as_local()
    assert isinstance(err, CapabilityDenied) and str(err) == "nope"
    assert isinstance(RemoteError("StateError", "x").as_local(), StateError)
    other = RemoteError("ValueError", "").as_local()
    assert type(other) is SwitchyardError and "ValueError" in str(other)


@pytest.mark.parametrize(
    "msg",
    [
        {"jsonrpc": "2.0", "id": "x", "method": "m", "params": {}},
        {"jsonrpc": "2.0", "id": 1, "method": 5, "params": {}},
        {"jsonrpc": "2.0", "id": 1, "method": "m", "params": []},
        {"jsonrpc": "1.0", "id": 1, "method": "m", "params": {}},
        {"jsonrpc": "2.0", "id": 99, "result": {}},
    ],
    ids=["str-id", "int-method", "list-params", "bad-version", "unexpected-response"],
)
def test_malformed_messages_are_protocol_errors(msg: dict[str, Any]) -> None:
    inbox = [msg]
    ch = Channel(lambda m: None, lambda t: inbox.pop(0) if inbox else None, lambda m, p: None)
    with pytest.raises(ProtocolError):
        ch.request("x", {})


def test_eof_during_request_is_a_protocol_error() -> None:
    ch = Channel(lambda m: None, lambda t: None, lambda m, p: None)
    with pytest.raises(ProtocolError, match="closed"):
        ch.request("x", {})


def test_serve_until_eof_and_nesting_limit() -> None:
    sent: list[dict[str, Any]] = []
    inbox = [{"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}]
    ch = Channel(sent.append, lambda t: inbox.pop(0) if inbox else None, lambda m, p: "pong")
    ch.serve_forever()
    assert sent == [{"jsonrpc": "2.0", "id": 1, "result": "pong"}]
    assert json.dumps(sent)  # responses are plain JSON


def test_stop_ends_serve_forever() -> None:
    sent: list[dict[str, Any]] = []
    inbox = [
        {"jsonrpc": "2.0", "id": 1, "method": "stop", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "never", "params": {}},
    ]
    ch = Channel(sent.append, lambda t: inbox.pop(0) if inbox else None, lambda m, p: ch.stop())
    ch.serve_forever()
    assert [m["id"] for m in sent] == [1]
