"""H4 R1-F8: which Hermes process hosts the modules (ADR-0014).

A process hosts only when it is the gateway runtime or has itself run a turn; a process that may host but
found the lock taken keeps trying. A plugin load for a one-shot command never hosts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sy_testing import FakeHermesCtx as FakeCtx
from sy_testing import write_module

from hermes_signalbox import hermes as adapter_mod
from hermes_signalbox.api import ApiClient, ApiUnavailable
from hermes_signalbox.core import Core
from hermes_signalbox.hermes import HermesAdapter
from hermes_signalbox.hostlock import HostLock

RETRY = 0.05
_REAL_GATEWAY_RUNTIME = adapter_mod._gateway_runtime  # the suite replaces it per test (tests/conftest.py)


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)
    monkeypatch.setattr(adapter_mod, "TICK_SECONDS", RETRY)
    monkeypatch.setattr(adapter_mod, "HOST_RETRY_SECONDS", RETRY)


@pytest.fixture
def data(tmp_path: Path) -> Path:
    """A plugin data directory with one ``auto`` module that needs no grant, and the loopback API on."""
    root = tmp_path / "plugin-data"
    write_module(root / "modules", "auto1", isolation="subprocess", activation="auto")
    (root / "config.toml").write_text("[api]\nenabled = true\nport = 0\n", encoding="utf-8")
    return root


@pytest.fixture
def adapters() -> Iterator[Callable[[Path], HermesAdapter]]:
    made: list[HermesAdapter] = []

    def make(data_dir: Path) -> HermesAdapter:
        adapter = HermesAdapter(FakeCtx(data_dir))
        made.append(adapter)
        adapter.register()
        return adapter

    yield make
    for adapter in reversed(made):
        adapter.close()


def _role(monkeypatch: pytest.MonkeyPatch, *, gateway: bool) -> None:
    monkeypatch.setattr(adapter_mod, "_gateway_runtime", lambda: gateway)


def _actions(data_dir: Path) -> list[str]:
    with Core(data_dir=data_dir, hosting=False) as reader:
        return [str(r["action"]) for r in reader.audit_log.tail(500)]


def _wait(condition: Callable[[], bool], periods: float = 2.0) -> bool:
    """True when ``condition`` holds within ``periods`` retry periods (plus scheduling slack)."""
    deadline = time.monotonic() + periods * RETRY + 5.0
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def _api_ready(data_dir: Path) -> bool:
    try:
        ApiClient.from_data_dir(data_dir)
    except ApiUnavailable:
        return False
    return True


def _status(adapter: HermesAdapter, module_id: str) -> str:
    return str(adapter.core.manager.info(module_id).status.value)


# T1 ---------------------------------------------------------------------------------------------------


def test_h4_f8_one_shot_command_load_never_hosts(
    data: Path, adapters: Callable[[Path], HermesAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    _role(monkeypatch, gateway=False)
    cli_load = adapters(data)
    time.sleep(4 * RETRY)  # several retry periods: a load that may not host must not start hosting later
    assert not cli_load.core.hosting
    assert _status(cli_load, "auto1") != "active"
    assert not (data / "api.port").exists()
    actions = _actions(data)
    assert "module.activated" not in actions and "core.hosting_acquired" not in actions
    other = HostLock(data / "host.lock")  # what another process sees: nobody hosts
    try:
        assert other.acquire()
    finally:
        other.release()


def test_h4_f8_plugin_cli_command_does_not_make_the_process_a_host(
    data: Path, adapters: Callable[[Path], HermesAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    _role(monkeypatch, gateway=False)
    cli_load = adapters(data)
    code = cli_load._cli_handler(argparse.Namespace(signalbox_json=True, signalbox_args=["module", "list"]))
    assert code == 0
    time.sleep(4 * RETRY)
    assert not cli_load.core.hosting
    assert "module.activated" not in _actions(data)


# T2 ---------------------------------------------------------------------------------------------------


def test_h4_f8_gateway_takes_over_hosting_when_the_lock_is_released(
    data: Path, adapters: Callable[[Path], HermesAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    _role(monkeypatch, gateway=True)
    elsewhere = HostLock(data / "host.lock")  # a one-shot process of the old release holds the lock
    assert elsewhere.acquire()
    try:
        gateway = adapters(data)
        assert not gateway.core.hosting and _status(gateway, "auto1") != "active"
        assert gateway.driver_alive()  # it keeps trying
    finally:
        elsewhere.release()
    assert _wait(lambda: gateway.core.hosting), "the gateway did not take over hosting within 2 retry periods"
    assert _wait(lambda: _status(gateway, "auto1") == "active")
    assert _wait(lambda: _api_ready(data))
    assert ApiClient.from_data_dir(data).request("module", "health", {"id": "auto1"})["ok"] is True
    with Core(data_dir=data, hosting=False) as reader:
        acquired = [r for r in reader.audit_log.tail(500) if r["action"] == "core.hosting_acquired"]
    assert len(acquired) == 1 and acquired[0]["detail"]["pid"] == str(os.getpid())


def test_h4_f8_gateway_hosts_at_load_when_the_lock_is_free(
    data: Path, adapters: Callable[[Path], HermesAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    _role(monkeypatch, gateway=True)
    gateway = adapters(data)
    assert gateway.core.hosting and _status(gateway, "auto1") == "active" and gateway.driver_alive()


def test_h4_f8_gateway_role_that_appears_after_load_is_picked_up(
    data: Path, adapters: Callable[[Path], HermesAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hermes can load plugins before the gateway has taken its own runtime lock."""
    role = {"gateway": False}
    monkeypatch.setattr(adapter_mod, "_gateway_runtime", lambda: role["gateway"])
    early = adapters(data)
    assert not early.core.hosting
    role["gateway"] = True
    assert _wait(lambda: early.core.hosting)
    assert _wait(lambda: _status(early, "auto1") == "active")


