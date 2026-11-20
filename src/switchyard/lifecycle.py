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

import enum
import importlib
import sys
import threading
import time
import types
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from switchyard.capabilities import CORE_ACTOR, AuditSink, PolicyEngine
from switchyard.context import ContextServices, LogSink, ModuleContext, PanelRegistry
from switchyard.errors import ManifestError, SwitchyardError
from switchyard.events import EventBus
from switchyard.host_t2 import T2Module
from switchyard.manifest import MANIFEST_NAME, Manifest, load_manifest
from switchyard.scheduler import Scheduler
from switchyard.state import StateStore

PACKAGE_ROOT = "_switchyard_modules"
MODES = frozenset({"manual", "auto", "disabled"})
REQUIRED_METHODS = ("activate", "deactivate", "health")
_MAX_REASON = 900
_MAX_HEALTH_DETAIL = 200


class ModuleStatus(enum.Enum):
    VERIFIED = "verified"
    ACTIVE = "active"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class ModuleInfo:
    id: str
    version: str
    status: ModuleStatus
    mode: str
    isolation: str
    path: Path
    error: str | None

    @property
    def state(self) -> ModuleStatus:
        return self.status


@dataclass
class _Entry:
    manifest: Manifest
    mode: str
    status: ModuleStatus = ModuleStatus.VERIFIED
    error: str | None = None
    instance: Any = None
    ctx: ModuleContext | None = None
    last_used: float = 0.0


