"""1.1 #124: per-call overhead on the model hot path (H2-2).

A routed model request made the router ask ``resources`` for candidates (a read-only cross-module call), and
every such call wrote an audit record; each append also re-read the audit log's tail. Both are bounded here.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import hermes_signalbox.core as core_mod
from hermes_signalbox.audit import AuditLog
from hermes_signalbox.core import Core

pytestmark = pytest.mark.bundled_modules


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)


@pytest.fixture
def core(tmp_path: Path) -> Iterator[Core]:
    c = Core(data_dir=tmp_path / "data", hosting=True)
    for cap in ("fs.read", "ui.panel"):
        c.run("module", "grant", {"id": "resources", "capability": cap}, actor="t")
    c.run("module", "activate", {"id": "resources"}, actor="t")
    yield c
    c.close()


def _records(core: Core, actor: str) -> list[dict]:
    return [r for r in core.audit_log.tail(500) if r["action"] == "module.action" and r["actor"] == actor]


def test_cross_module_read_calls_are_audited_once_per_window(core: Core) -> None:
    for _ in range(5):
        core._module_call("router", "resources", "pools", {})
    [only] = _records(core, "module:router")
    assert only["detail"] == {"action": "pools", "calls": "1"}


def test_cross_module_read_calls_are_counted_into_the_next_record(
    core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    core._module_call("router", "resources", "pools", {})
    for _ in range(3):
        core._module_call("router", "resources", "pools", {})
    monkeypatch.setattr(core_mod, "CROSS_CALL_AUDIT_WINDOW_S", 0.0)
    core._module_call("router", "resources", "pools", {})
    assert [r["detail"]["calls"] for r in _records(core, "module:router")] == ["1", "4"]


def test_operator_and_model_actions_are_still_audited_every_time(core: Core) -> None:
    for _ in range(3):
        core.run("module", "action", {"id": "resources", "action": "pools", "args": {}}, actor="cli")
    assert len(_records(core, "cli")) == 3


def test_append_skips_the_tail_read_when_this_process_wrote_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = AuditLog(tmp_path / "audit")
    log.append(actor="t", action="a", module="", detail={})
    reads = []
    real = AuditLog._recover

    def counting(self: AuditLog) -> tuple[int, str, int]:
        reads.append(1)
        return real(self)

    monkeypatch.setattr(AuditLog, "_recover", counting)
    for _ in range(3):
        log.append(actor="t", action="a", module="", detail={})
    assert reads == []
    other = AuditLog(tmp_path / "audit")  # another writer appends: the first must recover the new head
    other.append(actor="t", action="b", module="", detail={})
    log.append(actor="t", action="c", module="", detail={})
    assert reads and log.verify().ok and log.head[0] == 6
