"""Length-prefixed JSON-RPC 2.0 over byte streams, and a symmetric channel (spec section 3, T2 host).

Frame: 4-byte big-endian length, then that many bytes of UTF-8 JSON holding one object. Frames above
``MAX_FRAME_BYTES`` are refused on write and on read (before the body is read).

``Channel`` is used by both the parent and the child. ``request`` sends a call and reads frames until its own
response arrives, serving requests from the peer that arrive meanwhile (nested calls, bounded by
``MAX_NESTING``). Errors cross as ``{"code", "message", "data": {"type"}}``. With ``expose_messages`` the
message of a core ``SignalboxError`` is included; otherwise only the exception class name crosses, because
module exception messages can carry secrets.
"""

from __future__ import annotations

import itertools
import json
import re
import time
from collections.abc import Callable
from typing import IO, Any

from hermes_signalbox.errors import CapabilityDenied, SignalboxError, StateError

MAX_FRAME_BYTES = 1024 * 1024
MAX_NESTING = 16
_HEADER = 4

Message = dict[str, Any]


_TYPE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


def remote_type_name(value: Any) -> str:
    """The error type a child process reported, if it is a plain class name; otherwise ``"Error"``. The
    name is shown to the operator and written to the audit log, and the child chooses it (review R-6)."""
    return value if isinstance(value, str) and _TYPE_NAME.fullmatch(value) else "Error"


class ProtocolError(SignalboxError):
    """The peer broke the wire protocol (bad frame, oversize, unexpected message, closed stream)."""


class RemoteError(SignalboxError):
    """The peer's handler raised. ``remote_type`` is the original exception class name."""

    def __init__(self, remote_type: str, message: str = "") -> None:
        self.remote_type = remote_type
        self.remote_message = message
        super().__init__(f"{remote_type}: {message}" if message else remote_type)

    def as_local(self) -> SignalboxError:
        """Rebuild core errors as their own class so module code can catch them normally."""
        if self.remote_type == "CapabilityDenied":
            return CapabilityDenied(self.remote_message)
        if self.remote_type == "StateError":
            return StateError(self.remote_message)
        return SignalboxError(self.remote_message or f"remote error: {self.remote_type}")


# framing --------------------------------------------------------------------------------------------------


def write_frame(stream: IO[bytes], message: Message) -> None:
    try:
        body = json.dumps(message, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"message is not JSON-serialisable: {exc}") from None
    if len(body) > MAX_FRAME_BYTES:
        raise ProtocolError(f"frame too large ({len(body)} bytes, limit {MAX_FRAME_BYTES})")
    view = memoryview(len(body).to_bytes(_HEADER, "big") + body)
    try:
        while view:  # a raw pipe (bufsize=0) may accept part of a write (H1 B-16)
            written = stream.write(view)
            if not written:
                raise ProtocolError("stream accepted no bytes; frame not sent")
            view = view[written:]
        stream.flush()
    except (OSError, ValueError) as exc:
        raise ProtocolError(f"stream closed: {exc}") from None


def _read_exact(stream: IO[bytes], n: int) -> bytes:
    chunks: list[bytes] = []
    remaining = n
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: IO[bytes]) -> Message | None:
    """Read one frame. Returns ``None`` on a clean end of stream."""
    header = _read_exact(stream, _HEADER)
    if not header:
        return None
    if len(header) < _HEADER:
        raise ProtocolError("truncated frame header")
    size = int.from_bytes(header, "big")
    if size > MAX_FRAME_BYTES:
        raise ProtocolError(f"frame too large ({size} bytes, limit {MAX_FRAME_BYTES})")
    body = _read_exact(stream, size)
    if len(body) < size:
        raise ProtocolError("truncated frame body")
    try:
        message = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError(f"invalid frame: {exc}") from None
    if not isinstance(message, dict):
        raise ProtocolError("frame must hold a JSON object")
    return message


# channel --------------------------------------------------------------------------------------------------

Handler = Callable[[str, dict[str, Any]], Any]


