"""T2 subprocess host: child dispatcher in-process, and real subprocesses end to end."""

from __future__ import annotations

import functools
import json
import textwrap
from pathlib import Path
from typing import Any

import pytest
from sy_testing import RecordingAudit, write_module

from switchyard.capabilities import MemoryGrantStore, PolicyEngine
from switchyard.context import MemoryPanelRegistry
from switchyard.errors import CapabilityDenied, StateError, SwitchyardError
from switchyard.events import EventBus
from switchyard.host_t2 import T2Module, child_environment
from switchyard.host_t2_child import ChildHost
from switchyard.lifecycle import ModuleManager, ModuleStatus
from switchyard.logs import JsonlLogSink
from switchyard.manifest import load_manifest
from switchyard.rpc import RemoteError
from switchyard.state import StateStore

# child dispatcher, in-process ------------------------------------------------------------------------------


class FakeParent:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}

    def request(self, method: str, params: dict[str, Any], timeout: float | None = None) -> Any:
        self.calls.append((method, params))
        value = self.responses.get(method)
        if isinstance(value, Exception):
            raise value
        return value


CHILD_MOD = """
class Mod:
    def activate(self, ctx):
        self.ctx = ctx
        ctx.log("{id}", "hello", n=1)
        ctx.register_panel("{id}.status", lambda: {"ok": True})
        ctx.subscribe("x.y", self.on)
        ctx.emit("{id}.started", {})
        ctx.health_report(True, "fine")
        self.seen = []
    def on(self, event):
        self.seen.append(event.type)
        self.ctx.state.kv_set("last", event.data["n"])
    def deactivate(self):
        self.ctx = None
    def health(self):
        return (True, "child ok")
"""


def _child(
    tmp_path: Path, code: str = CHILD_MOD, responses: dict[str, Any] | None = None
) -> tuple[ChildHost, FakeParent]:
    d = write_module(tmp_path, "kid", code, isolation="subprocess")
    parent = FakeParent(responses)
    host = ChildHost(parent)
    host.handle(
        "load", {"module_id": "kid", "directory": str(d), "entry_module": "mod", "entry_class": "Mod"}
    )
    return host, parent


def test_child_proxies_context_calls(tmp_path: Path) -> None:
    host, parent = _child(tmp_path)
    host.handle("activate", {})
    methods = [m for m, _ in parent.calls]
    assert methods == ["ctx.log", "ctx.register_panel", "ctx.subscribe", "ctx.emit", "ctx.health_report"]
    assert parent.calls[0][1] == {"stream": "kid", "event": "hello", "fields": {"n": 1}}
    assert host.handle("panel", {"panel_id": "kid.status"}) == {"ok": True}
    handler_id = parent.calls[2][1]["handler_id"]
    host.handle(
        "event",
        {"handler_id": handler_id, "event": {"type": "x.y", "source": "core", "data": {"n": 5}, "ts": "t"}},
    )
    assert parent.calls[-1] == ("ctx.state", {"op": "kv_set", "args": ["last", 5]})
    assert host.handle("health", {}) == [True, "child ok"]
    host.handle("deactivate", {})


def test_child_health_shapes_and_errors(tmp_path: Path) -> None:
    host, _ = _child(tmp_path, "class Mod:\n    def activate(self, c): ...\n    def deactivate(self): ...\n"
                                "    def health(self):\n        return 'odd'\n")  # fmt: skip
    assert host.handle("health", {}) == [False, "invalid health result"]
    with pytest.raises(SwitchyardError, match="unknown"):
        host.handle("bogus", {})
    with pytest.raises(SwitchyardError, match="panel"):
        host.handle("panel", {"panel_id": "nope"})
    with pytest.raises(SwitchyardError, match="handler"):
        host.handle("event", {"handler_id": 99, "event": {}})


