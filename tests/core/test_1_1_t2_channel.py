"""1.1 backlog batch 7: the T2 channel (H1 B-15 #106, B-16 #107, B-18 #109)."""

from __future__ import annotations

import io
from typing import Any

import pytest

from hermes_signalbox import events, host_t2_child, rpc
from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.events import EventBus


class _Parent:
    def __init__(self) -> None:
        self.timeouts: list[float | None] = []

    def request(self, method: str, params: dict[str, Any], timeout: float | None = None) -> Any:
        self.timeouts.append(timeout)
        return "ok"


def test_h1_b15_child_calls_to_the_parent_have_a_timeout() -> None:
    parent = _Parent()
    assert host_t2_child._call(parent, "ctx.log", {}) == "ok"
    assert parent.timeouts == [host_t2_child.CHILD_CALL_TIMEOUT_S]
    assert 0 < host_t2_child.CHILD_CALL_TIMEOUT_S <= 120


class _Trickle(io.RawIOBase):
    """A raw stream that accepts at most 3 bytes per write, as a raw pipe may."""

    def __init__(self) -> None:
        self.data = bytearray()

    def writable(self) -> bool:
        return True

    def write(self, b: Any) -> int:
        chunk = bytes(b[:3])
        self.data += chunk
        return len(chunk)


def test_h1_b16_frame_writer_finishes_a_short_write() -> None:
    stream = _Trickle()
    message = {"id": 7, "method": "ctx.log", "params": {"text": "x" * 100}}
    rpc.write_frame(stream, message)  # type: ignore[arg-type]
    assert rpc.read_frame(io.BytesIO(bytes(stream.data))) == message


class _Stuck(io.RawIOBase):
    def writable(self) -> bool:
        return True

    def write(self, b: Any) -> int | None:
        return None  # would block


def test_h1_b16_a_stream_that_accepts_nothing_is_a_protocol_error() -> None:
    with pytest.raises(rpc.ProtocolError):
        rpc.write_frame(_Stuck(), {"id": 1})  # type: ignore[arg-type]


class _Audit:
    def append(self, **kw: Any) -> None:
        pass


def test_h1_b18_subscriptions_per_module_are_capped() -> None:
    bus = EventBus(_Audit())  # type: ignore[arg-type]
    for _ in range(events.MAX_SUBSCRIPTIONS):
        bus.subscribe("mod", "demo.*", lambda e: None)
    with pytest.raises(SignalboxError, match="subscriptions"):
        bus.subscribe("mod", "demo.*", lambda e: None)
    bus.subscribe("other", "demo.*", lambda e: None)  # per module, not global
    bus.unsubscribe_all("mod")
    bus.subscribe("mod", "demo.*", lambda e: None)
    assert bus.subscriptions("mod") == 1
