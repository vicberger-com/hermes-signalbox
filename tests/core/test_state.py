"""SQLite state store, migrations, grants persistence and module namespaces (spec section 3, State store)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sy_testing import ManifestFactory, RecordingAudit

from hermes_signalbox.capabilities import PolicyEngine
from hermes_signalbox.errors import StateError
from hermes_signalbox.state import SqliteGrantStore, StateStore, load_migrations

M1 = (1, "CREATE TABLE one (x INTEGER);")
M2 = (2, "CREATE TABLE two (y INTEGER);")


def _migrate_once(path: Path, backups: Path, migrations: list[tuple[int, str]]) -> None:
    store = StateStore(path, backup_dir=backups, migrations=migrations)
    try:
        store.migrate()
    finally:
        store.close()  # H1 D-23: no unclosed connections (ResourceWarning on 3.14)


def _store(tmp_path: Path) -> StateStore:
    store = StateStore(tmp_path / "state.db", backup_dir=tmp_path / "backup")
    store.migrate()
    return store


def test_packaged_migrations_are_numbered_from_one() -> None:
    migrations = load_migrations()
    assert [n for n, _ in migrations] == list(range(1, len(migrations) + 1))


def test_migrate_sets_version_and_wal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.user_version == len(load_migrations())
    assert store.core_query("PRAGMA journal_mode")[0][0] == "wal"
    store.migrate()  # idempotent
    assert not list((tmp_path / "backup").glob("*"))  # a fresh database needs no backup
    store.close()


def test_upgrade_takes_a_backup_first(tmp_path: Path) -> None:
    path, backups = tmp_path / "s.db", tmp_path / "backup"
    _migrate_once(path, backups, [M1])
    s = StateStore(path, backup_dir=backups, migrations=[M1, M2])
    s.migrate()
    assert s.user_version == 2
    [backup] = backups.glob("*.db")
    old = sqlite3.connect(backup)
    try:
        assert old.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        old.close()
    s.close()


def test_failed_migration_rolls_back(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    _migrate_once(path, tmp_path / "b", [M1])
    bad = (2, "CREATE TABLE two (y INTEGER); CREATE TABLE one (x INTEGER);")
    s = StateStore(path, backup_dir=tmp_path / "b", migrations=[M1, bad])
    with pytest.raises(StateError, match="migration 2"):
        s.migrate()
    assert s.user_version == 1
    assert s.core_query("SELECT name FROM sqlite_master WHERE name = 'two'") == []
    s.close()


def test_newer_database_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    _migrate_once(path, tmp_path / "b", [M1, M2])
    with pytest.raises(StateError, match="newer"):
        _migrate_once(path, tmp_path / "b", [M1])


def test_migration_numbers_must_be_contiguous(tmp_path: Path) -> None:
    with pytest.raises(StateError, match="contiguous"):
        StateStore(tmp_path / "s.db", backup_dir=tmp_path / "b", migrations=[M1, (3, "SELECT 1;")])


def test_grants_persist_across_reopen(
    tmp_path: Path, make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    store = _store(tmp_path)
    engine = PolicyEngine(SqliteGrantStore(store), audit)
    engine.register(make_manifest(request=["ui.panel", "schedule"]))
    engine.grant("demo", "ui.panel", actor="user")
    engine.grant("demo", "schedule", actor="user")
    engine.revoke("demo", "schedule", actor="user")
    store.close()

    store = _store(tmp_path)
    grants = SqliteGrantStore(store)
    assert grants.load("demo") == frozenset({"ui.panel"})
    grants.add("demo", "ui.panel")  # duplicate add is harmless
    grants.remove_all("demo")
    assert grants.load("demo") == frozenset()
    store.close()


# module namespaces ---------------------------------------------------------------------------------------


def test_module_table_round_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ms = store.module("demo")
    ms.create_table("items", [("id", "INTEGER"), ("name", "TEXT")], primary_key=["id"])
    ms.create_table("items", [("id", "INTEGER"), ("name", "TEXT")], primary_key=["id"])  # idempotent
    ms.execute("INSERT INTO m_demo__items (id, name) VALUES (?, ?)", (1, "a"))
    rows = ms.execute("WITH t AS (SELECT * FROM m_demo__items) SELECT name FROM t WHERE id = ?", (1,))
    assert rows == [("a",)]
    assert ms.table("items") == "m_demo__items"
    store.close()


@pytest.mark.parametrize("name", ["Items", "x;y", "a" * 33, "", "1abc", "items--"])
def test_bad_table_names_are_refused(tmp_path: Path, name: str) -> None:
    store = _store(tmp_path)
    with pytest.raises(StateError, match="name"):
        store.module("demo").create_table(name, [("x", "TEXT")])
    store.close()


@pytest.mark.parametrize(
    "columns",
    [[("x", "TEXT); DROP TABLE grants; --")], [("Bad", "TEXT")], [("x", "JSON")], []],
)
def test_bad_columns_are_refused(tmp_path: Path, columns: list[tuple[str, str]]) -> None:
    store = _store(tmp_path)
    with pytest.raises(StateError):
        store.module("demo").create_table("t", columns)
    store.close()


def test_primary_key_must_name_a_column(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(StateError, match="primary key"):
        store.module("demo").create_table("t", [("x", "TEXT")], primary_key=["y"])
    store.close()


def test_bad_module_id_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(StateError, match="module id"):
        store.module("Demo; DROP")
    store.close()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM grants",
        "SELECT * FROM m_other__items",
        "SELECT name FROM sqlite_master",
        "PRAGMA user_version = 0",
        "ATTACH DATABASE 'x.db' AS x",
        "CREATE TABLE m_demo__sneaky (x)",
        "DROP TABLE m_demo__items",
        "BEGIN",
        "DELETE FROM kv",
        "INSERT INTO m_demo__items (id, name) SELECT 9, capability FROM grants",
    ],
)
def test_module_sql_is_confined(tmp_path: Path, sql: str) -> None:
    store = _store(tmp_path)
    other = store.module("other")
    other.create_table("items", [("id", "INTEGER")])
    ms = store.module("demo")
    ms.create_table("items", [("id", "INTEGER"), ("name", "TEXT")])
    with pytest.raises(StateError, match=r"denied|not allowed"):
        ms.execute(sql)
    # the core connection is unaffected afterwards
    assert store.core_query("SELECT count(*) FROM grants") == [(0,)]
    store.close()


def test_one_statement_per_call(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ms = store.module("demo")
    ms.create_table("items", [("id", "INTEGER")])
    with pytest.raises(StateError):
        ms.execute("INSERT INTO m_demo__items VALUES (1); DELETE FROM m_demo__items")
    store.close()


def test_kv_is_isolated_per_module(tmp_path: Path) -> None:
    store = _store(tmp_path)
    a, b = store.module("alpha"), store.module("beta")
    a.kv_set("k", {"n": 1})
    assert a.kv_get("k") == {"n": 1}
    assert b.kv_get("k") is None and b.kv_get("k", "dflt") == "dflt"
    a.kv_set("k", [1, 2])
    assert a.kv_get("k") == [1, 2]
    with pytest.raises(StateError, match="key"):
        a.kv_set("", 1)
    with pytest.raises(StateError, match="JSON"):
        a.kv_set("k", object())
    store.close()


def test_drop_all_removes_only_that_module(tmp_path: Path) -> None:
    store = _store(tmp_path)
    a, b = store.module("alpha"), store.module("beta")
    for ms in (a, b):
        ms.create_table("t", [("x", "TEXT")])
        ms.kv_set("k", 1)
    a.drop_all()
    names = {r[0] for r in store.core_query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "m_alpha__t" not in names and "m_beta__t" in names
    assert a.kv_get("k") is None and b.kv_get("k") == 1
    store.close()


def test_double_underscore_cannot_forge_a_namespace(tmp_path: Path) -> None:
    # Module "foo" owns m_foo__*; a module id or table name containing "__" could collide with it.
    store = _store(tmp_path)
    with pytest.raises(StateError, match="module id"):
        store.module("foo__bar")
    with pytest.raises(StateError, match="name"):
        store.module("foo").create_table("bar__baz", [("x", "TEXT")])
    store.close()


def test_module_queries_have_a_work_budget_and_row_cap(tmp_path: Path) -> None:
    from hermes_signalbox import state as state_mod

    store = StateStore(tmp_path / "state.db", backup_dir=tmp_path / "backup")
    store.migrate()
    mod = store.module("demo")
    # Recursive CTEs are already refused by the authorizer (CTE names are not module tables); a cross join on
    # the module's own table is the remaining way to burn CPU or memory.
    mod.create_table("t", [("n", "INTEGER")])
    t = mod.table("t")
    for i in range(200):
        mod.execute(f"INSERT INTO {t} VALUES (?)", (i,))  # noqa: S608
    assert mod.execute(f"SELECT count(*) FROM {t}") == [(200,)]  # noqa: S608
    with pytest.raises(StateError, match="work budget"):
        mod.execute(f"SELECT count(*) FROM {t} a, {t} b, {t} c, {t} d")  # noqa: S608
    assert state_mod.MAX_ROWS < 200 * 200
    with pytest.raises(StateError, match="rows"):
        mod.execute(f"SELECT a.n FROM {t} a, {t} b")  # noqa: S608
    assert mod.execute("SELECT 1") == [(1,)]
    store.close()


def test_h1_deadline_bounds_lock_and_busy_waits(tmp_path: Path) -> None:
    """ADR-0013: a thread inside ``deadline(s)`` waits at most ``s`` in total for the store lock and for
    SQLite locks held by other processes; the store-wide busy wait is restored afterwards."""
    import threading
    import time

    store = _store(tmp_path)
    mod = store.module("m1")
    mod.create_table("t", [("k", "TEXT")], primary_key=["k"])
    table = mod.table("t")
    select, insert = "SELECT k FROM " + table, "INSERT INTO " + table + " VALUES (?)"  # noqa: S608
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with store._lock:
            held.set()
            release.wait(10)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(2)
    try:
        started = time.monotonic()
        with mod.deadline(0.2) as limit, pytest.raises(StateError, match="busy"):
            mod.execute(select)
        assert time.monotonic() - started < 1.0 and limit.remaining() < 0.1  # clock granularity (Windows)
    finally:
        release.set()
        t.join()
    other = sqlite3.connect(str(tmp_path / "state.db"), isolation_level=None)
    other.execute("BEGIN EXCLUSIVE")
    try:
        started = time.monotonic()
        with store.deadline(0.3), pytest.raises(StateError, match=r"busy|locked"):
            mod.execute(insert, ("a",))
        assert time.monotonic() - started < 2.0
        with store.deadline(0.3), store.deadline(5.0) as inner:  # nesting never extends the outer limit
            assert inner.remaining() <= 0.31
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert store.core_query("PRAGMA busy_timeout")[0][0] == 5000
    with store.deadline(1.0):
        mod.execute(insert, ("b",))
    assert mod.execute(select) == [("b",)]
    with store.deadline(0.0), pytest.raises(StateError, match="busy"):
        store.core_query("SELECT 1")  # nothing left of the budget
    store.close()
