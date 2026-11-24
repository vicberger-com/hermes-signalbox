"""H4 R1-F14: when Hermes unloads the plugin, Switchyard stops (ADR-0014, section "Unload").

Hermes runs the callbacks a plugin registered with ``ctx.on_unload`` when the plugin is disabled, uninstalled
or force-reloaded in a running process. Without one, the host lock, the loopback API and the active modules
stayed alive in that process until it exited.
"""

from __future__ import annotations

import os
import socket
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sy_testing import FakeHermesCtx, write_module

from switchyard import hermes as adapter_mod
from switchyard.core import Core
from switchyard.errors import SwitchyardError
from switchyard.hostlock import HostLock


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)
    monkeypatch.setattr(adapter_mod, "TICK_SECONDS", 0.05)
    monkeypatch.setattr(adapter_mod, "HOST_RETRY_SECONDS", 0.05)
    yield
    adapter_mod.shutdown()


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "plugin-data"
    write_module(root / "modules", "auto1", isolation="subprocess", activation="auto")
    (root / "config.toml").write_text("[api]\nenabled = true\nport = 0\n", encoding="utf-8")
    return root


def _records(data_dir: Path) -> list[dict[str, Any]]:
    with Core(data_dir=data_dir, hosting=False) as reader:
        return reader.audit_log.tail(500)


def _listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _lock_is_free(data_dir: Path) -> bool:
    other = HostLock(data_dir / "host.lock")  # what another process sees
    try:
        return other.acquire()
    finally:
        other.release()


def _tick_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "switchyard-tick" and t.is_alive()]


def _hosting_adapter(data_dir: Path) -> tuple[FakeHermesCtx, Any, int]:
    ctx = FakeHermesCtx(data_dir)
    adapter_mod.register(ctx)
    adapter = adapter_mod.current()
    assert adapter.core.hosting and adapter.core.manager.info("auto1").status.value == "active"
    port = int((data_dir / "api.port").read_text(encoding="utf-8"))
    assert _listening(port) and not _lock_is_free(data_dir)
    return ctx, adapter, port


# T4 ---------------------------------------------------------------------------------------------------


def test_h4_f14_unload_releases_the_lock_the_api_and_the_modules(data: Path) -> None:
    before = len(_tick_threads())
    ctx, adapter, port = _hosting_adapter(data)
    assert len(ctx.unload_callbacks) == 1
    ctx.unload()
    assert _lock_is_free(data), "the unloaded plugin still holds host.lock"
    assert not _listening(port), "the unloaded plugin still serves its API"
    assert not (data / "api.port").exists() and not (data / "api.token").exists()
    assert not adapter.driver_alive() and len(_tick_threads()) == before
    stopped = [r for r in _records(data) if r["action"] == "module.deactivated" and r["module"] == "auto1"]
    assert [r["detail"].get("reason") for r in stopped] == ["unload"]
    with pytest.raises(SwitchyardError, match="not registered"):
        adapter_mod.current()
    with Core(data_dir=data, hosting=False) as reader:
        assert reader.host_pid() is None


def test_h4_f14_after_unload_stale_hermes_references_do_nothing(data: Path) -> None:
    ctx, adapter, _port = _hosting_adapter(data)
    ctx.unload()
    count = len(_records(data))
    assert ctx.hooks["pre_llm_call"](user_message="hi") is None
    assert ctx.middleware["llm_request"](request={"model": "x"}) is None
    assert ctx.hooks["transform_terminal_output"](output="x", returncode=0) is None
    assert '"ok": false' in ctx.tools["switchyard_modules"]["handler"]({"action": "list"})
    assert ctx.commands["switchyard"]("module list").startswith("error")
    assert not adapter.core.hosting and _lock_is_free(data)
    assert len(_records(data)) == count  # nothing recorded, in particular no core.not_hosting


# T5 ---------------------------------------------------------------------------------------------------