def test_child_rebuilds_core_errors(tmp_path: Path) -> None:
    code = """
    class Mod:
        def activate(self, ctx):
            ctx.secrets
        def deactivate(self): ...
        def health(self): return True
    """
    host, _ = _child(tmp_path, code, {"ctx.broker": RemoteError("CapabilityDenied", "no secrets.read")})
    with pytest.raises(CapabilityDenied, match=r"no secrets\.read"):
        host.handle("activate", {})


def test_child_state_proxy(tmp_path: Path) -> None:
    code = """
    class Mod:
        def activate(self, ctx):
            s = ctx.state
            s.create_table("t", [("x", "TEXT")], primary_key=["x"])
            self.rows = s.execute("SELECT * FROM " + str(s.table("t")), [1])
            self.v = s.kv_get("k", 3)
            s.execute("DELETE FROM grants")
        def deactivate(self): ...
        def health(self): return True
    """
    host, parent = _child(tmp_path, code, {"ctx.state": None})
    host.handle("activate", {})
    ops = [p["op"] for m, p in parent.calls if m == "ctx.state"]
    assert ops == ["create_table", "table", "execute", "kv_get", "execute"]
    assert parent.calls[0][1]["args"] == ["t", [["x", "TEXT"]], ["x"]]


def test_child_refuses_load_twice_and_calls_before_load(tmp_path: Path) -> None:
    host = ChildHost(FakeParent())
    with pytest.raises(SwitchyardError, match="not loaded"):
        host.handle("activate", {})
    host, _ = _child(tmp_path)
    with pytest.raises(SwitchyardError, match="already loaded"):
        host.handle(
            "load", {"module_id": "kid", "directory": ".", "entry_module": "mod", "entry_class": "Mod"}
        )


def test_shutdown_stops_the_channel(tmp_path: Path) -> None:
    stopped: list[bool] = []
    host, _ = _child(tmp_path)
    host.on_shutdown = lambda: stopped.append(True)
    assert host.handle("shutdown", {}) is None and stopped == [True]


# environment ----------------------------------------------------------------------------------------------


def test_child_environment_is_an_allow_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWITCHYARD_TEST_SECRET", "canary")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-canary")
    env = child_environment()
    assert "SWITCHYARD_TEST_SECRET" not in env and "OPENAI_API_KEY" not in env
    assert env["SWITCHYARD_T2"] == "1" and "PATH" in env


# real subprocesses ----------------------------------------------------------------------------------------


class Env:
    def __init__(self, tmp_path: Path, audit: RecordingAudit, timeout: float = 15.0) -> None:
        self.audit = audit
        self.root = tmp_path / "third_party"
        self.root.mkdir()
        self.store = StateStore(tmp_path / "state.db", backup_dir=tmp_path / "backup")
        self.store.migrate()
        self.policy = PolicyEngine(MemoryGrantStore(), audit)
        self.bus = EventBus(audit)
        self.panels = MemoryPanelRegistry()
        self.logs = JsonlLogSink(tmp_path / "logs")
        self.manager = ModuleManager(
            policy=self.policy, audit=audit, bus=self.bus, logs=self.logs, panels=self.panels,
            store=self.store, trusted_roots=[tmp_path / "trusted"],
            t2_factory=functools.partial(T2Module, timeout=timeout),
        )  # fmt: skip

    def add(self, module_id: str, code: str, request: tuple[str, ...] = ()) -> None:
        write_module(self.root, module_id, code, isolation="subprocess", request=request)
        self.manager.discover([self.root])

    def log_text(self, module_id: str) -> str:
        path = self.logs.directory / f"{module_id}.jsonl"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def close(self) -> None:
        for module_id in self.manager.ids():
            self.manager.deactivate(module_id, actor="test")
        self.store.close()


@pytest.fixture
def env(tmp_path: Path, audit: RecordingAudit) -> Any:
    e = Env(tmp_path, audit)
    yield e
    e.close()


