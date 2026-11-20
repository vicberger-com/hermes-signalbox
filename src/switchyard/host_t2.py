"""T2 subprocess host, parent side (spec section 3, T2 subprocess host).

``T2Module`` looks to the lifecycle manager like an in-process module instance (``activate``, ``deactivate``,
``health``), so both trust levels share one lifecycle. Each instance owns one child process:

* ``python -I -m switchyard.host_t2_child``, working directory = module directory, stderr discarded,
  environment reduced to ``ENV_ALLOW`` plus ``SWITCHYARD_T2=1`` (no inherited secrets);
* every call has a deadline (``timeout``); a timeout, a protocol violation (oversize or malformed frame,
  unexpected message) or the child exiting kills the child and raises, which fails the module closed;
* requests from the child are replayed on the module's real ``ModuleContext``. Only the methods in
  ``_dispatch`` exist; state operations are limited to ``_STATE_OPS``; capability brokers are policy-checked
  and then refused, because broker objects cannot cross the process boundary in M0.
"""

from __future__ import annotations

import contextlib
import os
import queue
import subprocess  # nosec B404
import sys
import threading
from typing import IO, Any

from switchyard.context import ModuleContext
from switchyard.errors import SwitchyardError
from switchyard.manifest import Manifest
from switchyard.rpc import Channel, Message, ProtocolError, RemoteError, read_frame, write_frame

# subprocess (bandit B404/B603) is used once, in _start, with a fixed argument list and no shell.
DEFAULT_TIMEOUT_S = 10.0
SHUTDOWN_TIMEOUT_S = 2.0
ENV_ALLOW = (
    "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "TMPDIR",
    "HOME", "USERPROFILE", "LANG", "LC_ALL",
)  # fmt: skip
_STATE_OPS = frozenset({"table", "create_table", "execute", "kv_get", "kv_set"})
_BROKERS = {
    "secrets.read": "secrets",
    "net.outbound": "net",
    "schedule": "schedule",
    "process.spawn": "spawn",
}


MAX_PENDING_FRAMES = 64  # at most 64 MB queued (frames are capped at 1 MB)


class T2Timeout(SwitchyardError):
    """A call to a subprocess module did not finish in time."""


def child_environment() -> dict[str, str]:
    env = {k: v for k in ENV_ALLOW if (v := os.environ.get(k)) is not None}
    env["SWITCHYARD_T2"] = "1"
    return env


def _text(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str):
        raise SwitchyardError(f"parameter {key!r} must be a string")
    return value


def _obj(params: dict[str, Any], key: str) -> dict[str, Any]:
    value = params.get(key)
    if not isinstance(value, dict):
        raise SwitchyardError(f"parameter {key!r} must be an object")
    return value


