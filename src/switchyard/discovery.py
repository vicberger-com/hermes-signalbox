"""Module discovery and the module records (split out of ``lifecycle`` in 1.1, H1 A-30).

``ModuleDirectory`` finds and verifies modules, keeps their entries, and writes their audit records and
``modules`` rows. ``lifecycle.ModuleManager`` builds on it with import, activation, health and removal.
"""

from __future__ import annotations

import enum
import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import switchyard
from switchyard.capabilities import CORE_ACTOR, AuditSink, PolicyEngine
from switchyard.context import ModuleContext
from switchyard.errors import ManifestError
from switchyard.events import EventBus
from switchyard.manifest import MANIFEST_NAME, Manifest, core_compatibility, load_manifest
from switchyard.state import StateStore

_MAX_REASON = 900
_VERIFIED_KEY = "module.verified."  # meta key prefix: last audited verification (1.1 #125)

# H3-16/H3-18/H3-21: T2 child process should not write module.verified audit.
# The parent already wrote it during discovery.
def _is_t2_child() -> bool:
    return os.environ.get("SWITCHYARD_T2") == "1"


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
    stop_reason: str = ""  # why it last stopped: "idle", "revoked <cap>", "update", ... (R1 follow-up)

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
    stop_reason: str = ""


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ModuleDirectory:
    """The verified modules and their records. The manager's ``__init__`` sets these attributes."""

    _policy: PolicyEngine
    _audit: AuditSink
    _bus: EventBus
    _store: StateStore | None
    _trusted: list[Path]
    _entries: dict[str, _Entry]
    _lock: threading.RLock

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
        verdict, why = core_compatibility(manifest.requires_core, switchyard.__version__)  # H1 A-20
        if verdict == "incompatible":
            self._reject(directory, why)
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
        # 1.1 #125: every process that opens the data directory runs discovery. The audit gets a record when
        # the verified manifest is new or changed; an unchanged one is only announced on the in-process bus.
        fingerprint = self._verification_fingerprint(manifest.id, directory, manifest.digest)
        if fingerprint is not None:
            # H3-16/H3-18/H3-21: T2 child process should not write module.verified audit.
            # The parent already wrote it during discovery.
            if not _is_t2_child():
                self._record("module.verified", manifest.id, CORE_ACTOR)
            if verdict == "outdated":  # the 1.0 transition (Q-SY-1.1-3): loads, and says so once per change
                self._record(
                    "module.requires_core_outdated",
                    manifest.id,
                    CORE_ACTOR,
                    requires_core=manifest.requires_core[:200],  # schema caps it at 128; clip anyway (S1-3)
                )
            self._store_fingerprint(manifest.id, fingerprint)  # only after the record is written
        else:
            self._bus.publish("core", "module.verified", {"module": manifest.id})
        return manifest.id

    def _verification_fingerprint(self, module_id: str, directory: Path, digest: str) -> str | None:
        """(directory, manifest digest) when it differs from the last audited verification, else None.
        Without a store every verification is new. ``digest`` is of the bytes that were loaded and registered,
        not a second read of the file (1.1 acceptance S1-6)."""
        fingerprint = f"{directory.resolve()}|{digest}"
        if self._store is None:
            return fingerprint
        rows = self._store.core_query("SELECT value FROM meta WHERE key = ?", (_VERIFIED_KEY + module_id,))
        return None if rows and rows[0][0] == fingerprint else fingerprint

    def _store_fingerprint(self, module_id: str, fingerprint: str) -> None:
        if self._store is not None:
            self._store.core_execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (_VERIFIED_KEY + module_id, fingerprint),
            )
