"""Core wiring and the shared operations table (spec sections 2 and 3; every surface uses ``Core.run``)."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from switchyard.core import Core
from switchyard.errors import AuditError, CapabilityDenied, SwitchyardError
from switchyard.ops import OPERATIONS, UsageError
from switchyard.scheduler import Trigger
from switchyard.secrets import MemoryBackend

ROOT = Path(__file__).resolve().parents[2]
CANARY = "canary-" + "core-value-123"

BROKER_MOD = """
class Mod:
    def activate(self, ctx):
        status = ctx.secrets.use("secret://provider.key", lambda v: "ok" if v else "missing")
        ctx.log("{id}", "secret-checked", status=status)
    def deactivate(self): ...
    def health(self): return True
"""


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


def _core(tmp_path: Path, **kw: Any) -> Core:
    trusted = tmp_path / "trusted"
    trusted.mkdir(exist_ok=True)
    kw.setdefault("trusted_roots", [trusted])
    kw.setdefault("module_roots", [trusted, tmp_path / "data" / "modules"])
    return Core(data_dir=tmp_path / "data", **kw)


def _with_example(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "templates" / "module", tmp_path / "trusted" / "example",
                    ignore=shutil.ignore_patterns("__pycache__", "tests"))  # fmt: skip


def test_open_creates_layout_and_verifies_audit(tmp_path: Path) -> None:
    with _core(tmp_path) as core:
        assert (tmp_path / "data" / "state.db").exists() and (tmp_path / "data" / "audit").is_dir()
        assert core.audit_status.ok
        assert core.run("module", "list", {}, actor="test") == []


def test_full_module_flow_through_operations(tmp_path: Path) -> None:
    (tmp_path / "trusted").mkdir()
    _with_example(tmp_path)
    with _core(tmp_path) as core:
        [row] = core.run("module", "list", {}, actor="cli")
        assert row["id"] == "example" and row["status"] == "verified" and row["granted"] == []
        assert row["requested"] == ["ui.panel"]
        core.run("module", "grant", {"id": "example", "capability": "ui.panel"}, actor="cli")
        core.run("module", "activate", {"id": "example"}, actor="cli")
        assert core.run("module", "health", {"id": "example"}, actor="cli") == {
            "ok": True,
            "detail": "active",
        }
        panel = core.run("module", "panel", {"id": "example", "panel": "example.status"}, actor="cli")
        assert panel == {"title": "Example", "state": "active"}
        shown = core.run("module", "show", {"id": "example"}, actor="cli")
        assert shown["panels"] == ["example.status"] and shown["contributes"]["log_streams"] == ["example"]
        core.run("module", "mode", {"id": "example", "mode": "auto"}, actor="cli")
        core.run("module", "deactivate", {"id": "example"}, actor="cli")
        core.run("module", "revoke", {"id": "example", "capability": "ui.panel"}, actor="cli")
        core.run("module", "remove", {"id": "example"}, actor="cli")
        assert core.run("module", "list", {}, actor="cli") == []
        actions = [r["action"] for r in core.run("audit", "tail", {"n": 50}, actor="cli")]
        assert {"policy.granted", "module.activated", "module.removed"} <= set(actions)
        assert core.run("audit", "verify", {}, actor="cli")["ok"] is True


def test_grants_and_modes_persist_across_restarts(tmp_path: Path) -> None:
    (tmp_path / "trusted").mkdir()
    _with_example(tmp_path)
    with _core(tmp_path) as core:
        core.run("module", "grant", {"id": "example", "capability": "ui.panel"}, actor="cli")
        core.run("module", "mode", {"id": "example", "mode": "disabled"}, actor="cli")
    with _core(tmp_path) as core:
        [row] = core.run("module", "list", {}, actor="cli")
        assert row["granted"] == ["ui.panel"] and row["mode"] == "disabled"


def test_denied_capability_surfaces_as_capability_denied(tmp_path: Path) -> None:
    (tmp_path / "trusted").mkdir()
    _with_example(tmp_path)
    with _core(tmp_path) as core, pytest.raises(CapabilityDenied):
        core.run("module", "grant", {"id": "example", "capability": "net.outbound"}, actor="cli")


@pytest.mark.parametrize(
    ("noun", "verb", "params", "fragment"),
    [
        ("module", "launch", {}, "unknown operation"),
        ("module", "activate", {}, "missing parameter 'id'"),
        ("module", "activate", {"id": 5}, "'id' must be"),
        ("module", "list", {"surprise": 1}, "unknown parameter"),
        ("audit", "tail", {"n": "ten"}, "'n' must be"),
        ("audit", "tail", {"n": 100000}, "between"),
        ("module", "remove", {"id": "x", "keep_data": "yes"}, "'keep_data' must be"),
    ],
)
def test_usage_errors(tmp_path: Path, noun: str, verb: str, params: dict[str, Any], fragment: str) -> None:
    with _core(tmp_path) as core, pytest.raises(UsageError, match=fragment):
        core.run(noun, verb, params, actor="cli")


def test_every_operation_is_documented() -> None:
    for (noun, verb), op in OPERATIONS.items():
        assert op.description, f"{noun} {verb} has no description"
        assert op.noun == noun and op.verb == verb


def test_secrets_are_wired_and_the_value_never_lands_on_disk(tmp_path: Path) -> None:
    from sy_testing import write_module

    trusted = tmp_path / "trusted"
    trusted.mkdir()
    write_module(trusted, "sec", BROKER_MOD, request=("secrets.read",))
    toml = trusted / "sec" / "module.toml"
    text = toml.read_text(encoding="utf-8")
    text = text.replace(
        'request = ["secrets.read"]', 'request = ["secrets.read"]\nsecrets = ["provider.key"]'
    )
    toml.write_text(text, encoding="utf-8")
    with _core(
        tmp_path, secret_backends=[MemoryBackend({"provider.key": CANARY}, allow_test_backend=True)]
    ) as core:
        core.run("module", "grant", {"id": "sec", "capability": "secrets.read"}, actor="cli")
        core.run("module", "activate", {"id": "sec"}, actor="cli")
        assert core.run("module", "list", {}, actor="cli")[0]["status"] == "active"
    blob = "".join(
        p.read_text(encoding="utf-8", errors="replace") for p in (tmp_path / "data").rglob("*.jsonl")
    )
    assert '"status":"ok"' in blob and "secret.used" in blob and CANARY not in blob


def test_tampered_audit_is_reported_on_open(tmp_path: Path) -> None:
    (tmp_path / "trusted").mkdir()
    _with_example(tmp_path)
    with _core(tmp_path) as core:
        core.run("module", "grant", {"id": "example", "capability": "ui.panel"}, actor="cli")
    path = next((tmp_path / "data" / "audit").glob("audit-*.jsonl"))
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"actor":"core"', '"actor":"evil"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with _core(tmp_path) as core:
        assert not core.audit_status.ok
        assert core.run("audit", "verify", {}, actor="cli")["ok"] is False
        assert "audit.verify_failed" in [
            r["action"] for r in core.run("audit", "tail", {"n": 5}, actor="cli")
        ]


def test_truncated_audit_is_caught_by_the_anchor(tmp_path: Path) -> None:
    (tmp_path / "trusted").mkdir()
    _with_example(tmp_path)
    with _core(tmp_path) as core:
        core.run("module", "grant", {"id": "example", "capability": "ui.panel"}, actor="cli")
        core.run("module", "revoke", {"id": "example", "capability": "ui.panel"}, actor="cli")
    path = next((tmp_path / "data" / "audit").glob("audit-*.jsonl"))
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-2]) + "\n", encoding="utf-8")
    with _core(tmp_path) as core:
        assert not core.audit_status.ok and "anchor" in core.audit_status.reason


def test_config_file_is_loaded(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.toml").write_text(
        '[host]\nprofile = "server"\n[log]\nlevel = "DEBUG"\n', encoding="utf-8"
    )
    with _core(tmp_path) as core:
        assert core.run("host", "profile", {}, actor="cli")["profile_name"] == "server"
        cfg = core.run("config", "show", {}, actor="cli")
        assert cfg["log"]["level"] == "DEBUG" and cfg["api"] == {"enabled": False, "port": 0}
        assert Path(cfg["data_dir"]) == data


def test_tick_drives_scheduler_idle_stop_and_capacity(tmp_path: Path) -> None:
    with _core(tmp_path) as core:
        seen: list[dict[str, Any]] = []
        spec = {"metric": "disk.free_ratio", "below": 2.0}
        core.scheduler.add(Trigger(id="cap", owner="core", kind="capacity", spec=spec, callback=seen.append))
        core.tick()
        assert seen and seen[0]["metric"] == "disk.free_ratio"


def test_close_stops_active_modules(tmp_path: Path) -> None:
    (tmp_path / "trusted").mkdir()
    _with_example(tmp_path)
    core = _core(tmp_path)
    core.run("module", "grant", {"id": "example", "capability": "ui.panel"}, actor="cli")
    core.run("module", "activate", {"id": "example"}, actor="cli")
    core.close()
    core.close()  # idempotent
    lines = next((tmp_path / "data" / "audit").glob("audit-*.jsonl")).read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["detail"].get("reason") == "shutdown"


def test_operations_after_close_are_refused(tmp_path: Path) -> None:
    core = _core(tmp_path)
    core.close()
    with pytest.raises(SwitchyardError, match="closed"):
        core.run("module", "list", {}, actor="cli")


# H1 WP9 -------------------------------------------------------------------------------------------------


def test_h1_a10_failed_startup_releases_the_host_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import switchyard.core as core_mod

    data = tmp_path / "data"
    real = core_mod.StateStore

    def broken(*a: Any, **k: Any) -> Any:
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(core_mod, "StateStore", broken)
    with pytest.raises(sqlite3.OperationalError):
        Core(data_dir=data, hosting=True)
    monkeypatch.setattr(core_mod, "StateStore", real)
    with Core(data_dir=data, hosting=True) as c:  # same process: the lock was released
        assert c.hosting


def test_h1_a11_failed_acknowledgement_keeps_the_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    with Core(data_dir=data, hosting=True) as c:
        for i in range(3):
            c.audit.append(actor="t", action="x", module="", detail={"i": str(i)})
    log = next((data / "audit").glob("audit-*.jsonl"))
    lines = log.read_text(encoding="utf-8").splitlines(keepends=True)
    log.write_text("".join(lines[:-1]), encoding="utf-8")  # truncation: the anchor no longer matches
    with Core(data_dir=data, hosting=True) as c:
        assert not c.audit_status.ok

        def fail(**kw: Any) -> Any:
            raise AuditError("disk full")

        monkeypatch.setattr(c.audit_log, "append", fail)
        with pytest.raises(AuditError):
            c.run("audit", "ack", {}, actor="cli")
        monkeypatch.undo()
        assert c._audit_broken() is not None and c.audit.stored_head() is not None
        assert c.run("audit", "ack", {}, actor="cli")["acknowledged"] is True
    with Core(data_dir=data, hosting=True) as c:
        assert c.audit_status.ok


def test_h1_a9_torn_tail_at_startup_is_not_flagged(tmp_path: Path) -> None:
    data = tmp_path / "data"
    with Core(data_dir=data, hosting=True) as c:
        c.audit.append(actor="t", action="x", module="", detail={})
    log = next((data / "audit").glob("audit-*.jsonl"))
    with log.open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 99, "ts"')  # a crash mid-write
    with Core(data_dir=data, hosting=True) as c:
        assert c.audit_status.ok and c._audit_broken() is None
