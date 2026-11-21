"""1.1 backlog batch 11: module audit entries keep long names apart and mark cut values (H1 A-27 #94)."""

from __future__ import annotations

from typing import Any

from sy_testing import ManifestFactory, RecordingAudit

from switchyard.capabilities import MemoryGrantStore, PolicyEngine
from switchyard.context import ContextServices, ModuleContext


class _Nothing:
    """Logs, panels and bus are not used by ctx.audit."""

    def __getattr__(self, name: str) -> Any:
        return lambda *a, **k: None


def _ctx(make_manifest: ManifestFactory, audit: RecordingAudit) -> ModuleContext:
    policy = PolicyEngine(MemoryGrantStore(), audit)
    m = make_manifest()
    policy.register(m)
    services = ContextServices(policy=policy, logs=_Nothing(), panels=_Nothing(), bus=_Nothing(), audit=audit)
    return ModuleContext(m, services)


def test_h1_a27_long_field_names_stay_distinct(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    ctx = _ctx(make_manifest, audit)
    a, b = "k" * 64 + "_first", "k" * 64 + "_second"
    ctx.audit("noted", **{a: "1", b: "2"})
    detail = audit.records[-1]["detail"]
    assert len(detail) == 2 and sorted(detail.values()) == ["1", "2"]
    assert all(len(k) <= 64 for k in detail)


def test_h1_a27_cut_values_are_marked(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    ctx = _ctx(make_manifest, audit)
    ctx.audit("noted", short="ok", long="v" * 1000)
    detail = audit.records[-1]["detail"]
    assert detail["short"] == "ok"
    assert len(detail["long"]) <= 256 and detail["long"].endswith("[truncated]")
