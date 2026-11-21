"""1.1 backlog: module storage is bounded (H1 A-25 #93): value size, table count and a per-module quota."""

from __future__ import annotations

from pathlib import Path

import pytest

from switchyard import state as state_mod
from switchyard.errors import StateError
from switchyard.state import StateStore

BIG = state_mod.MAX_VALUE_BYTES + 1


def _insert(table: str, column: str = "v", value: str = "?") -> str:
    return f'INSERT INTO "{table}" ({column}) VALUES ({value})'  # noqa: S608 - module-owned name


def _delete(table: str) -> str:
    return f'DELETE FROM "{table}"'  # noqa: S608 - module-owned name


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    s = StateStore(tmp_path / "state.db", backup_dir=tmp_path / "backups")
    s.migrate()
    return s


def test_h1_a25_a_value_over_the_cap_is_refused(store: StateStore) -> None:
    m = store.module("demo")
    m.create_table("blobs", [("data", "BLOB")])
    t = m.table("blobs")
    with pytest.raises(StateError, match="too large"):
        m.execute(_insert(t, "data"), (b"x" * BIG,))
    with pytest.raises(StateError, match="too large"):  # SQLite-side amplification is capped too
        m.execute(_insert(t, "data", "zeroblob(?)"), (BIG,))
    m.execute(_insert(t, "data"), (b"x" * 1000,))  # normal values still fit
    assert store.core_query("SELECT length(zeroblob(?))", (BIG,))[0][0] == BIG  # the core is not capped


def test_h1_a25_a_kv_value_over_the_cap_is_refused(store: StateStore) -> None:
    with pytest.raises(StateError, match="kv value"):
        store.module("demo").kv_set("k", "x" * BIG)


def test_h1_a25_a_module_has_a_table_limit(store: StateStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_mod, "MAX_TABLES_PER_MODULE", 3)
    m = store.module("demo")
    for i in range(3):
        m.create_table(f"t{i}", [("v", "INTEGER")])
    m.create_table("t0", [("v", "INTEGER")])  # IF NOT EXISTS on an existing table is not a new one
    with pytest.raises(StateError, match="at most 3 tables"):
        m.create_table("t3", [("v", "INTEGER")])


@pytest.mark.parametrize("dbstat", [True, False])
def test_h1_a25_over_the_quota_writes_stop_until_data_is_deleted(
    store: StateStore, monkeypatch: pytest.MonkeyPatch, dbstat: bool
) -> None:
    monkeypatch.setattr(state_mod, "MODULE_QUOTA_BYTES", 64 * 1024)
    monkeypatch.setattr(state_mod, "QUOTA_CHECK_GROWTH", 0)
    if not dbstat:
        monkeypatch.setattr(store, "_dbstat", False)
    m = store.module("demo")
    m.create_table("rows", [("v", "BLOB")])
    t = m.table("rows")
    with pytest.raises(StateError, match="storage quota"):
        for _ in range(200):
            m.execute(_insert(t), (b"x" * 4096,))
    with pytest.raises(StateError, match="storage quota"):
        m.kv_set("k", "v")
    store.module("other").kv_set("k", "v")  # another module is not affected
    m.execute(_delete(t))  # deleting is always allowed, and frees the module
    m.execute(_insert(t), (b"x",))
    m.kv_set("k", "v")


def test_h1_a25_the_default_trigger_is_database_growth(
    store: StateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "MODULE_QUOTA_BYTES", 256 * 1024)
    measured: list[str] = []
    real = store.usage_bytes
    monkeypatch.setattr(store, "usage_bytes", lambda mid: measured.append(mid) or real(mid))
    m = store.module("demo")
    m.create_table("rows", [("v", "BLOB")])  # create_table always measures
    t = m.table("rows")
    measured.clear()
    for _ in range(20):  # small writes: no growth worth measuring
        m.execute(_insert(t), (b"x",))
    assert measured == []
    with pytest.raises(StateError, match="storage quota"):  # 1 MiB of growth triggers it
        for _ in range(400):
            m.execute(_insert(t), (b"x" * 8192,))
    assert measured


def test_h1_a25_usage_is_reported(store: StateStore) -> None:
    m = store.module("demo")
    m.create_table("rows", [("v", "TEXT")])
    m.execute(_insert(m.table("rows")), ("hello" * 100,))
    m.kv_set("k", "x" * 100)
    assert m.usage_bytes() >= 600