def test_end_to_end_subprocess_module(env: Env) -> None:
    env.add("kid", CHILD_MOD, request=("ui.panel",))
    env.policy.grant("kid", "ui.panel", actor="user")
    env.manager.activate("kid", actor="user")
    assert env.manager.info("kid").status is ModuleStatus.ACTIVE
    assert '"event":"hello"' in env.log_text("kid")
    assert env.panels.render("kid", "kid.status") == {"ok": True}
    env.bus.publish("core", "x.y", {"n": 42})
    assert env.store.module("kid").kv_get("last") == 42
    assert env.manager.health("kid") == (True, "child ok")
    env.manager.deactivate("kid", actor="user")
    assert env.panels.panels("kid") == []


def test_child_runs_with_scrubbed_environment(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWITCHYARD_TEST_SECRET", "canary-value")
    code = """
    import os
    class Mod:
        def activate(self, ctx):
            ctx.log("{id}", "env", keys=sorted(os.environ), cwd=os.getcwd())
        def deactivate(self): ...
        def health(self): return True
    """
    env.add("envmod", code)
    env.manager.activate("envmod", actor="user")
    rec = json.loads(env.log_text("envmod").splitlines()[0])
    assert "SWITCHYARD_TEST_SECRET" not in rec["fields"]["keys"]
    assert "SWITCHYARD_T2" in rec["fields"]["keys"]
    assert Path(rec["fields"]["cwd"]).resolve() == (env.root / "envmod").resolve()


def test_denied_capability_in_child_fails_closed(env: Env) -> None:
    env.add("kid", CHILD_MOD)  # ui.panel not requested or granted
    env.manager.activate("kid", actor="user")
    info = env.manager.info("kid")
    assert info.status is ModuleStatus.FAILED and info.error == "CapabilityDenied"
    assert "policy.denied" in env.audit.actions()


def test_child_state_is_confined(env: Env) -> None:
    code = """
    class Mod:
        def activate(self, ctx):
            ctx.state.execute("SELECT * FROM grants")
        def deactivate(self): ...
        def health(self): return True
    """
    env.add("sneaky", code)
    env.manager.activate("sneaky", actor="user")
    assert env.manager.info("sneaky").error == "StateError"


def test_child_cannot_spoof_core_events(env: Env) -> None:
    code = """
    class Mod:
        def activate(self, ctx):
            ctx.emit("module.activated", {"module": "other"})
        def deactivate(self): ...
        def health(self): return True
    """
    env.add("spoof", code)
    env.manager.activate("spoof", actor="user")
    assert env.manager.info("spoof").error == "SwitchyardError"


def test_exception_messages_do_not_cross(env: Env) -> None:
    code = """
    class Mod:
        def activate(self, ctx):
            raise ValueError("token=sk-SECRET-123")
        def deactivate(self): ...
        def health(self): return True
    """
    env.add("leaky", code)
    env.manager.activate("leaky", actor="user")
    assert env.manager.info("leaky").error == "ValueError"
    assert "sk-SECRET-123" not in json.dumps(env.audit.records)


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("import os\nos.write(1, b'\\xff\\xff\\xff\\xff')\nimport time\ntime.sleep(5)", "ProtocolError"),
        ("import os\nos._exit(3)", "ProtocolError"),
        ("raise ImportError('nope')", "ImportError"),
    ],
    ids=["oversize-frame", "crash", "import-error"],
)
def test_misbehaving_children_are_killed(env: Env, code: str, error: str) -> None:
    full = f"""
    class Mod:
        def activate(self, ctx):
{textwrap.indent(code, " " * 12)}
        def deactivate(self): ...
        def health(self): return True
    """
    if error == "ImportError":
        full = code
    env.add("bad", full)
    env.manager.activate("bad", actor="user")
    info = env.manager.info("bad")
    assert info.status is ModuleStatus.FAILED and info.error == error


