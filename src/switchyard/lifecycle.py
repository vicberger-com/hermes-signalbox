"""Module lifecycle manager, T1 in-process (spec section 3, Lifecycle).

``discover -> verified -> active <-> stopped``, with ``failed`` reachable from any step. Activation mode is
``manual``, ``auto`` or ``disabled`` and persists in the state store.

* **Trust.** A module with ``isolation = "in-process"`` is accepted only from a trusted root (resolved paths,
  so ``..`` and symlinks cannot smuggle a directory in). Everything else must declare ``subprocess`` and runs
  in the T2 host.
* **Import isolation.** Each module is imported as the synthetic package ``_switchyard_modules.<id>`` whose
  search path is the module directory, so two modules may both contain ``mod.py``, relative imports work, and
  removal purges exactly that module's entries from ``sys.modules``.
* **Fail closed.** An exception from import, construction, ``activate``, ``health`` or one of the module's
  bus handlers stops that module and marks it ``failed`` (audited by exception class only; messages can carry
  secrets). The core keeps running.
* **Cleanup.** Deactivation always closes the module's context (panels, subscriptions) and removes its
  triggers, even when the module's own ``deactivate`` raises.
"""

from __future__ import annotations

import importlib
import sys
import threading
import time
import types
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import switchyard
from switchyard.capabilities import CORE_ACTOR, AuditSink, PolicyEngine
from switchyard.context import (
    ContextServices,
    LogSink,
    MemoryActionRegistry,
    ModuleContext,
    PanelRegistry,
    SecretBackendPort,
)
from switchyard.discovery import _VERIFIED_KEY, ModuleDirectory, _Entry
from switchyard.discovery import ModuleInfo as ModuleInfo  # re-exported: callers import it from lifecycle
from switchyard.discovery import ModuleStatus as ModuleStatus  # re-exported likewise
from switchyard.errors import CapabilityDenied, SwitchyardError, UsageError
from switchyard.events import EventBus
from switchyard.host_t2 import T2Module
from switchyard.manifest import Manifest, core_compatibility, load_manifest, loaded_inside
from switchyard.scheduler import Scheduler
from switchyard.state import StateStore

PACKAGE_ROOT = "_switchyard_modules"
MODES = frozenset({"manual", "auto", "disabled"})
REQUIRED_METHODS = ("activate", "deactivate", "health")
_MAX_HEALTH_DETAIL = 200


def _error_name(exc: BaseException) -> str:
    """Exception class name; for errors raised inside a T2 child, the child's original class."""
    remote = getattr(exc, "remote_type", None)
    return remote if isinstance(remote, str) else type(exc).__name__


