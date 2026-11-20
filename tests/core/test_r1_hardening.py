"""R1 hardening review regressions (core trust boundary and Hermes integration)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from sy_testing import write_module

from switchyard.audit import AuditLog
from switchyard.core import Core
from switchyard.errors import CapabilityDenied, StateError, SwitchyardError
from switchyard.logs import MAX_STREAM_BYTES, JsonlLogSink
from switchyard.rpc import Channel, ProtocolError
from switchyard.state import StateStore
from switchyard.trim import MUST_KEEP

SUBSCRIBER = """
class Mod:
    def activate(self, ctx):
        self.ctx = ctx
        ctx.subscribe("*", lambda e: None)
    def deactivate(self):
        self.ctx = None
    def health(self):
        return (True, "ok")
"""


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "no-hermes"))


def test_two_audit_writers_keep_one_chain(tmp_path: Path) -> None:
    a, b = AuditLog(tmp_path / "audit"), AuditLog(tmp_path / "audit")
    for i in range(6):
        (a if i % 2 else b).append(actor="t", action="x", module="", detail={"i": str(i)})
    result = AuditLog.verify_directory(tmp_path / "audit")
    assert result.ok and result.records == 6


def test_truncation_stays_reported_until_acknowledged(tmp_path: Path) -> None:
    data = tmp_path / "d"
    core = Core(data_dir=data)
    for i in range(4):
        core.audit.append(actor="t", action="x", module="", detail={"i": str(i)})
    core.close()
    log = sorted((data / "audit").glob("audit-*.jsonl"))[-1]
    lines = log.read_bytes().splitlines(keepends=True)
    log.write_bytes(b"".join(lines[:-2]))  # drop the last two records
    core = Core(data_dir=data)
    try:
        assert not core.run("audit", "verify", {}, actor="t")["ok"]
        core.audit.append(actor="t", action="x", module="", detail={})  # later appends move the anchor ...
        verdict = core.run("audit", "verify", {}, actor="t")
        assert not verdict["ok"] and "audit ack" in verdict["reason"]  # ... but the failure stays
        with pytest.raises(CapabilityDenied):
            core.run("audit", "ack", {}, actor="hermes")
        assert core.run("audit", "ack", {}, actor="cli")["acknowledged"]
        assert core.run("audit", "verify", {}, actor="t")["ok"]
    finally:
        core.close()


def test_trailing_underscore_ids_cannot_reach_other_tables(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "s.db", backup_dir=tmp_path / "backup")
    store.migrate()
    with pytest.raises(StateError):
        store.module("ab_")  # ids may not end in "_"
    store.core_execute('CREATE TABLE "m_ab___notes" (v TEXT)')  # left by a module id allowed before R1
    attacker = store.module("ab")
    with pytest.raises(StateError, match="access denied"):
        attacker.execute('SELECT * FROM "m_ab___notes"')
    attacker.drop_all()  # does not fail on, or touch, the other table
    assert store.core_query("SELECT name FROM sqlite_master WHERE name = 'm_ab___notes'")


def test_model_actor_is_refused_operator_ops_in_the_core(tmp_path: Path) -> None:
    core = Core(data_dir=tmp_path / "d")
    try:
        for noun, verb, params in (("module", "deactivate", {"id": "x"}), ("audit", "ack", {})):
            with pytest.raises(CapabilityDenied, match="operator only"):
                core.run(noun, verb, params, actor="hermes")
        assert core.run("module", "list", {}, actor="hermes") is not None
    finally:
        core.close()


def _trusted_core(tmp_path: Path, **kw: Any) -> tuple[Core, Path]:
    trusted = tmp_path / "trusted"
    trusted.mkdir(exist_ok=True)
    data = tmp_path / "d"
    return Core(
        data_dir=data, trusted_roots=[trusted], module_roots=[trusted, data / "modules"], **kw
    ), trusted


def test_wildcard_and_core_subscriptions_need_core_read(tmp_path: Path) -> None:
    (tmp_path / "trusted").mkdir()
    write_module(tmp_path / "trusted", "spy", SUBSCRIBER)
    core, _ = _trusted_core(tmp_path)
    try:
        core.run("module", "activate", {"id": "spy"}, actor="t")
        assert core.run("module", "show", {"id": "spy"}, actor="t")["status"] == "failed"
    finally:
        core.close()


def test_kept_facade_is_rechecked_after_deactivation(tmp_path: Path) -> None:
    (tmp_path / "trusted").mkdir()
    write_module(tmp_path / "trusted", "keeper", request=("schedule",))
    core, _ = _trusted_core(tmp_path, hosting=True)
    try:
        core.run("module", "grant", {"id": "keeper", "capability": "schedule"}, actor="t")
        core.run("module", "activate", {"id": "keeper"}, actor="t")
        kept = core.manager._entry("keeper").instance.ctx.schedule
        core.run("module", "deactivate", {"id": "keeper"}, actor="t")
        with pytest.raises(SwitchyardError):
            kept.every("again", 60, lambda: None)
    finally:
        core.close()


def test_removal_never_keeps_grants(tmp_path: Path) -> None:
    (tmp_path / "trusted").mkdir()
    write_module(tmp_path / "trusted", "keepme", request=("ui.panel",))
    core, _ = _trusted_core(tmp_path)
    try:
        core.run("module", "grant", {"id": "keepme", "capability": "ui.panel"}, actor="t")
        core.run("module", "remove", {"id": "keepme", "keep_data": True}, actor="t")
        assert core.policy.granted("keepme") == frozenset()
    finally:
        core.close()


def test_rpc_call_has_one_total_deadline() -> None:
    def recv(timeout: float | None) -> Any:
        time.sleep(0.05)
        return {"jsonrpc": "2.0", "id": 99, "method": "ctx.log", "params": {}}  # a request, never the answer

    channel = Channel(lambda m: None, recv, lambda method, params: None)
    started = time.monotonic()
    with pytest.raises(ProtocolError, match="did not finish"):
        channel.request("health", {}, timeout=0.3)
    assert time.monotonic() - started < 2


def test_log_streams_are_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("switchyard.logs.MAX_STREAM_BYTES", 2000)
    sink = JsonlLogSink(tmp_path)
    for i in range(100):
        sink.write("m", "s", "e", {"i": i, "pad": "x" * 50})
    assert (tmp_path / "s.jsonl").stat().st_size <= 2000
    assert (tmp_path / "s.1.jsonl").stat().st_size <= 2000
    assert MAX_STREAM_BYTES >= 1_000_000


@pytest.mark.parametrize(
    "line",
    [
        "HTTP/1.1 403 Forbidden",
        "401 Unauthorized: token expired",
        "rejected: signature mismatch",
        "blocked by policy: outbound host",
    ],
)
def test_auth_failures_are_never_trimmed(line: str) -> None:
    assert MUST_KEEP.search(line)


def test_module_results_reach_the_model_labelled() -> None:
    from switchyard.hermes import UNTRUSTED_NOTE

    assert "data" in UNTRUSTED_NOTE and json.dumps({"note": UNTRUSTED_NOTE})
