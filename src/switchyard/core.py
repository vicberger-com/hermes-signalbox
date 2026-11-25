"""``Core``: builds and owns every core component for one data directory (spec sections 2 and 3).

Adapters (CLI, control API, Hermes plugin) hold a ``Core`` and call ``Core.run(noun, verb, params,
actor=...)``; they never reach into components directly. Startup verifies the audit chain against the head
anchor kept in ``state.db`` (updated on every append); a failed verification is recorded
(``audit.verify_failed``) and exposed as ``audit_status`` while the core keeps running (fail closed applies to
modules, not to the control plane that must report the problem).
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any

import switchyard
from switchyard.audit import AuditLog, AuditRecord, VerifyResult
from switchyard.bridge import HermesBridge
from switchyard.capabilities import CORE_ACTOR, PolicyEngine
from switchyard.config import CoreConfig, load_config
from switchyard.context import MemoryActionRegistry, MemoryPanelRegistry
from switchyard.errors import CapabilityDenied, SwitchyardError
from switchyard.events import EventBus
from switchyard.fsread import FsBroker
from switchyard.hermesconfig import ConfigWriter, HermesConfigPort
from switchyard.hostinfo import capacity_metrics
from switchyard.hostlock import HostLock
from switchyard.lifecycle import ModuleManager
from switchyard.logs import JsonlLogSink
from switchyard.net import NetBroker
from switchyard.notify import NotifyBroker
from switchyard.ops import lookup
from switchyard.paths import data_dir_source, ensure_data_dir, resolve_data_dir
from switchyard.process import ProcessBroker
from switchyard.schedule import ScheduleBroker
from switchyard.scheduler import Scheduler
from switchyard.secrets import Redactor, SecretsBroker
from switchyard.state import SqliteGrantStore, StateStore
from switchyard.updates import Fetcher, GitFetcher, UpdateController

BUILTIN_MODULES = Path(switchyard.__file__).resolve().parent / "modules"
_HEAD_KEY = "audit.head"
CROSS_CALL_AUDIT_WINDOW_S = 60.0  # 1.1 #124: one audit record per cross-module read call path per window
# H3-17: resources.resolve audit sampling - longer window to reduce audit overhead on Windows
CROSS_CALL_RESOURCES_RESOLVE_AUDIT_WINDOW_S = 300.0  # 5 minutes for resources.resolve specifically
_BROKEN_KEY = "audit.broken"
_HOST_PID_KEY = "core.host_pid"  # ADR-0014: who hosts, for processes that do not


class AnchoredAudit:
    """``AuditSink`` that writes to the log and stores the new head in ``state.db`` after every append."""

    def __init__(self, log: AuditLog, store: StateStore) -> None:
        self.log = log
        self._store = store

    def append(self, *, actor: str, action: str, module: str, detail: Mapping[str, str]) -> AuditRecord:
        record = self.log.append(actor=actor, action=action, module=module, detail=detail)
        self._store.core_execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value "
            # another process may have anchored a later record already: never move the anchor back
            "WHERE CAST(substr(value, 1, instr(value, ':') - 1) AS INTEGER) < ?",
            (_HEAD_KEY, f"{record.seq}:{record.hash}", record.seq),
        )
        return record

    def stored_head(self) -> tuple[int, str] | None:
        rows = self._store.core_query("SELECT value FROM meta WHERE key = ?", (_HEAD_KEY,))
        if not rows:
            return None
        seq, _, digest = str(rows[0][0]).partition(":")
        return int(seq), digest


VERIFY_CACHE_SECONDS = 60.0


class CoreView:
    """The ``core.read`` capability (ADR-0006): a read-only view of module states and the audit chain."""

    def __init__(self, core: Core) -> None:
        self._core = core
        self._lock = threading.Lock()
        self._cached: tuple[float, dict[str, Any]] | None = None

    def modules(self) -> list[dict[str, Any]]:
        return [
            {
                "id": i.id,
                "status": i.status.value,
                "mode": i.mode,
                "error": i.error,
                "stop_reason": i.stop_reason,
            }
            for i in self._core.manager.modules()
        ]

    def update_checks(self, max_age_s: float = 3600.0) -> list[dict[str, Any]]:
        """Channel heads versus installed commits for git-installed modules (ADR-0011). Runs ``git ls-remote``
        against each module's pinned https URL; nothing is downloaded or applied."""
        return self._core.updates.cached_checks(max_age_s)

    def verify_audit(self) -> dict[str, Any]:
        """Cached for ``VERIFY_CACHE_SECONDS``: a full scan holds the audit lock, so a module calling this in
        a loop must not stall every audited action (M6 review)."""
        now = time.monotonic()
        with self._lock:
            if self._cached is not None and now - self._cached[0] < VERIFY_CACHE_SECONDS:
                return dict(self._cached[1])
        result = self._core.verify_audit()
        out = {
            "ok": result.ok,
            "records": result.records,
            "first_bad_seq": result.first_bad_seq,
            "reason": result.reason,
        }
        with self._lock:
            self._cached = (now, out)
        return dict(out)


