"""1.1 acceptance security review, storage: the quota check notices reused free pages, and query results are
bounded in bytes (S2-2, S2-4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_signalbox import state as state_mod
from hermes_signalbox.errors import StateError
from hermes_signalbox.state import StateStore


def _insert(table: str) -> str:
    return f'INSERT INTO "{table}" (data) VALUES (?)'  # noqa: S608 - module-owned name


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    s = StateStore(tmp_path / "state.db", backup_dir=tmp_path / "backups")
    s.migrate()
    return s


def test_s2_2_writes_into_reused_free_pages_still_trigger_the_quota_check(
    store: StateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = store.module("other")
    other.create_table("blobs", [("data", "BLOB")])
    ot = other.table("blobs")
    for _ in range(
        12
    ):  # 12 MiB written, then deleted: the file keeps its size, the pages go to the free list
        other.execute(_insert(ot), (b"x" * (1024 * 1024),))
    other.execute(f'DELETE FROM "{ot}"')  # noqa: S608
    monkeypatch.setattr(state_mod, "MODULE_QUOTA_BYTES", 2 * 1024 * 1024)
    m = store.module("amod")
    m.create_table("blobs", [("data", "BLOB")])
    t = m.table("blobs")
    with pytest.raises(StateError, match="quota"):
        for _ in range(8):  # 8 MiB against a 2 MiB quota, all of it in reused pages
            m.execute(_insert(t), (b"y" * (1024 * 1024),))
    assert m.usage_bytes() < 5 * 1024 * 1024  # refused within one check interval of the quota


def test_s2_4_a_result_larger_than_the_byte_cap_is_refused(
    store: StateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "MAX_RESULT_BYTES", 2 * 1024 * 1024)
    m = store.module("demo")
    with pytest.raises(StateError, match="bytes"):
        m.execute("VALUES " + ", ".join(["(zeroblob(1000000))"] * 10))
    rows = m.execute("SELECT zeroblob(1000) UNION ALL SELECT zeroblob(1000)")
    assert len(rows) == 2  # small results are unchanged