def test_hanging_child_times_out(tmp_path: Path, audit: RecordingAudit) -> None:
    e = Env(tmp_path, audit, timeout=1.0)
    try:
        e.add("slow", "import time\nclass Mod:\n    def activate(self, ctx):\n        time.sleep(30)\n"
                      "    def deactivate(self): ...\n    def health(self): return True\n")  # fmt: skip
        e.manager.activate("slow", actor="user")
        assert e.manager.info("slow").error == "T2Timeout"
    finally:
        e.close()


def test_failing_child_event_handler_fails_module(env: Env) -> None:
    code = """
    class Mod:
        def activate(self, ctx):
            ctx.subscribe("x.y", self.on)
        def on(self, event):
            raise RuntimeError("boom")
        def deactivate(self): ...
        def health(self): return True
    """
    env.add("kid", code)
    env.manager.activate("kid", actor="user")
    env.bus.publish("core", "x.y", {})
    assert env.manager.info("kid").error == "RuntimeError"


def test_broker_access_is_policy_checked_then_unavailable(env: Env) -> None:
    code = """
    class Mod:
        def activate(self, ctx):
            ctx.schedule
        def deactivate(self): ...
        def health(self): return True
    """
    env.add("sched", code, request=("schedule",))
    with pytest.raises(CapabilityDenied):  # H1 A-5: no child process is started without the grant
        env.manager.activate("sched", actor="user")
    assert env.manager.info("sched").error is None
    env.policy.grant("sched", "schedule", actor="user")
    env.manager.activate("sched", actor="user")
    assert env.manager.info("sched").error == "SwitchyardError"  # granted, but brokers do not cross in M0


def test_t2_module_refuses_calls_after_kill(tmp_path: Path) -> None:
    from switchyard.manifest import load_manifest

    d = write_module(tmp_path, "kid", CHILD_MOD, isolation="subprocess")
    mod = T2Module(load_manifest(d))
    assert mod.health() == (False, "not running")
    mod.kill()  # harmless before start
    with pytest.raises(SwitchyardError, match="not running"):
        mod.deactivate()


def test_parent_rejects_bad_child_requests(env: Env) -> None:
    code = """
    class Mod:
        def activate(self, ctx):
            ctx._channel.request("ctx.state", {"op": "drop_all", "args": []})
        def deactivate(self): ...
        def health(self): return True
    """
    env.add("evil", code)
    env.manager.activate("evil", actor="user")
    assert env.manager.info("evil").error == "SwitchyardError"
    assert (
        env.manager.info("evil").status is ModuleStatus.FAILED
    )  # H1 D-27: the parent recorded it and lives on
    with pytest.raises(StateError):
        env.store.module("evil").execute("SELECT * FROM grants")


class FakeCtx:
    """Stands in for ModuleContext when probing the parent's request validation."""

    module_id = "kid"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def log(self, stream: str, event: str, **fields: Any) -> None:
        self.calls.append("log")

    def health_report(self, ok: bool, detail: str = "") -> None:
        self.calls.append("health_report")

    def subscribe(self, type_: str, handler: Any) -> None:
        self.calls.append("subscribe")


@pytest.mark.parametrize(
    ("method", "params", "fragment"),
    [
        ("ctx.log", {"stream": 1, "event": "e", "fields": {}}, "stream"),
        ("ctx.log", {"stream": "kid", "event": "e", "fields": []}, "fields"),
        ("ctx.subscribe", {"type": "x.y", "handler_id": "1"}, "handler_id"),
        ("ctx.health_report", {"ok": "yes"}, "boolean"),
        ("ctx.broker", {"capability": "root.everything"}, "broker"),
        ("ctx.state", {"op": "drop_all", "args": []}, "not allowed"),
        ("ctx.state", {"op": "kv_get", "args": "k"}, "not allowed"),
        ("ctx.unknown", {}, "unknown method"),
    ],
)
def test_parent_validates_child_requests(
    tmp_path: Path, method: str, params: dict[str, Any], fragment: str
) -> None:
    from switchyard.manifest import load_manifest

    mod = T2Module(load_manifest(write_module(tmp_path, "kid", CHILD_MOD, isolation="subprocess")))
    with pytest.raises(SwitchyardError, match="no context"):
        mod._dispatch("ctx.log", {})
    mod._ctx = FakeCtx()  # type: ignore[assignment]
    with pytest.raises(SwitchyardError, match=fragment):
        mod._dispatch(method, params)
    mod._dispatch("ctx.health_report", {"ok": True, "detail": "x" * 500})
    assert mod._ctx.calls == ["health_report"]  # type: ignore[attr-defined]


