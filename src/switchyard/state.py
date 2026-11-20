"""SQLite state store (spec section 3, State store; ADR-0001).

One file, WAL mode. Core tables come from numbered, forward-only migrations in ``switchyard/migrations``; each
runs in one transaction together with its ``user_version`` bump, after a backup copy of an existing database.

Modules get a ``ModuleState`` confined to tables named ``m_<module_id>__<name>`` plus their own rows in the
core ``kv`` table. Confinement uses SQLite's authorizer callback rather than parsing SQL: while a module
statement is prepared, the engine reports every table and operation it touches; anything outside the prefix
(core tables, other modules, ``sqlite_master``), plus PRAGMA, ATTACH, DDL and transaction control, is denied.
Module ids and table names may not contain ``__``, so no id can forge another module's prefix.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from switchyard.errors import StateError

_MODULE_ID = re.compile(r"[a-z][a-z0-9_]{1,31}\Z")
_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
_MIGRATION_FILE = re.compile(r"(\d{4})_[a-z0-9_]+\.sql\Z")
COLUMN_TYPES = frozenset({"TEXT", "INTEGER", "REAL", "BLOB"})
MAX_KV_KEY_CHARS = 128
_TABLE_ACTIONS = frozenset(
    {sqlite3.SQLITE_READ, sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
)
_DENIED_FUNCTIONS = frozenset({"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"})

Migration = tuple[int, str]


def load_migrations() -> list[Migration]:
    """Packaged migrations as ``(number, sql)``, sorted."""
    found: list[Migration] = []
    for entry in resources.files("switchyard").joinpath("migrations").iterdir():
        m = _MIGRATION_FILE.match(entry.name)
        if m:
            found.append((int(m.group(1)), entry.read_text(encoding="utf-8")))
    return sorted(found)


def _check_module_id(module_id: str) -> None:
    if not _MODULE_ID.match(module_id) or "__" in module_id:
        raise StateError(f"invalid module id {module_id!r}")


def _check_name(kind: str, name: str) -> None:
    if not isinstance(name, str) or not _NAME.match(name) or "__" in name:
        raise StateError(f"invalid {kind} name {name!r}")


class StateStore:
    """Owner of the single SQLite connection. All access is serialised by one lock."""

    def __init__(
        self, path: Path, *, backup_dir: Path, migrations: Sequence[Migration] | None = None
    ) -> None:
        self._migrations = list(load_migrations() if migrations is None else migrations)
        if [n for n, _ in self._migrations] != list(range(1, len(self._migrations) + 1)):
            raise StateError("migrations must be numbered contiguously from 1")
        self._path = path
        self._backup_dir = backup_dir
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        for pragma in (
            "journal_mode = WAL", "synchronous = NORMAL", "foreign_keys = ON",
            "busy_timeout = 5000", "trusted_schema = OFF",
        ):  # fmt: skip
            self._conn.execute(f"PRAGMA {pragma}")

    # core access --------------------------------------------------------------------------------------

    @property
    def user_version(self) -> int:
        return int(self.core_query("PRAGMA user_version")[0][0])

    def core_query(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        """Run one statement with full access. Core code only; never pass module-supplied SQL."""
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def core_execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # migrations ---------------------------------------------------------------------------------------

    def migrate(self) -> None:
        with self._lock:
            current, latest = self.user_version, len(self._migrations)
            if current > latest:
                raise StateError(f"database schema {current} is newer than this Switchyard ({latest})")
            if current == latest:
                return
            if current > 0:
                self._backup(current)
            for number, sql in self._migrations[current:]:
                script = f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;"
                try:
                    self._conn.executescript(script)
                except sqlite3.Error as exc:
                    if self._conn.in_transaction:
                        self._conn.execute("ROLLBACK")
                    raise StateError(f"migration {number} failed: {exc}") from exc

    def _backup(self, version: int) -> None:
        self._backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        dest = sqlite3.connect(str(self._backup_dir / f"state-v{version}-{stamp}.db"))
        try:
            self._conn.backup(dest)
        finally:
            dest.close()

    # modules ------------------------------------------------------------------------------------------

    def module(self, module_id: str) -> ModuleState:
        _check_module_id(module_id)
        return ModuleState(self, module_id)

    def _run_confined(self, authorizer: Any, sql: str, params: Sequence[Any]) -> list[tuple[Any, ...]]:
        with self._lock:
            self._conn.set_authorizer(authorizer)
            try:
                return self._conn.execute(sql, params).fetchall()
            finally:
                self._conn.set_authorizer(None)


class SqliteGrantStore:
    """``capabilities.GrantStore`` on the core ``grants`` table."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    def load(self, module_id: str) -> frozenset[str]:
        rows = self._store.core_query("SELECT capability FROM grants WHERE module_id = ?", (module_id,))
        return frozenset(r[0] for r in rows)

    def add(self, module_id: str, capability: str) -> None:
        self._store.core_execute(
            "INSERT OR IGNORE INTO grants (module_id, capability) VALUES (?, ?)", (module_id, capability)
        )

    def remove(self, module_id: str, capability: str) -> None:
        self._store.core_execute(
            "DELETE FROM grants WHERE module_id = ? AND capability = ?", (module_id, capability)
        )

    def remove_all(self, module_id: str) -> None:
        self._store.core_execute("DELETE FROM grants WHERE module_id = ?", (module_id,))