class Channel:
    def __init__(
        self,
        send: Callable[[Message], None],
        recv: Callable[[float | None], Message | None],
        handler: Handler,
        *,
        expose_messages: bool = False,
    ) -> None:
        self._send = send
        self._recv = recv
        self._handler = handler
        self._expose = expose_messages
        self._ids = itertools.count(1)
        self._depth = 0
        self._stopped = False
        self._deadline: float | None = None

    def stop(self) -> None:
        self._stopped = True

    @staticmethod
    def _check_request(msg: Message) -> tuple[int, str, dict[str, Any]]:
        if msg.get("jsonrpc") != "2.0":
            raise ProtocolError("missing jsonrpc 2.0 marker")
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params", {})
        if not isinstance(mid, int) or isinstance(mid, bool):
            raise ProtocolError("request id must be an integer")
        if not isinstance(method, str) or not isinstance(params, dict):
            raise ProtocolError("request needs a string method and object params")
        return mid, method, params

    def _error_body(self, exc: BaseException) -> dict[str, Any]:
        remote_type = exc.remote_type if isinstance(exc, RemoteError) else type(exc).__name__
        message = ""
        if self._expose and isinstance(exc, SignalboxError):
            message = exc.remote_message if isinstance(exc, RemoteError) else str(exc)
        return {"code": -32000, "message": message, "data": {"type": remote_type}}

    def dispatch(self, msg: Message) -> None:
        """Serve one inbound request message."""
        mid, method, params = self._check_request(msg)
        if self._depth >= MAX_NESTING:
            raise ProtocolError("nested calls too deep")
        self._depth += 1
        try:
            result = self._handler(method, params)
            reply: Message = {"jsonrpc": "2.0", "id": mid, "result": result}
        except ProtocolError:
            raise
        except Exception as exc:
            reply = {"jsonrpc": "2.0", "id": mid, "error": self._error_body(exc)}
        finally:
            self._depth -= 1
        self._send(reply)

    def remaining(self) -> float | None:
        """Seconds left of the innermost call in progress (``None``: no deadline). Transports use it to
        bound a send by the call's own deadline (H1 B-14)."""
        return None if self._deadline is None else self._deadline - time.monotonic()

    def request(self, method: str, params: dict[str, Any], timeout: float | None = None) -> Any:
        # One deadline for the whole call, the send included: a peer sending a request every few seconds, or
        # a slow write, must not stretch it (R1 review, H1 B-14).
        deadline = None if timeout is None else time.monotonic() + timeout
        outer = self._deadline
        if outer is not None:  # a nested call never outlives the call it runs inside
            self._deadline = outer if deadline is None else min(deadline, outer)
        else:
            self._deadline = deadline
        try:
            return self._request(method, params, timeout, deadline)
        finally:
            self._deadline = outer

    def _request(
        self, method: str, params: dict[str, Any], timeout: float | None, deadline: float | None
    ) -> Any:
        mid = next(self._ids)
        self._send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
        while True:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise ProtocolError(f"{method} did not finish within {timeout} s")
            msg = self._recv(remaining)
            if msg is None:
                raise ProtocolError("peer closed the channel")
            if "method" in msg:
                self.dispatch(msg)
                continue
            if msg.get("jsonrpc") != "2.0" or msg.get("id") != mid:
                raise ProtocolError("unexpected response")
            if "error" in msg:
                err: dict[str, Any] = msg["error"] if isinstance(msg["error"], dict) else {}
                raw_data = err.get("data")
                data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
                raise RemoteError(
                    remote_type_name(data.get("type", "Error")), str(err.get("message", ""))[:1000]
                )
            return msg.get("result")

    def serve_forever(self) -> None:
        """Serve requests until the peer closes the stream or ``stop()`` is called."""
        while not self._stopped:
            msg = self._recv(None)
            if msg is None:
                return
            if "method" not in msg:
                raise ProtocolError("unexpected response while idle")
            self.dispatch(msg)
