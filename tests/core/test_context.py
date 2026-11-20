"""ModuleContext (spec section 3, ModuleContext)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from sy_testing import ManifestFactory, RecordingAudit

from switchyard.capabilities import MemoryGrantStore, PolicyEngine
from switchyard.context import ContextServices, ModuleContext
from switchyard.errors import CapabilityDenied, SwitchyardError


class FakeLogs:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, str, dict[str, Any]]] = []

    def write(self, module_id: str, stream: str, event: str, fields: Mapping[str, Any]) -> None:
        self.lines.append((module_id, stream, event, dict(fields)))


class FakePanels:
    def __init__(self) -> None:
        self.panels: dict[tuple[str, str], Callable[[], Any]] = {}

    def add(self, module_id: str, panel_id: str, render: Callable[[], Any]) -> None:
        self.panels[(module_id, panel_id)] = render

    def remove_all(self, module_id: str) -> None:
        self.panels = {k: v for k, v in self.panels.items() if k[0] != module_id}


class FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, Any]]] = []
        self.subs: list[tuple[str, str]] = []

    def publish(self, source: str, type_: str, data: Mapping[str, Any]) -> None:
        self.published.append((source, type_, dict(data)))

    def subscribe(self, owner: str, type_: str, handler: Callable[..., None]) -> None:
        self.subs.append((owner, type_))

    def unsubscribe_all(self, owner: str) -> None:
        self.subs = [s for s in self.subs if s[0] != owner]


def _setup(
    make_manifest: ManifestFactory,
    audit: RecordingAudit,
    *,
    grant: tuple[str, ...] = (),
    brokers: Mapping[str, object] | None = None,
    **manifest_kw: Any,
) -> tuple[ModuleContext, ContextServices]:
    policy = PolicyEngine(MemoryGrantStore(), audit)
    m = make_manifest(**manifest_kw)
    policy.register(m)
    for cap in grant:
        policy.grant(m.id, cap, actor="user")
    services = ContextServices(
        policy=policy, logs=FakeLogs(), panels=FakePanels(), bus=FakeBus(), brokers=dict(brokers or {})
    )
    return ModuleContext(m, services), services


def test_log_goes_to_declared_stream(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    ctx, s = _setup(make_manifest, audit)
    ctx.log("demo", "started", count=1)
    assert s.logs.lines == [("demo", "demo", "started", {"count": 1})]  # type: ignore[attr-defined]
    with pytest.raises(SwitchyardError, match="log stream"):
        ctx.log("other", "x")


def test_panel_needs_grant_and_declaration(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    ctx, _ = _setup(make_manifest, audit)
    with pytest.raises(CapabilityDenied):
        ctx.register_panel("demo.status", dict)
    ctx, s = _setup(make_manifest, audit, grant=("ui.panel",))
    with pytest.raises(SwitchyardError, match="panel"):
        ctx.register_panel("demo.undeclared", dict)
    ctx.register_panel("demo.status", dict)
    assert ("demo", "demo.status") in s.panels.panels  # type: ignore[attr-defined]


def test_emit_is_namespaced(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    ctx, s = _setup(make_manifest, audit)
    ctx.emit("demo.tick", {"n": 1})
    assert s.bus.published == [("demo", "demo.tick", {"n": 1})]  # type: ignore[attr-defined]
    for spoof in ("module.activated", "demox.tick", "demo.", "demo"):
        with pytest.raises(SwitchyardError, match="event type"):
            ctx.emit(spoof, {})


def test_subscribe_records_owner(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    ctx, s = _setup(make_manifest, audit)
    ctx.subscribe("module.activated", lambda event: None)
    assert s.bus.subs == [("demo", "module.activated")]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("member", "capability"),
    [
        ("secrets", "secrets.read"),
        ("net", "net.outbound"),
        ("schedule", "schedule"),
        ("spawn", "process.spawn"),
    ],
)
def test_gated_members(
    make_manifest: ManifestFactory, audit: RecordingAudit, member: str, capability: str
) -> None:
    kw: dict[str, Any] = {"request": [capability], "panels": []}
    if capability == "net.outbound":
        kw["net_hosts"] = ["api.example.com"]
    if capability == "secrets.read":
        kw["secrets"] = ["provider.key"]
    broker = object()
    ctx, _ = _setup(make_manifest, audit, brokers={capability: broker}, **kw)
    with pytest.raises(CapabilityDenied):
        getattr(ctx, member)
    assert audit.records[-1]["action"] == "policy.denied"

    ctx, _ = _setup(make_manifest, audit, grant=(capability,), brokers={capability: broker}, **kw)
    assert getattr(ctx, member)._facade is broker  # wrapped: re-checked on every call (R1 review)

    ctx, _ = _setup(make_manifest, audit, grant=(capability,), **kw)
    with pytest.raises(SwitchyardError, match="not available"):
        getattr(ctx, member)


def test_close_revokes_everything(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    ctx, s = _setup(make_manifest, audit, grant=("ui.panel",))
    ctx.register_panel("demo.status", dict)
    ctx.subscribe("x.y", lambda event: None)
    ctx.close()
    ctx.close()  # idempotent
    assert s.panels.panels == {}  # type: ignore[attr-defined]
    assert s.bus.subs == []  # type: ignore[attr-defined]
    for call in (
        lambda: ctx.log("demo", "x"),
        lambda: ctx.register_panel("demo.status", dict),
        lambda: ctx.emit("demo.x", {}),
        lambda: ctx.subscribe("x.y", lambda event: None),
        lambda: ctx.health_report(True),
        lambda: ctx.secrets,
    ):
        with pytest.raises(SwitchyardError, match="closed"):
            call()


def test_health_report_is_kept(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    ctx, _ = _setup(make_manifest, audit)
    assert ctx.last_health is None
    ctx.health_report(False, "warming up")
    assert ctx.last_health == (False, "warming up")


def test_template_module_runs_on_a_real_context(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    from example import ExampleModule

    ctx, s = _setup(make_manifest, audit, grant=("ui.panel",), module_id="example",
                    panels=["example.status"], log_streams=["example"])  # fmt: skip
    mod = ExampleModule()
    mod.activate(ctx)
    assert mod.health().ok
    assert s.logs.lines[-1][1:3] == ("example", "activated")  # type: ignore[attr-defined]
    mod.deactivate()
    ctx.close()
