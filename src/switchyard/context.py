"""The per-module context handed to ``activate(ctx)`` (spec section 3, ModuleContext).

A context exposes only what its module may use. It holds no reference the module can follow to the core, other
modules or the policy engine through public members. Capability-gated members check the policy on every
access. ``close()`` (called by the lifecycle manager on deactivation) removes the module's panels and
subscriptions and makes every member raise, so a module that keeps a reference after deactivation can do
nothing with it.

Python cannot stop in-process code from reaching private attributes; this is a correctness and audit
control for reviewed T1 modules, not a containment boundary (DESIGN.md section 4). T2 modules get a proxy.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from switchyard.capabilities import PolicyEngine
from switchyard.errors import SwitchyardError
from switchyard.manifest import Manifest

_EVENT_SUFFIX = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\Z")


class LogSink(Protocol):
    def write(self, module_id: str, stream: str, event: str, fields: Mapping[str, Any]) -> None: ...


class PanelRegistry(Protocol):
    def add(self, module_id: str, panel_id: str, render: Callable[[], Any]) -> None: ...

    def remove_all(self, module_id: str) -> None: ...


class EventBusPort(Protocol):
    def publish(self, source: str, type_: str, data: Mapping[str, Any]) -> object: ...

    def subscribe(self, owner: str, type_: str, handler: Callable[..., None]) -> None: ...

    def unsubscribe_all(self, owner: str) -> None: ...


@dataclass(frozen=True)
class ContextServices:
    """Core services a context is built from. ``brokers`` maps a capability id to its broker facade."""

    policy: PolicyEngine
    logs: LogSink
    panels: PanelRegistry
    bus: EventBusPort
    brokers: Mapping[str, object] = field(default_factory=dict)
    state: Callable[[str], object] | None = None  # module id -> namespaced store (``StateStore.module``)


class MemoryPanelRegistry:
    """``PanelRegistry`` kept in memory; the control API and dashboard read panels from here."""

    def __init__(self) -> None:
        self._panels: dict[tuple[str, str], Callable[[], Any]] = {}

    def add(self, module_id: str, panel_id: str, render: Callable[[], Any]) -> None:
        self._panels[(module_id, panel_id)] = render

    def remove_all(self, module_id: str) -> None:
        self._panels = {k: v for k, v in self._panels.items() if k[0] != module_id}

    def panels(self, module_id: str) -> list[str]:
        return sorted(p for m, p in self._panels if m == module_id)

    def render(self, module_id: str, panel_id: str) -> Any:
        render = self._panels.get((module_id, panel_id))
        if render is None:
            raise SwitchyardError(f"unknown panel {panel_id!r} for module {module_id!r}")
        return render()


class ModuleContext:
    """What a module sees. Built by the lifecycle manager, one per activation."""

    __slots__ = ("_closed", "_last_health", "_manifest", "_services")

    def __init__(self, manifest: Manifest, services: ContextServices) -> None:
        self._manifest = manifest
        self._services = services
        self._closed = False
        self._last_health: tuple[bool, str] | None = None

    @property
    def module_id(self) -> str:
        return self._manifest.id

    @property
    def last_health(self) -> tuple[bool, str] | None:
        return self._last_health

    def _open(self) -> None:
        if self._closed:
            raise SwitchyardError(f"context for module {self.module_id!r} is closed")

    # always available ---------------------------------------------------------------------------------

    def log(self, stream: str, event: str, **fields: Any) -> None:
        """Write to one of the module's declared ``log_streams``."""
        self._open()
        if stream not in self._manifest.contributes["log_streams"]:
            raise SwitchyardError(f"log stream {stream!r} is not declared by module {self.module_id!r}")
        self._services.logs.write(self.module_id, stream, event, fields)

    def register_panel(self, panel_id: str, render: Callable[[], Any]) -> None:
        """Register a declared panel. Needs ``ui.panel``."""
        self._open()
        self._services.policy.require(self.module_id, "ui.panel", panel=panel_id)
        if panel_id not in self._manifest.contributes["panels"]:
            raise SwitchyardError(f"panel {panel_id!r} is not declared by module {self.module_id!r}")
        self._services.panels.add(self.module_id, panel_id, render)

    def emit(self, type_: str, data: Mapping[str, Any]) -> None:
        """Publish an event. Modules may only emit types under their own id: ``<module_id>.<name>``."""
        self._open()
        prefix = f"{self.module_id}."
        if not (type_.startswith(prefix) and _EVENT_SUFFIX.match(type_[len(prefix) :])):
            raise SwitchyardError(f"event type {type_!r} must look like '{prefix}<name>'")
        self._services.bus.publish(self.module_id, type_, data)

    def subscribe(self, type_: str, handler: Callable[..., None]) -> None:
        self._open()
        self._services.bus.subscribe(self.module_id, type_, handler)

    @property
    def state(self) -> object:
        """This module's namespaced store (tables ``m_<id>__*`` and key/value rows)."""
        self._open()
        if self._services.state is None:
            raise SwitchyardError("state store is not available in this host")
        return self._services.state(self.module_id)

    def health_report(self, ok: bool, detail: str = "") -> None:
        """Push a health state between ``health()`` polls. ``detail`` must not contain secret values."""
        self._open()
        self._last_health = (ok, detail)

    # capability-gated ---------------------------------------------------------------------------------

    def _broker(self, capability: str) -> object:
        self._open()
        self._services.policy.require(self.module_id, capability)
        broker = self._services.brokers.get(capability)
        if broker is None:
            raise SwitchyardError(f"{capability!r} is not available in this host")
        return broker

    @property
    def secrets(self) -> object:
        """Secrets broker facade. Needs ``secrets.read``."""
        return self._broker("secrets.read")

    @property
    def net(self) -> object:
        """Outbound network facade (host allow-list enforced inside). Needs ``net.outbound``."""
        return self._broker("net.outbound")

    @property
    def schedule(self) -> object:
        """Trigger registration facade. Needs ``schedule``."""
        return self._broker("schedule")

    @property
    def spawn(self) -> object:
        """Process launcher facade. Needs ``process.spawn``."""
        return self._broker("process.spawn")

    # lifecycle ----------------------------------------------------------------------------------------

    def close(self) -> None:
        """Remove panels and subscriptions; every later call raises. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._services.panels.remove_all(self.module_id)
        self._services.bus.unsubscribe_all(self.module_id)
