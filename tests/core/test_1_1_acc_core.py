"""1.1 acceptance security review, core: discovery survives a hostile manifest, one manifest read, audit
encoding (S1-3, S1-6, S1-8, S1-10)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from sy_testing import ManifestFactory, RecordingAudit, write_module

from hermes_signalbox.audit import AuditLog
from hermes_signalbox.errors import AuditError, ManifestError, SignalboxError
from hermes_signalbox.host_t2 import T2Module
from hermes_signalbox.manifest import load_manifest


def _manager(tmp_path: Path, audit: RecordingAudit):  # type: ignore[no-untyped-def]
    from hermes_signalbox.capabilities import MemoryGrantStore, PolicyEngine
    from hermes_signalbox.context import MemoryPanelRegistry
    from hermes_signalbox.events import EventBus
    from hermes_signalbox.lifecycle import ModuleManager
    from hermes_signalbox.logs import JsonlLogSink
    from hermes_signalbox.scheduler import Scheduler

    trusted = tmp_path / "trusted"
    trusted.mkdir()
    bus = EventBus(audit, clock=lambda: "t")
    manager = ModuleManager(
        policy=PolicyEngine(MemoryGrantStore(), audit), audit=audit, bus=bus,
        logs=JsonlLogSink(tmp_path / "logs"), panels=MemoryPanelRegistry(),
        scheduler=Scheduler(bus, audit, monotonic=lambda: 0.0), store=None, trusted_roots=[trusted],
        clock=lambda: 0.0,
    )  # fmt: skip
    return manager, trusted


def test_s1_3_an_overlong_requires_core_is_a_manifest_error(make_manifest: ManifestFactory) -> None:
    with pytest.raises(ManifestError, match="requires_core"):
        make_manifest("demo", requires_core=",".join(["<1"] * 400))


def test_s1_3_a_hostile_manifest_does_not_stop_discovery(tmp_path: Path, audit: RecordingAudit) -> None:
    manager, trusted = _manager(tmp_path, audit)
    write_module(trusted, "aaa", requires_core=",".join(["<1"] * 400))
    write_module(trusted, "bbb")
    assert manager.discover([trusted]) == ["bbb"]  # no exception; the good module still loads
    assert any(r["action"] == "module.rejected" for r in audit.records)


def test_s1_3_the_outdated_warning_detail_is_clipped(tmp_path: Path, audit: RecordingAudit) -> None:
    manager, trusted = _manager(tmp_path, audit)
    spec = ">=0.0.0," + ",".join(["<1"] * 30)  # within the length cap, only the old "<1" bound: outdated
    write_module(trusted, "old", requires_core=spec)
    assert manager.discover([trusted]) == ["old"]
    rec = next(r for r in audit.records if r["action"] == "module.requires_core_outdated")
    assert len(rec["detail"]["requires_core"]) <= 200


def test_s1_6_the_verified_digest_is_of_the_bytes_that_were_loaded(make_manifest: ManifestFactory) -> None:
    manifest = make_manifest("demo")
    raw = (manifest.directory / "module.toml").read_bytes()
    assert manifest.digest == hashlib.sha256(raw).hexdigest()


def test_s1_6_discovery_reads_the_manifest_once(
    tmp_path: Path, audit: RecordingAudit, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, trusted = _manager(tmp_path, audit)
    write_module(trusted, "demo")

    def no_reread(self: Path) -> bytes:
        raise AssertionError(f"manifest re-read: {self}")

    monkeypatch.setattr(Path, "read_bytes", no_reread)
    assert manager.discover([trusted]) == ["demo"]


def test_s1_8_t2_create_table_rejects_malformed_columns() -> None:
    calls: list[object] = []
    ctx = SimpleNamespace(state=SimpleNamespace(create_table=lambda *a, **k: calls.append((a, k))))
    for bad in (["ab"], [["a", "b", "c"]], [["a"]], [5]):
        with pytest.raises(SignalboxError, match="column"):
            T2Module._state(ctx, "create_table", ["t", bad, None])  # type: ignore[arg-type]
    T2Module._state(ctx, "create_table", ["t", [["a", "text"]], None])  # type: ignore[arg-type]
    assert calls and calls[0][0][1] == [("a", "text")]


def test_s1_10_an_unencodable_detail_is_an_audit_error(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit")
    with pytest.raises(AuditError):
        log.append(actor="t", action="x", module="m", detail={"k": "\ud800"})
    log.append(actor="t", action="y", module="m", detail={"k": "fine"})  # the chain still advances
    assert log.head[0] == 1


def test_bundled_manifests_still_load() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "hermes_signalbox" / "modules"
    for d in sorted(p for p in root.iterdir() if (p / "module.toml").is_file()):
        assert load_manifest(d).digest
