"""SQLite state store, migrations, grants persistence and module namespaces (spec section 3, State store)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sy_testing import ManifestFactory, RecordingAudit

from switchyard.capabilities import PolicyEngine
from switchyard.errors import StateError
from switchyard.state import SqliteGrantStore, StateStore, load_migrations

M1 = (1, "CREATE TABLE one (x INTEGER);")
M2 = (2, "CREATE TABLE two (y INTEGER);")


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
    StateStore(path, backup_dir=backups, migrations=[M1]).migrate()
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
    StateStore(path, backup_dir=tmp_path / "b", migrations=[M1]).migrate()
    bad = (2, "CREATE TABLE two (y INTEGER); CREATE TABLE one (x INTEGER);")
    s = StateStore(path, backup_dir=tmp_path / "b", migrations=[M1, bad])
    with pytest.raises(StateError, match="migration 2"):
        s.migrate()
    assert s.user_version == 1
    assert s.core_query("SELECT name FROM sqlite_master WHERE name = 'two'") == []
    s.close()


def test_newer_database_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    StateStore(path, backup_dir=tmp_path / "b", migrations=[M1, M2]).migrate()
    with pytest.raises(StateError, match="newer"):
        StateStore(path, backup_dir=tmp_path / "b", migrations=[M1]).migrate()


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