# T3 ---------------------------------------------------------------------------------------------------


def test_h4_f8_not_hosting_is_recorded_only_by_a_process_that_runs_turns(
    data: Path, adapters: Callable[[Path], HermesAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    _role(monkeypatch, gateway=False)
    elsewhere = HostLock(data / "host.lock")
    assert elsewhere.acquire()
    try:
        process = adapters(data)
        process._cli_handler(argparse.Namespace(signalbox_json=True, signalbox_args=["module", "list"]))
        time.sleep(4 * RETRY)
        assert "core.not_hosting" not in _actions(data)
        ctx: Any = process.ctx
        ctx.hooks["pre_llm_call"](user_message="hi")  # this process runs a turn while another one hosts
        ctx.hooks["pre_llm_call"](user_message="again")
        assert _actions(data).count("core.not_hosting") == 1
        assert not process.core.hosting
    finally:
        elsewhere.release()
    # a process that runs turns may host: it takes over once the lock is free
    assert _wait(lambda: process.core.hosting)
    assert _wait(lambda: _status(process, "auto1") == "active")


def test_h4_f8_first_turn_in_a_process_makes_it_host_before_the_turn_goes_out(
    data: Path, adapters: Callable[[Path], HermesAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    _role(monkeypatch, gateway=False)
    process = adapters(data)
    assert not process.core.hosting
    seen: list[bool] = []
    monkeypatch.setattr(process.core.bridge, "dispatch_gate", lambda kwargs: seen.append(True) or None)
    ctx: Any = process.ctx
    ctx.hooks["pre_llm_call"](user_message="hi")
    assert process.core.hosting and _status(process, "auto1") == "active"
    assert seen == [True]  # the gate ran for this very turn
    assert "core.not_hosting" not in _actions(data)


@pytest.mark.parametrize("surface", ["tool", "command", "middleware", "transform"])
def test_h4_f8_every_turn_surface_counts_as_running_turns(
    data: Path, adapters: Callable[[Path], HermesAdapter], monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    _role(monkeypatch, gateway=False)
    process = adapters(data)
    ctx: Any = process.ctx
    if surface == "tool":
        ctx.tools["signalbox_modules"]["handler"]({"action": "list"})
    elif surface == "command":
        ctx.commands["signalbox"]("module list")
    elif surface == "middleware":
        ctx.middleware["llm_request"](request={"model": "x"})
    else:
        ctx.hooks["transform_terminal_output"](output="x", returncode=0)
    assert process.core.hosting


# the gateway signal ------------------------------------------------------------------------------------


def test_h4_f8_gateway_runtime_is_read_from_hermes_own_ownership_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter_mod, "_gateway_runtime", _REAL_GATEWAY_RUNTIME)
    monkeypatch.delitem(sys.modules, "gateway.status", raising=False)
    assert adapter_mod._gateway_runtime() is False  # Hermes's gateway code is not even loaded here
    status = types.ModuleType("gateway.status")
    monkeypatch.setitem(sys.modules, "gateway.status", status)
    assert adapter_mod._gateway_runtime() is False  # an older Hermes without the check
    status.owns_gateway_runtime_lock = lambda: True  # type: ignore[attr-defined]
    assert adapter_mod._gateway_runtime() is True
    status.owns_gateway_runtime_lock = lambda: False  # type: ignore[attr-defined]
    assert adapter_mod._gateway_runtime() is False

    def broken() -> bool:
        raise RuntimeError("status bug")

    status.owns_gateway_runtime_lock = broken  # type: ignore[attr-defined]
    assert adapter_mod._gateway_runtime() is False


def test_h4_f8_gateway_marker_variable_does_not_make_a_host(
    data: Path, adapters: Callable[[Path], HermesAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shells started by the gateway inherit its marker variable; commands run there are still one-shot."""
    monkeypatch.setenv("_HERMES_GATEWAY", "1")
    monkeypatch.setattr(adapter_mod, "_gateway_runtime", _REAL_GATEWAY_RUNTIME)
    monkeypatch.delitem(sys.modules, "gateway.status", raising=False)
    child = adapters(data)
    time.sleep(4 * RETRY)
    assert not child.core.hosting


# who hosts ---------------------------------------------------------------------------------------------


def test_h4_f8_show_health_and_config_name_the_hosting_process(
    data: Path, adapters: Callable[[Path], HermesAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    with Core(data_dir=data, hosting=False) as reader:
        assert reader.host_pid() is None
        assert reader.run("config", "show", {}, actor="cli")["hosting"] == {"here": False, "pid": None}
    _role(monkeypatch, gateway=True)
    gateway = adapters(data)
    me = os.getpid()
    assert gateway.core.run("module", "show", {"id": "auto1"}, actor="cli")["host_pid"] == me
    assert gateway.core.run("module", "health", {"id": "auto1"}, actor="cli")["host_pid"] == me
    assert gateway.core.run("config", "show", {}, actor="cli")["hosting"] == {"here": True, "pid": me}
    with Core(data_dir=data, hosting=False) as reader:  # a CLI process reading the same directory
        assert reader.host_pid() == me
        assert reader.run("module", "show", {"id": "auto1"}, actor="cli")["host_pid"] == me
        assert reader.run("config", "show", {}, actor="cli")["hosting"] == {"here": False, "pid": me}
    gateway.close()
    with Core(data_dir=data, hosting=False) as reader:
        assert reader.host_pid() is None


def test_h4_f8_host_pid_of_a_dead_host_is_not_reported(data: Path) -> None:
    with Core(data_dir=data, hosting=True) as host:
        host.store.core_execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", ("core.host_pid", "424242")
        )
        # the record survives a crash; the lock does not
        host._host_lock.release()
        host.hosting = False
        assert host.host_pid() is None


def test_h4_f8_standalone_core_still_hosts_when_free(tmp_path: Path) -> None:
    """The daemon and library users are unchanged: ``Core()`` hosts when nobody else does."""
    with Core(data_dir=tmp_path / "d") as core:
        assert core.hosting and core.host_pid() == os.getpid()
        assert core.acquire_hosting() is True  # already hosting: no second record
        actions = [r["action"] for r in core.audit_log.tail(50)]
        assert actions.count("core.hosting_acquired") == 0


def test_h4_f8_acquire_hosting_after_close_is_refused(tmp_path: Path) -> None:
    core = Core(data_dir=tmp_path / "d", hosting=False)
    core.close()
    assert core.acquire_hosting() is False
    lock = HostLock(tmp_path / "d" / "host.lock")
    try:
        assert lock.acquire()
    finally:
        lock.release()


def test_h4_f8_delegation_backend_follows_live_hosting(
    data: Path, adapters: Callable[[Path], HermesAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    base = types.ModuleType("agent.delegation_provider")
    base.DelegationProvider = type("DelegationProvider", (), {})  # type: ignore[attr-defined]
    base.DelegationRouteError = type("DelegationRouteError", (Exception,), {})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.delegation_provider", base)
    providers: list[Any] = []
    monkeypatch.setattr(FakeCtx, "register_delegation_provider", providers.append, raising=False)
    _role(monkeypatch, gateway=False)
    process = adapters(data)
    monkeypatch.setattr(process.core.bridge, "delegation_active", lambda: True)
    assert providers and providers[0].is_available() is False
    ctx: Any = process.ctx
    ctx.hooks["pre_llm_call"](user_message="hi")
    assert process.core.hosting and providers[0].is_available() is True


def test_h4_f8_close_stops_a_process_that_is_still_waiting_to_host(
    data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _role(monkeypatch, gateway=True)
    elsewhere = HostLock(data / "host.lock")
    assert elsewhere.acquire()
    try:
        waiting = HermesAdapter(FakeCtx(data))
        waiting.register()
        waiting.close()
        assert not waiting.driver_alive()
    finally:
        elsewhere.release()
    time.sleep(4 * RETRY)
    assert not waiting.core.hosting and "core.hosting_acquired" not in _actions(data)
    assert json.loads(waiting.tool_host({}))["ok"] is False  # the core is closed
