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
import hashlib
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
    bridge: Any = None  # HermesBridge (ADR-0004)
    call: Callable[[str, str, str, Mapping[str, Any]], Any] | None = None  # (caller, module, action, args)
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


class _Guarded:
    """A broker facade that re-checks, on every call, that the context is still open and the capability
    still granted (R1 review): a module that kept ``ctx.schedule`` after deactivation or revocation cannot
    use it."""

    __slots__ = ("_capability", "_ctx", "_facade")

    def __init__(self, facade: object, ctx: ModuleContext, capability: str) -> None:
        self._facade = facade
        self._ctx = ctx
        self._capability = capability

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):  # private state (a facade's broker) is never reachable (R1 follow-up)
            raise AttributeError(name)
        self._check()
        value = getattr(self._facade, name)
        if value is None or isinstance(value, str | int | float | bool | bytes):
            return value
        if not callable(value):
            return _Guarded(value, self._ctx, self._capability)  # nested objects are checked too

        def guarded(*args: Any, **kwargs: Any) -> Any:
            self._check()
            return value(*args, **kwargs)

        return guarded

    def _check(self) -> None:
        self._ctx._open()
        self._ctx._services.policy.require(self._ctx.module_id, self._capability)


_AUDIT_KEY_CHARS = 64
_AUDIT_VALUE_CHARS = 256
_CUT = "[truncated]"


def _audit_key(key: str) -> str:
    """At most 64 characters; a longer name keeps a short digest of the whole name, so two names that share
    their first 64 characters stay two fields (H1 A-27)."""
    if len(key) <= _AUDIT_KEY_CHARS:
        return key
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    return f"{key[: _AUDIT_KEY_CHARS - 9]}~{digest}"


