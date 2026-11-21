"""T2 child process: hosts one third-party module and proxies its context to the parent.

Started by the parent as ``python -I -m switchyard.host_t2_child`` in the module directory with a scrubbed
environment. The module never sees the parent's objects: its ``ctx`` is a ``ProxyContext`` whose every call
is a request the parent replays on the module's real ``ModuleContext`` (so policy, declared streams and
panels, event namespaces and state confinement are enforced in the parent).
"""

from __future__ import annotations

import importlib
import itertools
import os
import sys
import types
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from switchyard.errors import SwitchyardError
from switchyard.rpc import Channel, RemoteError, read_frame, write_frame

PACKAGE_ROOT = "_switchyard_t2"
_MAX_DETAIL = 200
# The parent answers a child's request while it waits on a call of its own (activate, an action, an event).
# A module thread that calls ctx while the parent is idle waits until the next call; this bounds that wait
# (H1 B-15). Calls made from inside a parent call are answered at once.
CHILD_CALL_TIMEOUT_S = 30.0


class ParentPort(Protocol):
    def request(self, method: str, params: dict[str, Any], timeout: float | None = None) -> Any: ...


def _call(parent: ParentPort, method: str, params: dict[str, Any]) -> Any:
    try:
        return parent.request(method, params, CHILD_CALL_TIMEOUT_S)
    except RemoteError as exc:
        raise exc.as_local() from None


class StateProxy:
    def __init__(self, parent: ParentPort) -> None:
        self._parent = parent

    def _op(self, op: str, *args: Any) -> Any:
        return _call(self._parent, "ctx.state", {"op": op, "args": list(args)})

    def table(self, name: str) -> Any:
        return self._op("table", name)

    def create_table(
        self, name: str, columns: Sequence[tuple[str, str]], *, primary_key: Sequence[str] = ()
    ) -> Any:
        return self._op("create_table", name, [list(c) for c in columns], list(primary_key))

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        return self._op("execute", sql, list(params))

    def kv_get(self, key: str, default: Any = None) -> Any:
        return self._op("kv_get", key, default)

    def kv_set(self, key: str, value: Any) -> Any:
        return self._op("kv_set", key, value)


class ProxyContext:
    """What a T2 module sees as ``ctx``. Mirrors ``switchyard.context.ModuleContext``."""

    def __init__(self, channel: ParentPort, module_id: str, host: ChildHost) -> None:
        self._channel = channel
        self._host = host
        self.module_id = module_id

    def log(self, stream: str, event: str, **fields: Any) -> None:
        _call(self._channel, "ctx.log", {"stream": stream, "event": event, "fields": fields})

    def register_panel(self, panel_id: str, render: Callable[[], Any]) -> None:
        self._host.panels[panel_id] = render
        _call(self._channel, "ctx.register_panel", {"panel_id": panel_id})

    def emit(self, type_: str, data: dict[str, Any]) -> None:
        _call(self._channel, "ctx.emit", {"type": type_, "data": data})

    def subscribe(self, type_: str, handler: Callable[[Any], None]) -> None:
        handler_id = next(self._host.handler_ids)
        self._host.handlers[handler_id] = handler
        _call(self._channel, "ctx.subscribe", {"type": type_, "handler_id": handler_id})

    def health_report(self, ok: bool, detail: str = "") -> None:
        _call(self._channel, "ctx.health_report", {"ok": ok, "detail": detail})

    @property
    def state(self) -> StateProxy:
        return StateProxy(self._channel)

    def _broker(self, capability: str) -> Any:
        return _call(self._channel, "ctx.broker", {"capability": capability})

    @property
    def secrets(self) -> Any:
        return self._broker("secrets.read")

    @property
    def net(self) -> Any:
        return self._broker("net.outbound")

    @property
    def schedule(self) -> Any:
        return self._broker("schedule")

    @property
    def spawn(self) -> Any:
        return self._broker("process.spawn")