# H1 D-11: the flood kill and the stalled-writer kill run in the suite -------------------------------------


class _Proc:
    def __init__(self, stdin: Any = None) -> None:
        self.stdin = stdin
        self.killed = 0

    def kill(self) -> None:
        self.killed += 1


def test_h1_d11_flooding_child_is_killed(tmp_path: Path) -> None:
    import io

    from switchyard.host_t2 import MAX_PENDING_FRAMES, T2Module
    from switchyard.rpc import write_frame

    frames = io.BytesIO()
    for n in range(MAX_PENDING_FRAMES + 5):
        write_frame(frames, {"jsonrpc": "2.0", "method": "ctx.log", "params": {"n": n}})
    frames.seek(0)
    d = write_module(tmp_path, "flood", isolation="subprocess")
    mod = T2Module(load_manifest(d), timeout=0.2)
    mod._proc = _Proc()  # type: ignore[assignment]
    mod._reader(frames)  # nobody reads the inbox: the queue fills
    assert mod._flooded and mod._proc.killed == 1  # type: ignore[union-attr]


def test_h1_d11_child_that_stops_reading_is_killed(tmp_path: Path) -> None:
    import threading
    import time

    from switchyard.host_t2 import T2Module
    from switchyard.rpc import ProtocolError

    class Stuck:
        def __init__(self) -> None:
            self.gate = threading.Event()

        def write(self, data: bytes) -> int:
            self.gate.wait(10)  # the child never drains its stdin
            return len(data)

        def flush(self) -> None:
            pass

    d = write_module(tmp_path, "stuck", isolation="subprocess")
    mod = T2Module(load_manifest(d), timeout=0.3)
    stuck = Stuck()
    mod._proc = _Proc(stdin=stuck)  # type: ignore[assignment]
    start = time.monotonic()
    with pytest.raises(ProtocolError, match="stopped reading"):
        mod._send({"jsonrpc": "2.0", "id": 1, "method": "health", "params": {}})
    stuck.gate.set()
    assert mod._proc.killed == 1 and time.monotonic() - start < 2  # type: ignore[union-attr]


def test_h1_b14_send_counts_against_the_call_deadline(tmp_path: Path) -> None:
    import time

    from switchyard.rpc import Channel, ProtocolError

    sent: list[float | None] = []

    def slow_send(msg: Any) -> None:
        sent.append(channel.remaining())
        time.sleep(0.6)  # a slow write, within the old per-send budget

    def recv(timeout: float | None) -> Any:
        time.sleep(timeout or 0)
        return {"jsonrpc": "2.0", "method": "ctx.log", "params": {}, "id": 99}

    channel = Channel(slow_send, recv, lambda m, p: None)
    start = time.monotonic()
    with pytest.raises(ProtocolError, match="did not finish"):
        channel.request("health", {}, timeout=1.0)
    # The call's deadline is already running when the first send starts (before H1 it began after the send,
    # so a slow write did not count). Checked on the mechanism, not on wall-clock time, which CI jitter blurs.
    assert sent and sent[0] is not None and 0.5 < sent[0] <= 1.0
    assert all(later is not None and later < sent[0] for later in sent[1:])
    assert time.monotonic() - start < 4.0  # hang guard only
