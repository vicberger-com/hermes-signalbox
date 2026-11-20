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

import copy
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
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


_ACTION_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
ACTION_PARAM_KINDS = (bool, int, str)


@dataclass(frozen=True)
class Action:
    module_id: str
    name: str
    handler: Callable[..., Any]
    params: Mapping[str, type]
    read_only: bool


class MemoryActionRegistry:
    """Module actions (ADR-0002), keyed by ``(module_id, name)``."""

    def __init__(self) -> None:
        self._actions: dict[tuple[str, str], Action] = {}

    def add(self, action: Action) -> None:
        self._actions[(action.module_id, action.name)] = action

    def remove_all(self, module_id: str) -> None:
        self._actions = {k: v for k, v in self._actions.items() if k[0] != module_id}

    def names(self, module_id: str) -> list[str]:
        return sorted(n for m, n in self._actions if m == module_id)

    def get(self, module_id: str, name: str) -> Action:
        action = self._actions.get((module_id, name))
        if action is None:
            raise SwitchyardError(f"unknown action {name!r} for module {module_id!r} (is it running?)")
        return action


class SecretBackendPort(Protocol):
    def add_backend(self, owner: str, backend: Any) -> None: ...
    def remove_backends(self, owner: str) -> None: ...


@dataclass(frozen=True)
class ContextServices:
    """Core services a context is built from. ``brokers`` maps a capability id to its broker facade."""

    policy: PolicyEngine
    logs: LogSink
    panels: PanelRegistry
    bus: EventBusPort
    brokers: Mapping[str, object] = field(default_factory=dict)
    state: Callable[[str], object] | None = None  # module id -> namespaced store (``StateStore.module``)
    actions: MemoryActionRegistry | None = None
    config: Callable[[str], Mapping[str, Any]] | None = None  # module id -> its [modules.<id>] settings
    audit: Any = None  # AuditSink for ``ctx.audit``
    secret_backends: SecretBackendPort | None = None


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

    @property
    def config(self) -> Mapping[str, Any]:
        """This module's settings from ``[modules.<id>]`` in the core ``config.toml`` (read-only copy)."""
        self._open()
        if self._services.config is None:
            return MappingProxyType({})
        return MappingProxyType(copy.deepcopy(dict(self._services.config(self.module_id))))

    def audit(self, event: str, **detail: str) -> None:
        """Append ``module.<id>.<event>`` to the audit log. Record names and outcomes, never secret values
        (the audit sink redacts known values as a backstop)."""
        self._open()
        if not _EVENT_SUFFIX.match(event) or len(detail) > 16:
            raise SwitchyardError(
                f"audit event {event!r} must look like '<name>[.<name>]' with at most 16 fields"
            )
        if self._services.audit is None:
            raise SwitchyardError("the audit log is not available in this host")
        clean = {str(k)[:64]: str(v)[:256] for k, v in detail.items()}
        self._services.audit.append(actor=self.module_id, action=f"module.{self.module_id}.{event}",
                                    module=self.module_id, detail=clean)  # fmt: skip

    def health_report(self, ok: bool, detail: str = "") -> None:
        """Push a health state between ``health()`` polls. ``detail`` must not contain secret values."""
        self._open()
        self._last_health = (ok, detail)

    def register_action(
        self,
        name: str,
        handler: Callable[..., Any],
        *,
        params: Mapping[str, type] | None = None,
        read_only: bool = False,
    ) -> None:
        """Expose ``handler`` as ``module action`` (ADR-0002). ``name`` must be in ``contributes.commands``;
        ``params`` maps argument names to ``bool``, ``int`` or ``str``. Only ``read_only`` actions are offered
        to the Hermes model tool."""
        self._open()
        if not _ACTION_NAME.match(name) or name not in self._manifest.contributes["commands"]:
            raise SwitchyardError(
                f"action {name!r} is not declared in contributes.commands of {self.module_id!r}"
            )
        spec = dict(params or {})
        for key, kind in spec.items():
            if not _ACTION_NAME.match(key) or kind not in ACTION_PARAM_KINDS:
                raise SwitchyardError(f"action {name!r}: parameter {key!r} must be bool, int or str")
        if self._services.actions is None:
            raise SwitchyardError("module actions are not available in this host")
        self._services.actions.add(Action(self.module_id, name, handler, spec, bool(read_only)))

    # capability-gated ---------------------------------------------------------------------------------

    def provide_secret_backend(self, backend: Any) -> None:
        """Add a secret backend to the core broker (ADR-0002).

        Only for in-process modules from a trusted root, granted ``secrets.read``, for a backend name declared
        in ``contributes.secret_backends``.
        """
        self._open()
        if self._manifest.isolation != "in-process":
            raise SwitchyardError("only in-process modules from a trusted root may provide secret backends")
        self._services.policy.require(self.module_id, "secrets.read")
        name = getattr(backend, "name", None)
        if not isinstance(name, str) or name not in self._manifest.contributes["secret_backends"]:
            raise SwitchyardError(f"secret backend {name!r} is not declared by module {self.module_id!r}")
        if self._services.secret_backends is None:
            raise SwitchyardError("the secrets broker is not available in this host")
        self._services.secret_backends.add_backend(self.module_id, backend)

    def _broker(self, capability: str) -> object:
        self._open()
        self._services.policy.require(self.module_id, capability)
        broker = self._services.brokers.get(capability)
        if broker is None:
            raise SwitchyardError(f"{capability!r} is not available in this host")
        for_module = getattr(broker, "for_module", None)
        return for_module(self.module_id) if callable(for_module) else broker

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
    def fs(self) -> object:
        """File-read facade (ADR-0003). Needs ``fs.read``."""
        return self._broker("fs.read")

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
        if self._services.actions is not None:
            self._services.actions.remove_all(self.module_id)
        if self._services.secret_backends is not None:
            self._services.secret_backends.remove_backends(self.module_id)