class Core:
    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        hermes_dir: Path | None = None,
        trusted_roots: Sequence[Path] | None = None,
        module_roots: Sequence[Path] | None = None,
        secret_backends: Sequence[Any] = (),
        hosting: bool | None = None,
        fetcher: Fetcher | None = None,
        hermes_config: HermesConfigPort | None = None,
    ) -> None:
        initial = resolve_data_dir(configured=data_dir, hermes_dir=hermes_dir)
        self.config: CoreConfig = load_config(initial / "config.toml")
        self.data_dir = ensure_data_dir(self.config.data_dir or initial)
        self.data_dir_source = (
            f"data_dir in {initial / 'config.toml'}"
            if self.config.data_dir
            else data_dir_source(configured=data_dir, hermes_dir=hermes_dir)
        )
        # hosting=True: must host (raise if another process does); None: host if free; False: never host.
        self._host_lock = HostLock(self.data_dir / "host.lock")
        self.hosting = bool(hosting is not False and self._host_lock.acquire())
        self._closed = False
        try:
            self._start(hosting, trusted_roots, module_roots, secret_backends, fetcher, hermes_config)
        except BaseException:
            # H1 A-10: a failed start must not keep the host lock or the database for the process lifetime
            self._abort_start()
            raise

    def _abort_start(self) -> None:
        for name in ("bridge", "schedules"):
            part = self.__dict__.get(name)
            if part is not None:
                with contextlib.suppress(Exception):
                    part.close()
        store = self.__dict__.get("store")
        if store is not None:
            with contextlib.suppress(Exception):
                store.close()
        with contextlib.suppress(Exception):
            self._host_lock.release()

    def _start(
        self,
        hosting: bool | None,
        trusted_roots: Sequence[Path] | None,
        module_roots: Sequence[Path] | None,
        secret_backends: Sequence[Any],
        fetcher: Fetcher | None,
        hermes_config: HermesConfigPort | None,
    ) -> None:
        if hosting is True and not self.hosting:
            raise SwitchyardError(f"another process hosts modules for {self.data_dir}")
        self.redactor = Redactor()
        self.audit_log = AuditLog(self.data_dir / "audit", redact=self.redactor.redact)
        self.store = StateStore(self.data_dir / "state.db", backup_dir=self.data_dir / "backup")
        self.store.migrate()
        self.audit = AnchoredAudit(self.audit_log, self.store)
        self.audit_status = self.verify_audit()
        if not self.audit_status.ok and not self._audit_broken():
            # Keep the failure until the operator acknowledges it ("audit ack"): appending below moves the
            # head anchor, and without this flag the next verify would pass and the gap would be forgotten
            # (R1 review).
            self.store.core_execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (_BROKEN_KEY, f"{self.audit_status.first_bad_seq}:{self.audit_status.reason}"[:500]),
            )
            self.audit.append(
                actor=CORE_ACTOR,
                action="audit.verify_failed",
                module="",
                detail={"reason": self.audit_status.reason, "seq": str(self.audit_status.first_bad_seq)},
            )
        self.policy = PolicyEngine(SqliteGrantStore(self.store), self.audit)
        self.bus = EventBus(self.audit)
        self.scheduler = Scheduler(self.bus, self.audit)
        self.logs = JsonlLogSink(self.data_dir / "logs", redact=self.redactor.redact)
        self.panels = MemoryPanelRegistry()
        self.actions = MemoryActionRegistry()
        self.processes = ProcessBroker(self.policy, self.audit)
        self.files = FsBroker(self.policy, self.audit)
        self.bridge = HermesBridge(self.audit)
        self.secrets = SecretsBroker(list(secret_backends), self.policy, self.audit, self.redactor)
        trusted = list(trusted_roots) if trusted_roots is not None else [BUILTIN_MODULES]
        roots = (
            list(module_roots) if module_roots is not None else [BUILTIN_MODULES, self.data_dir / "modules"]
        )
        brokers: dict[str, object] = {
            "secrets.read": self.secrets,
            "process.spawn": self.processes,
            "fs.read": self.files,
        }
        self.hermes_config = (
            ConfigWriter(hermes_config, self.audit, self.data_dir / "hermes-config-backups")
            if hermes_config
            else None
        )
        if self.hermes_config is not None:
            brokers["hermes.config.write"] = self.hermes_config
        self.schedules = ScheduleBroker(self.scheduler, self.audit)
        brokers["schedule"] = self.schedules
        brokers["core.read"] = CoreView(self)
        brokers["net.outbound"] = NetBroker(self.policy, self.audit)
        brokers["notify"] = NotifyBroker(self.bus.publish, self.audit, self.redactor.redact)
        self.manager = ModuleManager(
            policy=self.policy,
            audit=self.audit,
            bus=self.bus,
            logs=self.logs,
            panels=self.panels,
            trusted_roots=trusted,
            scheduler=self.scheduler,
            store=self.store,
            brokers=brokers,
            actions=self.actions,
            secret_backends=self.secrets,
            config=lambda mid: self.config.modules.get(mid, {}),
            bridge=self.bridge,
            call=self._module_call,
        )
        self.manager.discover(roots)
        if self.hosting:
            self.manager.persist_states()  # H4 R1-F9: discovery no longer writes the state column
        self._lock = threading.RLock()
        self._cross_lock = threading.Lock()
        self._cross_calls: dict[tuple[str, str, str], tuple[float | None, int]] = {}
        if self.hosting:
            self._record_host_pid()
        self.updates = UpdateController(
            self.manager, self.audit, self.data_dir, fetcher or GitFetcher(configured=self.config.git),
            swap_guard=self._open_and_locked,
        )  # fmt: skip

    def _module_call(self, caller: str, module_id: str, action: str, args: Mapping[str, Any]) -> Any:
        from switchyard.ops import run_action

        # 1.1 #124: a read-only cross-module call can run on every model request (router -> resources).
        # It is recorded once per (caller, target, action) per window, with the number of calls since the
        # last record, instead of one fsynced record per call. Operator and model actions are still
        # recorded every time.
        # H3-17: resources.resolve uses a longer audit window (5 min) to reduce audit overhead on Windows.
        key = (caller, module_id, action)
        now = time.monotonic()
        with self._cross_lock:
            last, count = self._cross_calls.get(key, (None, 0))
            count += 1
            window = (
                CROSS_CALL_RESOURCES_RESOLVE_AUDIT_WINDOW_S
                if module_id == "resources" and action == "resolve"
                else CROSS_CALL_AUDIT_WINDOW_S
            )
            record = last is None or now - last >= window
            self._cross_calls[key] = (now, 0) if record else (last, count)
        return run_action(self, module_id, action, args, actor=f"module:{caller}", read_only_only=True,
                          audit=record, audit_detail={"calls": str(count)})  # fmt: skip

    def _record_host_pid(self) -> None:
        self.store.core_execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (_HOST_PID_KEY, str(os.getpid()))
        )

    def acquire_hosting(self) -> bool:
        """Become the hosting process of this data directory if nobody is (ADR-0014). True when this core
        hosts afterwards. A core that starts hosting here records ``core.hosting_acquired``; starting the
        ``auto`` modules is the caller's next step."""
        with self._lock:
            if self._closed:
                return False
            if self.hosting:
                return True
            if not self._host_lock.acquire():
                return False
            try:
                self._record_host_pid()
                self.audit.append(actor=CORE_ACTOR, action="core.hosting_acquired", module="",
                                  detail={"pid": str(os.getpid())})  # fmt: skip
            except BaseException:
                self._host_lock.release()
                raise
            self.hosting = True
            self.manager.persist_states()  # H4 R1-F9: this process's statuses are the true ones now
            return True

    def host_pid(self) -> int | None:
        """The process that hosts this data directory, or ``None`` when nobody does. The recorded pid is
        reported only while the host lock is held: a host that died left the record, not the lock."""
        if self.hosting:
            return os.getpid()
        probe = HostLock(self.data_dir / "host.lock")
        try:
            if probe.acquire():
                probe.release()
                return None
        except OSError:
            return None
        rows = self.store.core_query("SELECT value FROM meta WHERE key = ?", (_HOST_PID_KEY,))
        value = str(rows[0][0]) if rows else ""
        return int(value) if value.isdigit() else None

    def _audit_broken(self) -> str | None:
        rows = self.store.core_query("SELECT value FROM meta WHERE key = ?", (_BROKEN_KEY,))
        return str(rows[0][0]) if rows else None

    def verify_audit(self) -> VerifyResult:
        result = self.audit_log.verify(expected_head=self.audit.stored_head())
        broken = self._audit_broken() if hasattr(self, "store") else None
        if broken:
            seq, _, reason = broken.partition(":")
            first = int(seq) if seq.isdigit() else 0
            message = f"earlier failure not acknowledged: {reason} (run 'switchyard audit ack')"
            return VerifyResult(False, result.records, first if result.ok else result.first_bad_seq, message)
        return result

    def ack_audit(self, *, actor: str) -> dict[str, Any]:
        broken = self._audit_broken()
        if broken is None:
            return {"acknowledged": False}
        # H1 A-11: record the acknowledgement first, then re-anchor at it (the operator has accepted the log
        # as it is now as the new baseline), and only then clear the flag. A failure at any step leaves the
        # warning in place.
        record = self.audit_log.append(
            actor=actor, action="audit.acknowledged", module="", detail={"failure": broken[:300]}
        )
        self.store.core_execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (_HEAD_KEY, f"{record.seq}:{record.hash}"),
        )
        self.store.core_execute("DELETE FROM meta WHERE key = ?", (_BROKEN_KEY,))
        return {"acknowledged": True, "failure": broken}

    def run(self, noun: str, verb: str, params: Mapping[str, Any], *, actor: str) -> Any:
        """Run one operation from the shared table. Raises ``UsageError`` or the operation's own error."""
        from switchyard.ops import MODEL_ACTOR, MODEL_OPS

        operation = lookup(noun, verb)
        if actor == MODEL_ACTOR and (noun, verb) not in MODEL_OPS:
            self.audit.append(actor=actor, action="policy.denied", module="", detail={"op": f"{noun} {verb}"})
            raise CapabilityDenied(f"'{noun} {verb}' is for the operator only")
        clean = operation.validate(params)
        if not operation.locked:  # H1 B-2: git work runs without the core lock (see UpdateController)
            with self._lock:
                if self._closed:
                    raise SwitchyardError("core is closed")
            return self.redactor.redact_obj(operation.fn(self, clean, actor))
        with self._lock:
            if self._closed:
                raise SwitchyardError("core is closed")
            # H1 A-7: a result (health detail, panel, action, ...) never carries a secret value out
            return self.redactor.redact_obj(operation.fn(self, clean, actor))

    @contextlib.contextmanager
    def _open_and_locked(self) -> Iterator[None]:
        """The core lock, refusing once the core is closed (the swap step of an update, H1 B-2)."""
        with self._lock:
            if self._closed:
                raise SwitchyardError("core is closed")
            yield

    def tick(self) -> None:
        """Periodic work: time triggers, idle stop, capacity metrics for capacity triggers."""
        with self._lock:
            if self._closed or not self.hosting:
                return
        # Scheduled module jobs run without the core lock held, so a slow job cannot block the control plane
        # (M6 review); each module job is itself time-bounded (ModuleSchedule).
        self.scheduler.tick()
        with self._lock:
            if self._closed:
                return
            self.manager.tick()
            for metric, value in capacity_metrics(self.data_dir).items():
                self.scheduler.observe(metric, value)

    def close(self, *, reason: str = "shutdown") -> None:
        """Stop every module (recorded with ``reason``), then release everything this core holds. Each step
        runs even when an earlier one raised, so a failed stop never keeps the host lock (H4 R1-F14)."""
        with self._lock:
            if self._closed:
                return
            with contextlib.ExitStack() as steps:  # run in reverse order of registration
                steps.callback(self._release_hosting)
                steps.callback(self.store.close)
                steps.callback(self._forget_host_pid)
                steps.callback(self.schedules.close)
                steps.callback(self.bridge.close)
                steps.callback(setattr, self, "_closed", True)
                for module_id in self.manager.ids():
                    self.manager.deactivate(module_id, actor=CORE_ACTOR, reason=reason)

    def _forget_host_pid(self) -> None:
        if self.hosting:
            with contextlib.suppress(Exception):  # the lock, not this record, says who hosts
                self.store.core_execute("DELETE FROM meta WHERE key = ?", (_HOST_PID_KEY,))

    def _release_hosting(self) -> None:
        self._host_lock.release()
        self.hosting = False

    def __enter__(self) -> Core:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()