class ModuleState:
    """A module's view of the store: its own tables and key/value rows only."""

    def __init__(self, store: StateStore, module_id: str) -> None:
        self._store = store
        self._id = module_id
        self._prefix = f"m_{module_id}__"
        self._denied: str | None = None

    def table(self, name: str) -> str:
        """Full table name for ``name``; use it in SQL passed to ``execute``."""
        _check_name("table", name)
        return self._prefix + name

    def create_table(
        self, name: str, columns: Sequence[tuple[str, str]], *, primary_key: Sequence[str] = ()
    ) -> None:
        full = self.table(name)
        if not columns:
            raise StateError("a table needs at least one column")
        names = []
        for col, kind in columns:
            _check_name("column", col)
            if kind not in COLUMN_TYPES:
                raise StateError(f"column type {kind!r} is not one of {sorted(COLUMN_TYPES)}")
            names.append(col)
        if not set(primary_key) <= set(names):
            raise StateError("primary key must name existing columns")
        # Every identifier matched _NAME (letters, digits, underscore); every type is from COLUMN_TYPES.
        parts = [f'"{c}" {k}' for c, k in columns]
        if primary_key:
            parts.append("PRIMARY KEY (" + ", ".join(f'"{c}"' for c in primary_key) + ")")
        ddl = f'CREATE TABLE IF NOT EXISTS "{full}" ({", ".join(parts)}) STRICT'
        self._store.core_execute(ddl)

    def _authorize(
        self, action: int, arg1: str | None, arg2: str | None, db: str | None, _src: str | None
    ) -> int:
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action in _TABLE_ACTIONS:
            if db == "main" and arg1 is not None and arg1.startswith(self._prefix):
                return sqlite3.SQLITE_OK
            self._denied = f"table {arg1!r}"
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() not in _DENIED_FUNCTIONS:
            return sqlite3.SQLITE_OK
        self._denied = f"operation {action} ({arg1 or arg2 or ''})"
        return sqlite3.SQLITE_DENY

    def execute(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        """Run one statement on this module's tables. Returns all result rows."""
        self._denied = None
        try:
            return self._store._run_confined(self._authorize, sql, params)
        except (sqlite3.Error, sqlite3.Warning) as exc:
            if self._denied is not None:
                raise StateError(f"module {self._id!r}: access denied to {self._denied}") from None
            raise StateError(f"module {self._id!r}: statement not allowed: {exc}") from None

    def kv_get(self, key: str, default: Any = None) -> Any:
        rows = self._store.core_query("SELECT value FROM kv WHERE module_id = ? AND key = ?", (self._id, key))
        return json.loads(rows[0][0]) if rows else default

    def kv_set(self, key: str, value: Any) -> None:
        if not isinstance(key, str) or not 0 < len(key) <= MAX_KV_KEY_CHARS:
            raise StateError(f"kv key must be 1 to {MAX_KV_KEY_CHARS} characters")
        try:
            text = json.dumps(value, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise StateError(f"kv value is not JSON-serialisable: {exc}") from None
        self._store.core_execute(
            "INSERT INTO kv (module_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT (module_id, key) DO UPDATE SET value = excluded.value",
            (self._id, key, text),
        )

    def drop_all(self) -> None:
        """Remove every table and kv row this module owns (uninstall without ``--keep-data``)."""
        rows = self._store.core_query(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND substr(name, 1, ?) = ?",
            (len(self._prefix), self._prefix),
        )
        for (name,) in rows:
            _check_name("table", name[len(self._prefix) :])
            self._store.core_execute(f'DROP TABLE "{name}"')
        self._store.core_execute("DELETE FROM kv WHERE module_id = ?", (self._id,))