class T2Module:
    def __init__(self, manifest: Manifest, *, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self._manifest = manifest
        self._timeout = timeout
        self._proc: subprocess.Popen[bytes] | None = None
        self._channel: Channel | None = None
        self._ctx: ModuleContext | None = None
        # Bounded (R1 review): when full, the reader stops reading and the child blocks on its own writes.
        self._inbox: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=MAX_PENDING_FRAMES)
        self._write_lock = threading.Lock()
        self._call_lock = threading.RLock()
        self._flooded = False

    # process ------------------------------------------------------------------------------------------

    def _start(self) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        # Fixed argv (this interpreter, -I, our own child module); no shell; nothing taken from the module.
        self._proc = subprocess.Popen(  # nosec B603
            [sys.executable, "-I", "-m", "switchyard.host_t2_child"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=self._manifest.directory,
            env=child_environment(),
            bufsize=0,
            creationflags=flags,
        )
        stdout = self._proc.stdout
        if stdout is None:  # pragma: no cover - stdout=PIPE always yields a stream
            raise ProtocolError("child has no stdout")
        threading.Thread(target=self._reader, args=(stdout,), daemon=True).start()
        self._channel = Channel(self._send, self._recv, self._dispatch, expose_messages=True)

    def _reader(self, stream: IO[bytes]) -> None:
        try:
            while True:
                msg = read_frame(stream)
                try:
                    self._inbox.put(("msg", msg), timeout=self._timeout)
                except queue.Full:
                    # The child floods frames nobody is reading: stop it instead of blocking (R1 follow-up).
                    self._flooded = True
                    proc = self._proc
                    if proc is not None:
                        proc.kill()
                    return
                if msg is None:
                    return
        except ProtocolError as exc:
            with contextlib.suppress(queue.Full):
                self._inbox.put(("error", exc), timeout=1)

    def _send(self, msg: Message) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise ProtocolError("child is not running")
        stdin = proc.stdin
        failure: list[BaseException] = []

        def write() -> None:
            try:
                write_frame(stdin, msg)
            except BaseException as exc:  # reported to the caller below
                failure.append(exc)

        with self._write_lock:
            # A child that stops reading its stdin must not block the parent forever (R1 follow-up).
            writer = threading.Thread(target=write, daemon=True)
            writer.start()
            writer.join(self._timeout)
            if writer.is_alive():
                proc.kill()
                raise ProtocolError(f"module {self._manifest.id!r} stopped reading its input")
        if failure:
            raise failure[0]

    def _recv(self, timeout: float | None) -> Message | None:
        try:
            kind, value = self._inbox.get(timeout=timeout)
        except queue.Empty:
            raise T2Timeout(f"module {self._manifest.id!r} did not answer within {timeout} s") from None
        if kind == "error":
            raise value
        return value  # type: ignore[no-any-return]

    def kill(self) -> None:
        proc, self._proc, self._channel = self._proc, None, None
        if proc is None:
            return
        proc.kill()
        try:
            proc.wait(timeout=SHUTDOWN_TIMEOUT_S)
        finally:
            for stream in (proc.stdin, proc.stdout):
                if stream is not None:
                    stream.close()

    def _call(self, method: str, params: dict[str, Any], timeout: float | None = None) -> Any:
        with self._call_lock:
            if self._channel is None:
                raise SwitchyardError(f"module {self._manifest.id!r} is not running")
            try:
                return self._channel.request(method, params, timeout or self._timeout)
            except RemoteError:
                raise
            except Exception:
                self.kill()
                raise

    # module interface ---------------------------------------------------------------------------------

    def activate(self, ctx: ModuleContext) -> None:
        self._ctx = ctx
        try:
            self._start()
            m = self._manifest
            self._call("load", {"module_id": m.id, "directory": str(m.directory),
                                "entry_module": m.entry_module, "entry_class": m.entry_class})  # fmt: skip
            self._call("activate", {})
        except BaseException:
            self.kill()
            raise

    def deactivate(self) -> None:
        if self._channel is None:
            raise SwitchyardError(f"module {self._manifest.id!r} is not running")
        try:
            self._call("deactivate", {})
        finally:
            try:
                if self._channel is not None:
                    self._call("shutdown", {}, timeout=SHUTDOWN_TIMEOUT_S)
                if self._proc is not None:
                    self._proc.wait(timeout=SHUTDOWN_TIMEOUT_S)
            except (SwitchyardError, subprocess.TimeoutExpired):
                pass
            self.kill()

    def health(self) -> tuple[bool, str]:
        if self._channel is None:
            return False, "not running"
        result = self._call("health", {})
        if isinstance(result, list) and len(result) == 2 and isinstance(result[0], bool):
            return result[0], str(result[1])
        return False, "invalid health result"

    # requests from the child --------------------------------------------------------------------------

    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        ctx = self._ctx
        if ctx is None:
            raise SwitchyardError("no context")
        if method == "ctx.log":
            ctx.log(_text(params, "stream"), _text(params, "event"), **_obj(params, "fields"))
            return None
        if method == "ctx.register_panel":
            panel_id = _text(params, "panel_id")
            ctx.register_panel(panel_id, lambda: self._call("panel", {"panel_id": panel_id}))
            return None
        if method == "ctx.emit":
            ctx.emit(_text(params, "type"), _obj(params, "data"))
            return None
        if method == "ctx.subscribe":
            handler_id = params.get("handler_id")
            if not isinstance(handler_id, int):
                raise SwitchyardError("handler_id must be an integer")

            def forward(event: Any) -> None:
                payload = {
                    "type": event.type,
                    "source": event.source,
                    "data": dict(event.data),
                    "ts": event.ts,
                }
                self._call("event", {"handler_id": handler_id, "event": payload})

            ctx.subscribe(_text(params, "type"), forward)
            return None
        if method == "ctx.health_report":
            ok = params.get("ok")
            if not isinstance(ok, bool):
                raise SwitchyardError("ok must be a boolean")
            ctx.health_report(ok, str(params.get("detail", ""))[:200])
            return None
        if method == "ctx.state":
            return self._state(ctx, _text(params, "op"), params.get("args"))
        if method == "ctx.broker":
            member = _BROKERS.get(_text(params, "capability"))
            if member is None:
                raise SwitchyardError("unknown capability broker")
            getattr(ctx, member)  # policy check; raises CapabilityDenied when not granted
            raise SwitchyardError("capability brokers are not available to subprocess modules in M0")
        raise SwitchyardError(f"unknown method {method!r}")

    @staticmethod
    def _state(ctx: ModuleContext, op: str, args: Any) -> Any:
        if op not in _STATE_OPS or not isinstance(args, list):
            raise SwitchyardError(f"state operation {op!r} is not allowed")
        store = ctx.state
        if op == "create_table":
            name, columns, primary_key = args
            store.create_table(name, [tuple(c) for c in columns], primary_key=primary_key)  # type: ignore[attr-defined]
            return None
        if op == "execute":
            sql, sql_params = args
            rows = store.execute(sql, tuple(sql_params))  # type: ignore[attr-defined]
            return [list(r) for r in rows]
        return getattr(store, op)(*args)
