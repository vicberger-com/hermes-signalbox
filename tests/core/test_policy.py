"""Policy engine and capability grants (spec section 3, Policy)."""

from __future__ import annotations

import pytest
from sy_testing import ManifestFactory, RecordingAudit

from switchyard.capabilities import CAPABILITIES, MemoryGrantStore, PolicyEngine
from switchyard.errors import CapabilityDenied, ManifestError
from switchyard.manifest import load_schema


def _engine(audit: RecordingAudit) -> tuple[PolicyEngine, MemoryGrantStore]:
    store = MemoryGrantStore()
    return PolicyEngine(store, audit), store


def test_vocabulary_matches_the_schema() -> None:
    enum = load_schema()["properties"]["capabilities"]["properties"]["request"]["items"]["enum"]
    assert frozenset(enum) == CAPABILITIES


def test_default_deny(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    engine, _ = _engine(audit)
    engine.register(make_manifest())
    assert engine.granted("demo") == frozenset()
    with pytest.raises(CapabilityDenied, match=r"demo.*ui\.panel"):
        engine.require("demo", "ui.panel", panel="demo.status")
    assert audit.records[-1] == {
        "actor": "core",
        "action": "policy.denied",
        "module": "demo",
        "detail": {"capability": "ui.panel", "panel": "demo.status"},
    }


def test_grant_then_require(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    engine, store = _engine(audit)
    engine.register(make_manifest())
    engine.grant("demo", "ui.panel", actor="user")
    assert engine.granted("demo") == frozenset({"ui.panel"})
    assert store.load("demo") == frozenset({"ui.panel"})
    n = len(audit.records)
    engine.require("demo", "ui.panel")
    assert len(audit.records) == n  # allowed checks are not audited
    assert audit.records[-1]["action"] == "policy.granted"
    assert audit.records[-1]["actor"] == "user"


def test_unrequested_capability_cannot_be_granted(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    engine, store = _engine(audit)
    engine.register(make_manifest())
    with pytest.raises(CapabilityDenied, match="not requested"):
        engine.grant("demo", "process.spawn", actor="user")
    assert store.load("demo") == frozenset()
    assert audit.actions()[-1] == "policy.grant_refused"


def test_unknown_capability_cannot_be_granted(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    engine, _ = _engine(audit)
    engine.register(make_manifest())
    with pytest.raises(CapabilityDenied, match="unknown capability"):
        engine.grant("demo", "root.everything", actor="user")


def test_unregistered_module_is_denied(audit: RecordingAudit) -> None:
    engine, _ = _engine(audit)
    with pytest.raises(CapabilityDenied, match="not registered"):
        engine.grant("ghost", "ui.panel", actor="user")
    with pytest.raises(CapabilityDenied):
        engine.require("ghost", "ui.panel")
    assert engine.granted("ghost") == frozenset()


def test_revoke(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    engine, _ = _engine(audit)
    engine.register(make_manifest())
    engine.grant("demo", "ui.panel", actor="user")
    engine.revoke("demo", "ui.panel", actor="user")
    assert audit.actions()[-1] == "policy.revoked"
    with pytest.raises(CapabilityDenied):
        engine.require("demo", "ui.panel")
    n = len(audit.records)
    engine.revoke("demo", "ui.panel", actor="user")  # no-op, not audited
    assert len(audit.records) == n


def test_own_policy_can_only_tighten(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    engine, store = _engine(audit)
    m = make_manifest(request=["ui.panel", "net.outbound"], net_hosts=["api.example.com"],
                      policies=["deny:net.outbound"])  # fmt: skip
    engine.register(m)
    with pytest.raises(CapabilityDenied, match="module policy"):
        engine.grant("demo", "net.outbound", actor="user")
    store.add("demo", "net.outbound")  # even a stored grant is ignored
    assert "net.outbound" not in engine.granted("demo")


@pytest.mark.parametrize("policy", ["allow:net.outbound", "deny:root.everything", "deny", "nonsense"])
def test_unknown_policy_rejected(make_manifest: ManifestFactory, audit: RecordingAudit, policy: str) -> None:
    engine, _ = _engine(audit)
    with pytest.raises(ManifestError, match="policy"):
        engine.register(make_manifest(policies=[policy]))


def test_stale_grant_removed_when_manifest_drops_request(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    engine, store = _engine(audit)
    engine.register(make_manifest(request=["ui.panel", "schedule"]))
    engine.grant("demo", "schedule", actor="user")
    engine.register(make_manifest(request=["ui.panel"]))  # updated manifest no longer requests it
    assert store.load("demo") == frozenset()  # H1 A-6: removed, not just hidden
    engine.register(make_manifest(request=["ui.panel", "schedule"]))
    assert engine.granted("demo") == frozenset()  # asking again needs a new grant


def test_unregister_drops_grants(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    engine, store = _engine(audit)
    engine.register(make_manifest())
    engine.grant("demo", "ui.panel", actor="user")
    engine.unregister("demo", actor="user")
    assert store.load("demo") == frozenset()
    assert audit.actions()[-1] == "policy.grants_removed"
    with pytest.raises(CapabilityDenied):
        engine.require("demo", "ui.panel")


def test_unregister_can_keep_grants(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    engine, store = _engine(audit)
    engine.register(make_manifest())
    engine.grant("demo", "ui.panel", actor="user")
    engine.unregister("demo", actor="user", keep_grants=True)
    assert store.load("demo") == frozenset({"ui.panel"})


def test_net_host_allow_list(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    engine, _ = _engine(audit)
    engine.register(make_manifest(request=["net.outbound"], net_hosts=["api.example.com"], panels=[]))
    engine.grant("demo", "net.outbound", actor="user")
    engine.require_host("demo", "api.example.com")
    engine.require_host("demo", "API.Example.com")  # hosts compare case-insensitively
    with pytest.raises(CapabilityDenied, match=r"evil\.example\.net"):
        engine.require_host("demo", "evil.example.net")
    assert audit.records[-1]["detail"] == {"capability": "net.outbound", "host": "evil.example.net"}


def test_secret_name_allow_list(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    engine, _ = _engine(audit)
    engine.register(make_manifest(request=["secrets.read"], secrets=["provider.key"], panels=[]))
    engine.grant("demo", "secrets.read", actor="user")
    engine.require_secret("demo", "provider.key")
    with pytest.raises(CapabilityDenied, match=r"other\.key"):
        engine.require_secret("demo", "other.key")
