"""1.1: Hermes config writes lock across processes; a rollback never undoes another writer (H1 C-17 #115)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from switchyard.errors import SwitchyardError
from switchyard.hermesconfig import WRITE_LOCK_NAME, ConfigWriter
from switchyard.hostlock import FileLock


class _Sink:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def append(self, *, actor: str, action: str, module: str, detail: dict[str, str]) -> None:
        self.records.append({"action": action, "detail": dict(detail)})


class _Port:
    """A Hermes config with one list key. ``after_write`` lets a test change it as another writer would."""

    def __init__(self, value: list[str]) -> None:
        self.value = list(value)
        self.writes: list[list[str]] = []
        self.after_write: Any = None
        self.during_write: Any = None

    def get(self, key: str) -> Any:
        return list(self.value)

    def set(self, key: str, value: Any) -> None:
        if self.during_write is not None:
            self.during_write()
        self.writes.append(list(value))
        self.value = list(value)
        if self.after_write is not None:
            hook, self.after_write = self.after_write, None
            hook()

    def skills(self) -> list[dict[str, str]]:
        return [{"name": n} for n in ("a", "b", "c", "intruder", "other")]

    def essential(self) -> frozenset[str]:
        return frozenset()


def test_h1_c17_the_write_holds_a_cross_process_lock(tmp_path: Path) -> None:
    port = _Port(["a"])
    seen: list[str] = []

    def another_process_tries() -> None:
        try:
            with FileLock(tmp_path / "b" / WRITE_LOCK_NAME, timeout=0.05):
                seen.append("got it")
        except TimeoutError:
            seen.append("waited")

    port.during_write = another_process_tries
    ConfigWriter(port, _Sink(), tmp_path / "b").set("activation", "skills.disabled", ["a", "b"], actor="t")  # type: ignore[arg-type]
    assert seen == ["waited"]


def test_h1_c17_a_rollback_never_overwrites_another_writer(tmp_path: Path) -> None:
    port = _Port(["a"])
    sink = _Sink()
    reads: list[int] = []

    def get(key: str) -> Any:
        # First read-back: a name we did not write, so the write is rolled back. Before the rollback,
        # another writer (Hermes itself, or a hand edit) has changed the key again.
        reads.append(1)
        return ["a", "b", "intruder"] if len(reads) == 1 else ["other"]

    port.after_write = lambda: setattr(port, "get", get)
    with pytest.raises(SwitchyardError, match="changed by another writer"):
        ConfigWriter(port, sink, tmp_path / "b").set("activation", "skills.disabled", ["a", "b"], actor="t")  # type: ignore[arg-type]
    assert port.writes == [["a", "b"]]  # no restore written over "other"
    rollback = [r for r in sink.records if r["action"] == "hermes.config.rollback"]
    assert rollback and rollback[-1]["detail"]["restored"] == "skipped"


def test_h1_c17_a_rollback_of_our_own_write_still_restores(tmp_path: Path) -> None:
    port = _Port(["a"])
    sink = _Sink()

    def get(key: str) -> Any:
        return ["a", "b", "intruder"]

    port.after_write = lambda: setattr(port, "get", get)
    with pytest.raises(SwitchyardError, match="previous value restored"):
        ConfigWriter(port, sink, tmp_path / "b").set("activation", "skills.disabled", ["a", "b"], actor="t")  # type: ignore[arg-type]
    assert port.writes == [["a", "b"], ["a"]]