def _error_name(exc: BaseException) -> str:
    """Exception class name; for errors raised inside a T2 child, the child's original class."""
    remote = getattr(exc, "remote_type", None)
    return remote if isinstance(remote, str) else type(exc).__name__


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ModuleManager:
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
            state=store.module if store is not None else None,
        )  # fmt: skip
        bus.set_error_handler(self._on_handler_error)

    # queries ------------------------------------------------------------------------------------------

    def _entry(self, module_id: str) -> _Entry:
        entry = self._entries.get(module_id)
        if entry is None:
            raise SwitchyardError(f"unknown module {module_id!r}")
        return entry

    def ids(self) -> list[str]:
        with self._lock:
            return sorted(self._entries)

    def info(self, module_id: str) -> ModuleInfo:
        with self._lock:
            e = self._entry(module_id)
            m = e.manifest
            return ModuleInfo(m.id, m.version, e.status, e.mode, m.isolation, m.directory, e.error)

    def manifest(self, module_id: str) -> Manifest:
        with self._lock:
            return self._entry(module_id).manifest

    def modules(self) -> list[ModuleInfo]:
        return [self.info(i) for i in self.ids()]

    # records ------------------------------------------------------------------------------------------

    def _record(self, action: str, module_id: str, actor: str, **detail: str) -> None:
        self._audit.append(actor=actor, action=action, module=module_id, detail=detail)
        self._bus.publish("core", action, {"module": module_id, **detail})

    def _persist(self, e: _Entry) -> None:
        if self._store is None:
            return
        now = _utc()
        self._store.core_execute(
            "INSERT INTO modules (id, version, mode, state, installed_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET version = excluded.version, mode = excluded.mode, "
            "state = excluded.state, updated_at = excluded.updated_at",
            (e.manifest.id, e.manifest.version, e.mode, e.status.value, now, now),
        )

    def _stored_mode(self, module_id: str) -> str | None:
        if self._store is None:
            return None
        rows = self._store.core_query("SELECT mode FROM modules WHERE id = ?", (module_id,))
        return str(rows[0][0]) if rows else None

    # discovery ----------------------------------------------------------------------------------------

    def _reject(self, directory: Path, reason: str) -> None:
        reason = reason[:_MAX_REASON]
        self._audit.append(
            actor=CORE_ACTOR,
            action="module.rejected",
            module="",
            detail={"path": str(directory), "reason": reason},
        )
        self._bus.publish("core", "module.rejected", {"path": str(directory), "reason": reason})

    def _is_trusted(self, directory: Path) -> bool:
        resolved = directory.resolve()
        return any(resolved.is_relative_to(root) for root in self._trusted)

    def discover(self, roots: Sequence[Path]) -> list[str]:
        """Load and verify every ``<root>/<dir>/module.toml``. Returns the ids accepted by this call."""
        accepted: list[str] = []
        for root in roots:
            if not root.is_dir():
                continue
            for directory in sorted(p for p in root.iterdir() if (p / MANIFEST_NAME).is_file()):
                module_id = self._discover_one(directory)
                if module_id is not None:
                    accepted.append(module_id)
        return accepted

    def _discover_one(self, directory: Path) -> str | None:
        try:
            manifest = load_manifest(directory)
        except ManifestError as exc:
            self._reject(directory, "; ".join(exc.errors))
            return None
        if manifest.isolation == "in-process" and not self._is_trusted(directory):
            self._reject(
                directory, "module is outside the trusted roots; it must declare isolation = 'subprocess'"
            )
            return None
        with self._lock:
            existing = self._entries.get(manifest.id)
            if existing is not None and existing.manifest.directory.resolve() != directory.resolve():
                self._reject(directory, f"duplicate module id {manifest.id!r}")
                return None
            if existing is not None and existing.status is ModuleStatus.ACTIVE:
                return manifest.id  # a running module keeps its manifest until it is restarted
            try:
                self._policy.register(manifest)
            except ManifestError as exc:
                self._reject(directory, "; ".join(exc.errors))
                return None
            mode = self._stored_mode(manifest.id) or manifest.activation
            entry = _Entry(manifest=manifest, mode=mode)
            self._entries[manifest.id] = entry
            self._persist(entry)
        self._record("module.verified", manifest.id, CORE_ACTOR)
        return manifest.id

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
        cls = getattr(module, manifest.entry_class)
        missing = [m for m in REQUIRED_METHODS if not callable(getattr(cls, m, None))]
        if missing:
            raise TypeError(f"entry class lacks {missing}")
        return cls()

    # transitions --------------------------------------------------------------------------------------

    def activate(self, module_id: str, *, actor: str) -> None:
        with self._lock:
            e = self._entry(module_id)
            if e.mode == "disabled":
                raise SwitchyardError(f"module {module_id!r} is disabled")
            if e.status is ModuleStatus.ACTIVE:
                e.last_used = self._clock()
                return
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
            raise SwitchyardError(f"invalid mode {mode!r}; expected one of {sorted(MODES)}")
        with self._lock:
            e = self._entry(module_id)
            if mode == "disabled" and e.status is ModuleStatus.ACTIVE:
                self.deactivate(module_id, actor=actor, reason="disabled")
            e.mode = mode
            self._persist(e)
        self._record("module.mode_changed", module_id, actor, mode=mode)

    def start_auto(self, *, actor: str) -> None:
        """Activate every ``auto`` module that is not running or failed."""
        for module_id in self.ids():
            e = self._entries[module_id]
            if e.mode == "auto" and e.status in (ModuleStatus.VERIFIED, ModuleStatus.STOPPED):
                self.activate(module_id, actor=actor)

    def touch(self, module_id: str) -> None:
        """Mark a module as used now (resets its idle timer)."""
        with self._lock:
            self._entry(module_id).last_used = self._clock()

    def tick(self) -> None:
        """Stop ``auto`` modules idle for ``idle_stop_seconds``."""
        now = self._clock()
        for module_id in self.ids():
            e = self._entries[module_id]
            idle = e.manifest.idle_stop_seconds
            if (
                e.status is ModuleStatus.ACTIVE
                and e.mode == "auto"
                and idle > 0
                and now - e.last_used >= idle
            ):
                self.deactivate(module_id, actor=CORE_ACTOR, reason="idle")

    def remove(self, module_id: str, *, actor: str, keep_data: bool = False) -> None:
        """Stop and forget a module. Drops its grants and stored data unless ``keep_data``."""
        with self._lock:
            self._entry(module_id)
            self.deactivate(module_id, actor=actor, reason="remove")
            self._unload(module_id)
            self._policy.unregister(module_id, actor=actor, keep_grants=keep_data)
            if self._store is not None:
                if not keep_data:
                    self._store.module(module_id).drop_all()
                self._store.core_execute("DELETE FROM modules WHERE id = ?", (module_id,))
            del self._entries[module_id]
        self._record("module.removed", module_id, actor, keep_data=str(keep_data).lower())