def test_h4_f14_register_after_unload_hosts_again(data: Path) -> None:
    ctx, first, _port = _hosting_adapter(data)
    ctx.unload()
    _again_ctx, second, port = _hosting_adapter(data)  # a force reload: same process, new context
    assert second is not first and _listening(port)
    acquired = [r for r in _records(data) if r["action"] == "core.hosting_acquired"]
    assert [r["detail"]["pid"] for r in acquired] == [str(os.getpid())] * 2


def test_h4_f14_register_twice_without_unload_still_moves_hosting(data: Path) -> None:
    """The reload hypothesis: a second ``register`` in one process closes the first adapter itself."""
    _ctx, first, _port = _hosting_adapter(data)
    _ctx2, second, _port2 = _hosting_adapter(data)
    assert second is not first and not first.core.hosting and not first.driver_alive()


def test_h4_f14_unload_of_a_replaced_adapter_leaves_the_new_one_alone(data: Path) -> None:
    old_ctx, _first, _port = _hosting_adapter(data)
    _new_ctx, second, port = _hosting_adapter(data)
    old_ctx.unload()  # Hermes disposing the earlier load after the new one registered
    assert adapter_mod.current() is second and second.core.hosting and _listening(port)


# older hosts and failures ---------------------------------------------------------------------------------


def test_h4_f14_hermes_without_on_unload_still_loads(data: Path) -> None:
    class OldCtx(FakeHermesCtx):
        on_unload = None  # type: ignore[assignment]

    ctx = OldCtx(data)
    adapter_mod.register(ctx)
    assert adapter_mod.current().core.hosting and ctx.unload_callbacks == []


def test_h4_f14_a_failing_on_unload_registration_does_not_break_the_load(data: Path) -> None:
    class BrokenCtx(FakeHermesCtx):
        def on_unload(self, callback: Callable[[], None]) -> None:
            raise RuntimeError("host bug")

    adapter_mod.register(BrokenCtx(data))
    adapter = adapter_mod.current()
    assert adapter.core.hosting
    errors = [r for r in adapter.core.audit_log.tail(50) if r["action"] == "core.adapter_error"]
    assert [r["detail"] for r in errors] == [{"hook": "on_unload", "error": "RuntimeError"}]


def test_h4_f14_unload_callback_never_raises(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, adapter, _port = _hosting_adapter(data)

    def broken() -> None:
        raise RuntimeError("close bug")

    monkeypatch.setattr(adapter.core.bridge, "close", broken)
    ctx.unload()  # Hermes logs what escapes; nothing must
    assert _lock_is_free(data)  # and a failing step does not keep the lock


# the core ---------------------------------------------------------------------------------------------


def test_h4_f14_core_close_records_the_reason_it_is_given(tmp_path: Path) -> None:
    for reason in ("shutdown", "unload"):
        root = tmp_path / reason
        write_module(root / "modules", "auto1", isolation="subprocess", activation="auto")
        core = Core(data_dir=root, hosting=True)
        core.manager.start_auto(actor="core")
        if reason == "shutdown":
            core.close()  # the default, as before
        else:
            core.close(reason=reason)
        stopped = [r for r in _records(root) if r["action"] == "module.deactivated"]
        assert [r["detail"].get("reason") for r in stopped] == [reason]


def test_h4_f14_process_exit_still_records_shutdown(data: Path) -> None:
    _hosting_adapter(data)
    adapter_mod.shutdown()  # the atexit hook
    stopped = [r for r in _records(data) if r["action"] == "module.deactivated"]
    assert [r["detail"].get("reason") for r in stopped] == ["shutdown"]
    assert _lock_is_free(data)


def test_h4_f14_adapter_close_closes_the_core(data: Path) -> None:
    """The run's first root-cause note said ``close()`` left the core open. It does not; this pins it."""
    _ctx, adapter, port = _hosting_adapter(data)
    adapter.close()
    assert _lock_is_free(data) and not _listening(port)
    with pytest.raises(SwitchyardError, match="closed"):
        adapter.core.run("module", "list", {}, actor="cli")