def normalise_health(result: Any) -> list[Any]:
    if isinstance(result, bool):
        return [result, ""]
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
        return [result[0], str(result[1])[:_MAX_DETAIL]]
    ok = getattr(result, "ok", None)
    if isinstance(ok, bool):
        return [ok, str(getattr(result, "detail", ""))[:_MAX_DETAIL]]
    return [False, "invalid health result"]


class ChildHost:
    """Dispatcher for requests from the parent."""

    def __init__(self, parent: ParentPort) -> None:
        self._parent = parent
        self._instance: Any = None
        self._module_id = ""
        self.panels: dict[str, Callable[[], Any]] = {}
        self.handlers: dict[int, Callable[[Any], None]] = {}
        self.handler_ids = itertools.count(1)
        self.on_shutdown: Callable[[], None] = lambda: None

    def _loaded(self) -> Any:
        if self._instance is None:
            raise SwitchyardError("module not loaded")
        return self._instance

    def _load(self, params: dict[str, Any]) -> None:
        if self._instance is not None:
            raise SwitchyardError("module already loaded")
        module_id, directory = str(params["module_id"]), str(params["directory"])
        if PACKAGE_ROOT not in sys.modules:
            root = types.ModuleType(PACKAGE_ROOT)
            root.__path__ = []
            sys.modules[PACKAGE_ROOT] = root
        prefix = f"{PACKAGE_ROOT}.{module_id}"
        for name in [n for n in sys.modules if n == prefix or n.startswith(prefix + ".")]:
            del sys.modules[name]
        importlib.invalidate_caches()
        package = types.ModuleType(prefix)
        package.__path__ = [directory]
        sys.modules[package.__name__] = package
        module = importlib.import_module(f"{package.__name__}.{params['entry_module']}")
        file = getattr(module, "__file__", None) or ""
        home = os.path.realpath(directory)
        if not file or os.path.commonpath([os.path.realpath(file), home]) != home:  # H1 A-3, after import
            raise SwitchyardError("entry code was loaded from outside the module directory")
        self._instance = getattr(module, str(params["entry_class"]))()
        self._module_id = module_id

    def handle(self, method: str, params: dict[str, Any]) -> Any:
        if method == "load":
            self._load(params)
            return None
        if method == "shutdown":
            self.on_shutdown()
            return None
        instance = self._loaded()
        if method == "activate":
            instance.activate(ProxyContext(self._parent, self._module_id, self))
            return None
        if method == "deactivate":
            instance.deactivate()
            return None
        if method == "health":
            return normalise_health(instance.health())
        if method == "panel":
            render = self.panels.get(str(params.get("panel_id")))
            if render is None:
                raise SwitchyardError("unknown panel")
            return render()
        if method == "event":
            handler = self.handlers.get(params.get("handler_id"))  # type: ignore[arg-type]
            if handler is None:
                raise SwitchyardError("unknown handler")
            event = params["event"]
            handler(
                types.SimpleNamespace(
                    type=event["type"], source=event["source"], data=event["data"], ts=event["ts"]
                )
            )
            return None
        raise SwitchyardError(f"unknown method {method!r}")


def main() -> None:  # pragma: no cover - exercised through real subprocesses in tests/core/test_host_t2.py
    proto_in, proto_out = sys.stdin.buffer, sys.stdout.buffer
    sys.stdout = sys.stderr  # print() in module code must not corrupt the protocol stream
    holder: dict[str, Channel] = {}
    host = ChildHost(_Lazy(holder))
    channel = Channel(lambda m: write_frame(proto_out, m), lambda _t: read_frame(proto_in), host.handle)
    holder["channel"] = channel
    host.on_shutdown = channel.stop
    channel.serve_forever()


class _Lazy:  # pragma: no cover - see main()
    def __init__(self, holder: dict[str, Channel]) -> None:
        self._holder = holder

    def request(self, method: str, params: dict[str, Any], timeout: float | None = None) -> Any:
        return self._holder["channel"].request(method, params, timeout)


if __name__ == "__main__":  # pragma: no cover
    main()
