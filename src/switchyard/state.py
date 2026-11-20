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

import contextlib
import json
import re
import sqlite3
import threading
import time
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from switchyard.errors import StateError

_MODULE_ID = re.compile(r"[a-z][a-z0-9_]{0,30}[a-z0-9]\Z")
_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
_MIGRATION_FILE = re.compile(r"(\d{4})_[a-z0-9_]+\.sql\Z")
COLUMN_TYPES = frozenset({"TEXT", "INTEGER", "REAL", "BLOB"})
MAX_KV_KEY_CHARS = 128
_TABLE_ACTIONS = frozenset(
    {sqlite3.SQLITE_READ, sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
)
_DENIED_FUNCTIONS = frozenset({"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"})

Migration = tuple[int, str]
BUSY_TIMEOUT_MS = 5000  # store-wide wait for SQLite locks held by other processes


class Deadline:
    """A thread's total wait budget for the store (ADR-0013): see ``StateStore.deadline``."""

    def __init__(self, end: float) -> None:
        self.end = end

    def remaining(self) -> float:
        return max(0.0, self.end - time.monotonic())

    def expired(self) -> bool:
        return time.monotonic() >= self.end


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


# Module statements: abort after MAX_WORK_STEPS * PROGRESS_EVERY VM instructions; cap returned rows.
PROGRESS_EVERY = 1000
MAX_WORK_STEPS = 10_000
MAX_ROWS = 10_000


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
        self._local = threading.local()
        self._busy_ms = BUSY_TIMEOUT_MS
        self._conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        for pragma in (
            "journal_mode = WAL", "synchronous = NORMAL", "foreign_keys = ON",
            f"busy_timeout = {BUSY_TIMEOUT_MS}", "trusted_schema = OFF",
        ):  # fmt: skip
            self._conn.execute(f"PRAGMA {pragma}")

    # wait budgets -------------------------------------------------------------------------------------

    @contextlib.contextmanager
    def deadline(self, seconds: float) -> Iterator[Deadline]:
        """Bound the total time this thread waits for the store inside the block: for the store lock (other
        threads) and for SQLite locks (other processes). A statement that would wait longer raises
        ``StateError`` (\"busy\"). Nested blocks never extend an outer limit. Used on Hermes hot paths, where
        the bridge deadline is shorter than the store-wide busy wait (ADR-0013)."""
        outer: Deadline | None = getattr(self._local, "deadline", None)
        end = time.monotonic() + max(0.0, float(seconds))
        current = Deadline(end if outer is None else min(end, outer.end))
        self._local.deadline = current
        try:
            yield current
        finally:
            self._local.deadline = outer

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        limit: Deadline | None = getattr(self._local, "deadline", None)
        if limit is None:
            with self._lock:
                yield
            return
        if not self._lock.acquire(timeout=limit.remaining()):
            raise StateError("state store busy: the wait budget is used up")
        try:
            wait_ms = min(int(limit.remaining() * 1000), BUSY_TIMEOUT_MS)
            if wait_ms <= 0:
                raise StateError("state store busy: the wait budget is used up")
            previous = self._busy_ms
            self._set_busy(wait_ms)
            try:
                yield
            finally:
                self._set_busy(previous)
        finally:
            self._lock.release()

    def _set_busy(self, wait_ms: int) -> None:
        if wait_ms != self._busy_ms:
            self._conn.execute(f"PRAGMA busy_timeout = {int(wait_ms)}")
            self._busy_ms = wait_ms

    # core access --------------------------------------------------------------------------------------

    @property
    def user_version(self) -> int:
        return int(self.core_query("PRAGMA user_version")[0][0])

    def core_query(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        """Run one statement with full access. Core code only; never pass module-supplied SQL."""
        with self._locked():
            return self._conn.execute(sql, params).fetchall()

    def core_execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self._locked():
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
        budget = [0]

        def progress() -> int:
            budget[0] += 1
            return 1 if budget[0] > MAX_WORK_STEPS else 0  # non-zero aborts the statement

        with self._locked():
            self._conn.set_authorizer(authorizer)
            self._conn.set_progress_handler(progress, PROGRESS_EVERY)
            try:
                rows = self._conn.execute(sql, params).fetchmany(MAX_ROWS + 1)
            except sqlite3.OperationalError as exc:
                if budget[0] > MAX_WORK_STEPS:
                    raise StateError("module query exceeded its work budget") from None
                raise StateError(f"module query failed: {exc}") from None
            finally:
                self._conn.set_progress_handler(None, 0)
                self._conn.set_authorizer(None)
        if len(rows) > MAX_ROWS:
            raise StateError(f"module query returned more than {MAX_ROWS} rows; page with LIMIT/OFFSET")
        return rows


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


def _owned(rest: str) -> bool:
    return bool(_NAME.match(rest)) and "__" not in rest


class ModuleState:
    """A module's view of the store: its own tables and key/value rows only."""

    def __init__(self, store: StateStore, module_id: str) -> None:
        self._store = store
        self._id = module_id
        self._prefix = f"m_{module_id}__"
        self._denied: str | None = None

    def deadline(self, seconds: float) -> contextlib.AbstractContextManager[Deadline]:
        """Bound this thread's total store wait inside the block (see ``StateStore.deadline``)."""
        return self._store.deadline(seconds)

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
            # count(*) reads with db=None; ATTACH is denied, so that can only be main.
            main = db == "main" or (db is None and action == sqlite3.SQLITE_READ and arg2 == "")
            # The rest must be a valid table name: module "ab" must not reach "ab_"'s "m_ab___x" (R1 review).
            if (
                main
                and arg1 is not None
                and arg1.startswith(self._prefix)
                and _owned(arg1[len(self._prefix) :])
            ):
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
            if not _owned(name[len(self._prefix) :]):
                continue  # another module's table whose id extends ours
            self._store.core_execute(f'DROP TABLE "{name}"')
        self._store.core_execute("DELETE FROM kv WHERE module_id = ?", (self._id,))