def _audit_value(value: str) -> str:
    """At most 256 characters; a cut value ends with ``[truncated]`` (H1 A-27)."""
    if len(value) <= _AUDIT_VALUE_CHARS:
        return value
    return value[: _AUDIT_VALUE_CHARS - len(_CUT)] + _CUT


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
        """Receive events of ``type_``. Every event (``*``) and core events (``core.…``, including operator
        notifications from all modules) need ``core.read`` (R1 review)."""
        self._open()
        if type_ == "*" or type_.startswith("core."):
            self._services.policy.require(self.module_id, "core.read")
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
        clean = {_audit_key(str(k)): _audit_value(str(v)) for k, v in detail.items()}
        self._services.audit.append(actor=self.module_id, action=f"module.{self.module_id}.{event}",
                                    module=self.module_id, detail=clean)  # fmt: skip

    def has(self, capability: str) -> bool:
        """Whether this module currently holds ``capability`` (no audit record; use for optional features)."""
        self._open()
        return capability in self._services.policy.granted(self.module_id)

    def call(self, module_id: str, action: str, args: Mapping[str, Any] | None = None) -> Any:
        """Run another module's read-only action (ADR-0004)."""
        self._open()
        if self._services.call is None:
            raise SwitchyardError("cross-module calls are not available in this host")
        return self._services.call(self.module_id, module_id, action, dict(args or {}))

    def _bridge_check(self, declared: str) -> Any:
        self._open()
        self._services.policy.require(self.module_id, "hermes.hooks", hook=declared)
        if declared not in self._manifest.contributes["hooks"]:
            raise SwitchyardError(
                f"hook {declared!r} is not declared in contributes.hooks of {self.module_id!r}"
            )
        if self._services.bridge is None:
            raise SwitchyardError("the Hermes bridge is not available in this host")
        return self._services.bridge

    def hermes_hook(self, name: str, fn: Callable[[dict[str, Any]], Any]) -> None:
        """Observe a Hermes hook (``fn(kwargs)``; return value ignored). Needs ``hermes.hooks``."""
        from switchyard.bridge import OBSERVER_HOOKS

        if name not in OBSERVER_HOOKS:
            raise SwitchyardError(f"unsupported Hermes hook {name!r}; supported: {sorted(OBSERVER_HOOKS)}")
        self._bridge_check(name).add_hook(self.module_id, name, fn)

    def hermes_gate(self, fn: Callable[[dict[str, Any]], str | None]) -> None:
        """Register a turn gate (ADR-0006): ``fn(metadata) -> reason | None`` runs before each Hermes turn; a
        reason blocks the turn with that message. Needs ``hermes.hooks`` and ``gate:pre_llm_call`` declared in
        ``contributes.hooks``."""
        self._bridge_check("gate:pre_llm_call").add_gate(self.module_id, fn)

    def hermes_transform(self, kind: str, fn: Callable[[tuple[str, ...], dict[str, Any]], Any]) -> None:
        """Shorten Hermes output (ADR-0008): ``kind`` is ``terminal_output`` or ``tool_result``;
        ``fn(lines, meta) -> [[start, end), ...] | None`` names the lines to keep; the core rebuilds the text.
        Needs ``hermes.output`` (the module reads tool output) and ``transform:<kind>`` in
        ``contributes.hooks``."""
        if kind not in ("terminal_output", "tool_result"):
            raise SwitchyardError(f"unsupported transform {kind!r}")
        self._open()
        self._services.policy.require(self.module_id, "hermes.output", transform=kind)
        if f"transform:{kind}" not in self._manifest.contributes["hooks"]:
            raise SwitchyardError(
                f"hook 'transform:{kind}' is not declared in contributes.hooks of {self.module_id!r}"
            )
        if self._services.bridge is None:
            raise SwitchyardError("the Hermes bridge is not available in this host")
        self._services.bridge.add_transform(self.module_id, kind, fn)

    def hermes_delegation(self, route: Callable[[dict[str, Any]], Any], roles: Callable[[], Any]) -> None:
        """Route Hermes ``delegate_task`` tasks (ADR-0007). ``roles() -> [(name, description)]`` feeds the
        ``worker_role`` schema enum;
        ``route(meta) -> {"model", "provider"} | {"profile"} | {"refuse": code}``.
        Needs ``hermes.delegation``; one module at a time."""
        self._open()
        self._services.policy.require(self.module_id, "hermes.delegation")
        if self._services.bridge is None:
            raise SwitchyardError("the Hermes bridge is not available in this host")
        self._services.bridge.set_delegation(self.module_id, route, roles)

    def hermes_middleware(
        self,
        kind: str,
        fn: Callable[[dict[str, Any], dict[str, Any]], Any],
        fallback: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
    ) -> None:
        """Register Hermes middleware: ``fn(request, context) -> new request | None``.

        Needs ``hermes.hooks``; only the ``model`` key may change (ADR-0004). ``fallback`` (same signature)
        answers when ``fn`` misses the bridge deadline or fails; it must be fast and do no I/O that can
        block. ``context["claim"]()`` must return True before ``fn`` commits any side effect (ADR-0013).
        """
        from switchyard.bridge import MIDDLEWARE_KINDS

        if kind not in MIDDLEWARE_KINDS:
            raise SwitchyardError(f"unsupported middleware {kind!r}; supported: {sorted(MIDDLEWARE_KINDS)}")
        self._bridge_check(f"middleware:{kind}").add_middleware(self.module_id, kind, fn, fallback)

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
        facade = for_module(self.module_id) if callable(for_module) else broker
        return _Guarded(facade, self, capability)

    @property
    def notify(self) -> object:
        """Operator notifications (ADR-0009): ``ctx.notify.send(severity, title, detail)``.
        Needs ``notify``."""
        return self._broker("notify")

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
    def core(self) -> object:
        """Read-only view of module states and the audit chain (ADR-0006). Needs ``core.read``."""
        return self._broker("core.read")

    @property
    def hermes_config(self) -> object:
        """Hermes config writes (ADR-0005): allow-listed keys, backed up, audited, rolled back on failure.
        Needs ``hermes.config.write``."""
        return self._broker("hermes.config.write")

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
        s, mid = self._services, self.module_id
        optional = (
            getattr(s.actions, "remove_all", None),
            getattr(s.secret_backends, "remove_backends", None),
            getattr(s.bridge, "remove_all", None),
        )
        steps = [s.panels.remove_all, s.bus.unsubscribe_all, *(f for f in optional if f is not None)]
        first: BaseException | None = None
        for step in steps:  # H1 A-22: one failing step does not leave a secret backend or hook registered
            try:
                step(mid)
            except Exception as exc:
                first = first or exc
        if first is not None:
            raise first
