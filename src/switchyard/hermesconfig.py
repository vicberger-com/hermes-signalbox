"""Hermes configuration writes: the ``hermes.config.write`` capability (``ctx.hermes_config``), ADR-0005.

Hermes-agnostic: the adapter supplies a ``HermesConfigPort`` that reads and writes Hermes's own config through
its public API. The broker allows an allow-list of keys only, validates every value, writes a backup before
each change, audits it, reads the value back, and restores the previous value if the write fails or Hermes
stores something other than what was asked. ``revert`` restores any backup (itself backed up, so it can be
undone too). Backups hold skill and plugin names only.
"""

from __future__ import annotations

import json
import os
import re
import secrets as _random
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from switchyard.capabilities import AuditSink
from switchyard.errors import SwitchyardError

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}\Z")
_BACKUP_ID = re.compile(r"[0-9]{20}-[a-f0-9]{8}\Z")
MAX_NAMES = 2000
KEEP_BACKUPS = 200


def _name_list(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_NAMES:
        raise SwitchyardError(f"value must be a list of at most {MAX_NAMES} names")
    names = []
    for item in value:
        if not isinstance(item, str) or not _NAME.match(item):
            raise SwitchyardError(f"invalid name {str(item)[:80]!r}")
        names.append(item)
    return sorted(set(names))


# key -> validator. ``skills.disabled`` takes effect on the next turn; ``plugins.disabled`` on restart.
ALLOWED_KEYS: dict[str, Callable[[Any], Any]] = {
    "skills.disabled": _name_list,
    "plugins.disabled": _name_list,
}


class HermesConfigPort(Protocol):
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
    def skills(self) -> list[dict[str, str]]: ...


class ConfigWriter:
    """Satisfies the ``hermes.config.write`` broker. Thread-safe."""

    def __init__(self, port: HermesConfigPort, audit: AuditSink, backup_dir: Path) -> None:
        self._port = port
        self._audit = audit
        self._dir = backup_dir
        self._lock = threading.Lock()
        self._seq = 0

    @staticmethod
    def _check_key(key: str) -> Callable[[Any], Any]:
        validator = ALLOWED_KEYS.get(key)
        if validator is None:
            raise SwitchyardError(
                f"Hermes config key {key!r} is not writable; allowed: {sorted(ALLOWED_KEYS)}"
            )
        return validator

    def get(self, key: str) -> Any:
        self._check_key(key)
        value = self._port.get(key)
        if value is None:
            return []
        return sorted({str(v) for v in value}) if isinstance(value, list | tuple | set) else [str(value)]

    def skills(self) -> list[dict[str, str]]:
        out = []
        for row in self._port.skills()[:MAX_NAMES]:
            name = row.get("name")
            if isinstance(name, str) and _NAME.match(name):
                out.append(
                    {
                        "name": name,
                        "category": str(row.get("category") or "")[:128],
                        "description": str(row.get("description") or "")[:4000],
                    }
                )
        return out

    def _write_backup(self, record: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{record['id']}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True)
        for old in sorted(self._dir.glob("*.json"))[:-KEEP_BACKUPS]:
            old.unlink(missing_ok=True)

    def set(self, module_id: str, key: str, value: Any, *, actor: str, note: str = "") -> dict[str, Any]:
        """Write ``key``; returns ``{"backup", "key", "stored", "refused"}``. ``refused`` lists names Hermes
        declined to store (for example essential skills); anything else unexpected rolls back."""
        new = self._check_key(key)(value)
        with self._lock:
            old = self.get(key)
            now = datetime.now(UTC)
            self._seq = (self._seq + 1) % 1_000_000  # orders backups made within the same second
            backup = f"{now.strftime('%Y%m%d%H%M%S')}{self._seq:06d}-{_random.token_hex(4)}"
            record = {
                "id": backup,
                "key": key,
                "old": old,
                "new": new,
                "module": module_id,
                "actor": actor,
                "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "note": note[:200],
            }
            self._write_backup(record)
            detail = {"key": key, "backup": backup, "names": str(len(new)), "by": actor[:64]}
            self._audit.append(actor=module_id, action="hermes.config.write", module=module_id, detail=detail)
            try:
                self._port.set(key, new)
                stored = self.get(key)
                unexpected = set(stored) - set(new)
                if unexpected:
                    raise SwitchyardError(f"Hermes stored {len(unexpected)} unexpected name(s) for {key}")
            except Exception as exc:
                try:
                    self._port.set(key, old)
                    restored = "yes"
                except Exception:  # the rollback itself failed: say so; the backup file has the old value
                    restored = "no"
                self._audit.append(
                    actor=module_id,
                    action="hermes.config.rollback",
                    module=module_id,
                    detail={"key": key, "backup": backup, "error": type(exc).__name__, "restored": restored},
                )
                raise SwitchyardError(
                    f"writing Hermes config {key} failed ({type(exc).__name__}); "
                    f"previous value {'restored' if restored == 'yes' else 'NOT restored'}, "
                    f"backup {backup}"
                ) from None
        return {"backup": backup, "key": key, "stored": stored, "refused": sorted(set(new) - set(stored))}

    def backups(self, n: int = 20) -> list[dict[str, Any]]:
        out = []
        for path in sorted(self._dir.glob("*.json"), reverse=True)[: max(1, min(n, KEEP_BACKUPS))]:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out.append(
                {k: record.get(k) for k in ("id", "key", "module", "actor", "at", "note")}
                | {"old": len(record.get("old") or []), "new": len(record.get("new") or [])}
            )
        return out

    def revert(self, module_id: str, backup_id: str, *, actor: str) -> dict[str, Any]:
        """Restore the value a backup recorded before its change. The revert is itself backed up."""
        if not isinstance(backup_id, str) or not _BACKUP_ID.match(backup_id):
            raise SwitchyardError(f"invalid backup id {str(backup_id)[:40]!r}")
        path = self._dir / f"{backup_id}.json"
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise SwitchyardError(f"no backup {backup_id!r}") from None
        return self.set(module_id, record["key"], record["old"], actor=actor, note=f"revert of {backup_id}")

    def for_module(self, module_id: str) -> ModuleConfig:
        return ModuleConfig(self, module_id)


class ModuleConfig:
    """What ``ctx.hermes_config`` returns: the writer bound to one module."""

    __slots__ = ("_module_id", "_writer")

    def __init__(self, writer: ConfigWriter, module_id: str) -> None:
        self._writer = writer
        self._module_id = module_id

    def get(self, key: str) -> Any:
        return self._writer.get(key)

    def skills(self) -> list[dict[str, str]]:
        return self._writer.skills()

    def set(self, key: str, value: Any, *, actor: str, note: str = "") -> dict[str, Any]:
        return self._writer.set(self._module_id, key, value, actor=actor, note=note)

    def backups(self, n: int = 20) -> list[dict[str, Any]]:
        return self._writer.backups(n)

    def revert(self, backup_id: str, *, actor: str) -> dict[str, Any]:
        return self._writer.revert(self._module_id, backup_id, actor=actor)