class ModuleManager(ModuleDirectory):
    def __init__(
        self,
        *,
        policy: PolicyEngine,
        audit: AuditSink,
        bus: EventBus,
        logs: LogSink,
        panels: PanelRegistry,
        trusted_roots: Sequence[Path],
        scheduler: Scheduler | None = None,
        store: StateStore | None = None,
        brokers: Mapping[str, object] | None = None,
        actions: MemoryActionRegistry | None = None,
        secret_backends: SecretBackendPort | None = None,
        config: Callable[[str], Mapping[str, Any]] | None = None,
        bridge: Any = None,
        call: Callable[[str, str, str, Mapping[str, Any]], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        t2_factory: Callable[[Manifest], Any] = T2Module,
    ) -> None:
        self._policy = policy
        self._audit = audit
        self._bus = bus
        self._scheduler = scheduler
        self._store = store
        self._trusted = [p.resolve() for p in trusted_roots]
        self._clock = clock
        self._t2_factory = t2_factory
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.RLock()
        self._services = ContextServices(
            policy=policy, logs=logs, panels=panels, bus=bus, brokers=dict(brokers or {}),
            state=store.module if store is not None else None, actions=actions,
            secret_backends=secret_backends, config=config, audit=audit, bridge=bridge, call=call,
        )  # fmt: skip
        bus.set_error_handler(self._on_handler_error)

    # queries ------------------------------------------------------------------------------------------

    def _entry(self, module_id: str) -> _Entry:
        entry = self._entries.get(module_id)
        if entry is None:
            raise UsageError(f"unknown module {module_id!r}")
        return entry

    def ids(self) -> list[str]:
        with self._lock:
            return sorted(self._entries)

    def info(self, module_id: str) -> ModuleInfo:
        with self._lock:
            e = self._entry(module_id)
            m = e.manifest
            mode = self._current_mode(e)
            return ModuleInfo(
                m.id, m.version, e.status, mode, m.isolation, m.directory, e.error, e.stop_reason
            )

    def manifest(self, module_id: str) -> Manifest:
        with self._lock:
            return self._entry(module_id).manifest

    def modules(self) -> list[ModuleInfo]:
        return [self.info(i) for i in self.ids()]

    # records ------------------------------------------------------------------------------------------

    def reload(self, module_id: str) -> None:
        """Re-read a stopped module's manifest from its directory (after an update swapped the directory)."""
        with self._lock:
            e = self._entry(module_id)
            if e.status is ModuleStatus.ACTIVE:
                raise SwitchyardError(f"module {module_id!r} must be stopped before reload")
            directory = e.manifest.directory
            manifest = load_manifest(directory)
            if manifest.id != module_id:
                raise SwitchyardError(f"manifest in {directory} now declares id {manifest.id!r}")
            verdict, why = core_compatibility(manifest.requires_core, switchyard.__version__)
            if verdict == "incompatible":
                raise SwitchyardError(why)
            if manifest.isolation == "in-process" and not self._is_trusted(directory):
                raise SwitchyardError(
                    "module is outside the trusted roots; it must use isolation = 'subprocess'"
                )
            self._policy.register(manifest)
            self._unload(module_id)
            e.manifest, e.status, e.error = manifest, ModuleStatus.VERIFIED, None
            self._persist(e)
        self._record("module.reloaded", module_id, CORE_ACTOR, version=manifest.version)

    # loading ------------------------------------------------------------------------------------------

    @staticmethod
    def _package(module_id: str) -> str:
        return f"{PACKAGE_ROOT}.{module_id}"

    def _unload(self, module_id: str) -> None:
        prefix = self._package(module_id)
        for name in [n for n in sys.modules if n == prefix or n.startswith(prefix + ".")]:
            del sys.modules[name]

    def _instantiate(self, manifest: Manifest) -> Any:
        if PACKAGE_ROOT not in sys.modules:
            root = types.ModuleType(PACKAGE_ROOT)
            root.__path__ = []
            sys.modules[PACKAGE_ROOT] = root
        self._unload(manifest.id)
        importlib.invalidate_caches()
        package = types.ModuleType(self._package(manifest.id))
        package.__path__ = [str(manifest.directory)]
        sys.modules[package.__name__] = package
        module = importlib.import_module(f"{package.__name__}.{manifest.entry_module}")
        if not loaded_inside(module, manifest.directory):  # H1 A-3: what ran must be what was checked
            self._unload(manifest.id)
            raise SwitchyardError(f"module {manifest.id!r}: entry code was loaded from outside its directory")
        cls = getattr(module, manifest.entry_class)
        missing = [m for m in REQUIRED_METHODS if not callable(getattr(cls, m, None))]
        if missing:
            raise TypeError(f"entry class lacks {missing}")
        return cls()

    # transitions --------------------------------------------------------------------------------------

    def activate(self, module_id: str, *, actor: str) -> None:
        with self._lock:
            e = self._entry(module_id)
            if self._current_mode(e) == "disabled":  # H4 R1-F9: as the store has it now
                # H3-23: use ModuleNotRunning for clearer semantics
                from switchyard.errors import ModuleNotRunning

                raise ModuleNotRunning(f"module {module_id!r} is disabled")
            if e.status is ModuleStatus.ACTIVE:
                e.last_used = self._clock()
                return
            # H1 A-5: no module code runs (no import, no activate) until every required capability is granted,
            # whoever asks. The module stays as it was; nothing is marked failed.
            missing = sorted(e.manifest.requested - e.manifest.optional - self._policy.granted(module_id))
            if missing:
                self._audit.append(
                    actor=CORE_ACTOR,
                    action="policy.denied",
                    module=module_id,
                    detail={"capability": ",".join(missing), "operation": "module activate", "actor": actor},
                )
                raise CapabilityDenied(
                    f"module {module_id!r} cannot start: not granted {', '.join(missing)} "
                    f"(grant with 'module grant {module_id} --capability <name>')"
                )
            try:
                if e.manifest.isolation == "subprocess":
                    instance = self._t2_factory(e.manifest)
                else:
                    instance = self._instantiate(e.manifest)
            except Exception as exc:
                self._fail(e, exc)
                return
            ctx = ModuleContext(e.manifest, self._services)
            try:
                instance.activate(ctx)
            except Exception as exc:
                ctx.close()
                self._fail(e, exc)
                return
            e.instance, e.ctx, e.status, e.error = instance, ctx, ModuleStatus.ACTIVE, None
            e.last_used = self._clock()
            self._persist(e)
        self._record("module.activated", module_id, actor)

    def _cleanup(self, e: _Entry) -> None:
        if e.ctx is not None:
            e.ctx.close()
        if self._scheduler is not None:
            self._scheduler.remove_owner(e.manifest.id)
        e.instance, e.ctx = None, None

    def _fail(self, e: _Entry, exc: BaseException) -> None:
        with self._lock:
            was_active = e.status is ModuleStatus.ACTIVE
            if was_active and e.instance is not None:
                try:
                    e.instance.deactivate()
                except Exception as cleanup_exc:
                    self._audit.append(
                        actor=CORE_ACTOR,
                        action="module.deactivate_failed",
                        module=e.manifest.id,
                        detail={"error": _error_name(cleanup_exc)},
                    )
            self._cleanup(e)
            e.status, e.error = ModuleStatus.FAILED, _error_name(exc)
            self._persist(e)
        self._record("module.failed", e.manifest.id, CORE_ACTOR, error=_error_name(exc))

    def _on_handler_error(self, owner: str, exc: BaseException) -> None:
        with self._lock:
            e = self._entries.get(owner)
            if e is None or e.status is not ModuleStatus.ACTIVE:
                return
        self._fail(e, exc)

    def deactivate(self, module_id: str, *, actor: str, reason: str = "") -> None:
        with self._lock:
            e = self._entry(module_id)
            if e.status is not ModuleStatus.ACTIVE:
                return
            try:
                e.instance.deactivate()
            except Exception as exc:
                self._audit.append(
                    actor=CORE_ACTOR,
                    action="module.deactivate_failed",
                    module=module_id,
                    detail={"error": _error_name(exc)},
                )
            finally:
                self._cleanup(e)
                e.status = ModuleStatus.STOPPED
                e.stop_reason = reason or "operator"
                self._persist(e)
        detail = {"reason": reason} if reason else {}
        self._record("module.deactivated", module_id, actor, **detail)

    def health(self, module_id: str) -> tuple[bool, str]:
        """Poll the module's ``health()``. An exception fails the module closed."""
        with self._lock:
            e = self._entry(module_id)
            if e.status is not ModuleStatus.ACTIVE:
                return False, e.status.value
            instance = e.instance
        try:
            result = instance.health()
        except Exception as exc:
            self._fail(e, exc)
            return False, f"health check raised {_error_name(exc)}"
        return self._normalise_health(result)

    @staticmethod
    def _normalise_health(result: Any) -> tuple[bool, str]:
        if isinstance(result, bool):
            return result, ""
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
            return result[0], str(result[1])[:_MAX_HEALTH_DETAIL]
        ok = getattr(result, "ok", None)
        if isinstance(ok, bool):
            return ok, str(getattr(result, "detail", ""))[:_MAX_HEALTH_DETAIL]
        return False, "invalid health result"

    def set_mode(self, module_id: str, mode: str, *, actor: str) -> None:
        if mode not in MODES:
            raise UsageError(f"invalid mode {mode!r}; expected one of {sorted(MODES)}")
        with self._lock:
            e = self._entry(module_id)
            if mode == "disabled" and e.status is ModuleStatus.ACTIVE:
                self.deactivate(module_id, actor=actor, reason="disabled")
            e.mode = mode
            self._persist_mode(e)  # H4 R1-F9: the mode column only; the hosting process owns ``state``
        self._record("module.mode_changed", module_id, actor, mode=mode)

    def start_auto(self, *, actor: str) -> None:
        """Activate every ``auto`` module that is stopped or verified and holds every capability it requests
        except those listed as ``optional``.

        A module still waiting for grants is left alone (``module.auto_skipped``) rather than failed."""
        for module_id in self.ids():
            e = self._entries[module_id]
            if self._current_mode(e) == "auto" and e.status in (ModuleStatus.VERIFIED, ModuleStatus.STOPPED):
                missing = sorted(e.manifest.requested - e.manifest.optional - self._policy.granted(module_id))
                if missing:
                    self._record("module.auto_skipped", module_id, actor, missing=",".join(missing))
                    continue
                self.activate(module_id, actor=actor)

    def touch(self, module_id: str) -> None:
        """Mark a module as used now (resets its idle timer)."""
        with self._lock:
            self._entry(module_id).last_used = self._clock()

    def tick(self) -> None:
        """Stop modules another process set to ``disabled`` (H4 R1-F9), and ``auto`` modules idle for
        ``idle_stop_seconds``."""
        now = self._clock()
        for module_id in self.ids():
            e = self._entries[module_id]
            if e.status is not ModuleStatus.ACTIVE:
                continue
            mode = self._current_mode(e)
            if mode == "disabled":
                self.deactivate(module_id, actor=CORE_ACTOR, reason="disabled")
                continue
            idle = e.manifest.idle_stop_seconds
            if mode == "auto" and idle > 0 and now - e.last_used >= idle:
                self.deactivate(module_id, actor=CORE_ACTOR, reason="idle")

    def remove(self, module_id: str, *, actor: str, keep_data: bool = False) -> None:
        """Stop and forget a module. Drops its grants, and its stored data unless ``keep_data``."""
        with self._lock:
            self._entry(module_id)
            self.deactivate(module_id, actor=actor, reason="remove")
            self._unload(module_id)
            # Grants never survive removal (R1 review): consent was given to the code that was installed; a
            # different module could later appear under the same id. keep_data keeps stored data only.
            self._policy.unregister(module_id, actor=actor, keep_grants=False)
            if self._store is not None:
                if not keep_data:
                    self._store.module(module_id).drop_all()
                self._store.core_execute("DELETE FROM modules WHERE id = ?", (module_id,))
                self._store.core_execute("DELETE FROM meta WHERE key = ?", (_VERIFIED_KEY + module_id,))
            del self._entries[module_id]
        self._record("module.removed", module_id, actor, keep_data=str(keep_data).lower())
