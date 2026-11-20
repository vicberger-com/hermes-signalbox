"""H1 D-12: the per-platform skip allow-list."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from skip_allowlist import ALLOWLIST, allowed, compare


def test_h1_d12_compare_flags_new_skips_and_stale_entries() -> None:
    expected = frozenset({"tests/a.py::test_posix_only"})
    assert compare(["tests/a.py::test_posix_only"], ["tests/b.py::test_x"], expected) == []
    assert compare(["tests/a.py::test_posix_only", "tests/c.py::test_new[p1]"], [], expected) == [
        "unexpected skip: tests/c.py::test_new"
    ]
    assert compare([], ["tests/a.py::test_posix_only"], expected) == [
        "listed as skipped but ran: tests/a.py::test_posix_only"
    ]
    assert compare([], [], expected) == []  # deselected: not a problem


def test_h1_d12_allowlist_names_existing_tests_for_every_ci_os(tmp_path: Path) -> None:
    data = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    root = ALLOWLIST.parent.parent
    for platform in ("win32", "linux", "darwin"):
        for entry in allowed(platform):
            path, name = entry.split("::")
            assert f"def {name}(" in (root / path).read_text(encoding="utf-8"), entry
    assert set(data) >= {"win32", "linux", "darwin"}
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"win32": "not a list"}), encoding="utf-8")
    with pytest.raises(ValueError, match="list of test ids"):
        allowed("win32", bad)
