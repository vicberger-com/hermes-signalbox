"""Secrets broker interface, test backend and redactor (spec section 3, Secrets broker)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sy_testing import ManifestFactory, RecordingAudit

from switchyard import secrets as secrets_mod
from switchyard.audit import AuditLog
from switchyard.capabilities import MemoryGrantStore, PolicyEngine
from switchyard.context import ContextServices, MemoryPanelRegistry, ModuleContext
from switchyard.errors import CapabilityDenied, SwitchyardError
from switchyard.events import EventBus
from switchyard.logs import JsonlLogSink
from switchyard.secrets import (
    MemoryBackend,
    Redactor,
    SecretLeak,
    SecretRef,
    SecretsBroker,
    SecretUnavailable,
)

CANARY = "canary-" + "7f3a9c2e1b-value"


class LockedBackend:
    name = "locked"

    def available(self) -> bool:
        return False

    def get(self, name: str) -> str:
        raise AssertionError("must not be called while locked")


def _setup(
    make_manifest: ManifestFactory, audit: Any, *, grant: bool = True, backends: Any = None
) -> tuple[SecretsBroker, PolicyEngine, Redactor]:
    policy = PolicyEngine(MemoryGrantStore(), audit)
    policy.register(make_manifest(request=["secrets.read"], secrets=["provider.key"], panels=[]))
    if grant:
        policy.grant("demo", "secrets.read", actor="user")
    redactor = Redactor()
    if backends is None:
        backends = [MemoryBackend({"provider.key": CANARY, "other.key": "other-" + "000000-value"})]
    return SecretsBroker(backends, policy, audit, redactor), policy, redactor


# refs -----------------------------------------------------------------------------------------------------


def test_secret_ref_parsing() -> None:
    assert SecretRef.parse("secret://provider.key").name == "provider.key"
    assert str(SecretRef("a_b")) == "secret://a_b"
    for bad in (
        "provider.key",
        "secret://",
        "secret://UPPER",
        "secret://a/b",
        "https://x",
        "secret://" + "a" * 70,
    ):
        with pytest.raises(SwitchyardError, match="secret"):
            SecretRef.parse(bad)


# broker ---------------------------------------------------------------------------------------------------


def test_use_passes_the_value_and_returns_only_the_result(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    broker, _, redactor = _setup(make_manifest, audit)
    result = broker.use("demo", "secret://provider.key", lambda v: {"status": 200, "length": len(v)})
    assert result == {"status": 200, "length": len(CANARY)}
    rec = audit.records[-1]
    assert rec["action"] == "secret.used" and rec["detail"] == {"secret": "provider.key", "backend": "memory"}
    assert redactor.redact(f"leaked {CANARY}!") == "leaked [REDACTED]!"


def test_result_containing_the_value_is_blocked(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    broker, _, _ = _setup(make_manifest, audit)
    for leak in (lambda v: v, lambda v: {"echo": [v]}, lambda v: f"Bearer {v}", lambda v: v.encode()):
        with pytest.raises(SecretLeak) as info:
            broker.use("demo", "secret://provider.key", leak)
        assert CANARY not in str(info.value)
    assert audit.actions().count("secret.leak_blocked") == 4


def test_exception_messages_from_fn_are_dropped(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    broker, _, _ = _setup(make_manifest, audit)

    def boom(v: str) -> None:
        raise RuntimeError(f"upstream rejected key {v}")

    with pytest.raises(SwitchyardError) as info:
        broker.use("demo", "secret://provider.key", boom)
    assert CANARY not in str(info.value) and "RuntimeError" in str(info.value)
    assert info.value.__cause__ is None and info.value.__context__ is None
    frames = []
    tb = info.value.__traceback__
    while tb is not None:
        frames.append(tb.tb_frame)
        tb = tb.tb_next
    assert all(CANARY not in repr(v) for f in frames for v in f.f_locals.values())


def test_leak_traceback_holds_no_value(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    broker, _, _ = _setup(make_manifest, audit)
    with pytest.raises(SecretLeak) as info:
        broker.use("demo", "secret://provider.key", lambda v: v)
    tb = info.value.__traceback__
    while tb is not None:
        assert all(CANARY not in repr(v) for v in tb.tb_frame.f_locals.values())
        tb = tb.tb_next


def test_policy_is_checked_first(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    broker, _, _ = _setup(make_manifest, audit, grant=False)
    with pytest.raises(CapabilityDenied):
        broker.use("demo", "secret://provider.key", len)
    broker, _, _ = _setup(make_manifest, audit)
    with pytest.raises(CapabilityDenied, match=r"other\.key"):
        broker.use("demo", "secret://other.key", len)  # exists in the backend but not declared by the module


def test_locked_or_missing_backends_fail_closed(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    broker, _, _ = _setup(make_manifest, audit, backends=[LockedBackend()])
    with pytest.raises(SecretUnavailable, match=r"provider\.key"):
        broker.use("demo", "secret://provider.key", len)
    broker, _, _ = _setup(make_manifest, audit, backends=[MemoryBackend({})])
    with pytest.raises(SecretUnavailable):
        broker.use("demo", "secret://provider.key", len)
    assert audit.actions()[-1] == "secret.unavailable"


def test_first_available_backend_wins(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    backends = [
        LockedBackend(),
        MemoryBackend({}, name="empty"),
        MemoryBackend({"provider.key": CANARY}, name="b3"),
    ]
    broker, _, _ = _setup(make_manifest, audit, backends=backends)
    assert broker.use("demo", "secret://provider.key", len) == len(CANARY)
    assert audit.records[-1]["detail"]["backend"] == "b3"


def test_memory_backend_refuses_outside_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secrets_mod, "_running_under_pytest", lambda: False)
    with pytest.raises(SwitchyardError, match="test"):
        MemoryBackend({"a": "b"})
    assert MemoryBackend({"a": "b"}, allow_test_backend=True).get("a") == "b"


def test_memory_backend_lists_names_only() -> None:
    backend = MemoryBackend({"b.key": "x", "a.key": "y"})
    assert backend.names() == ["a.key", "b.key"] and backend.available()
    with pytest.raises(KeyError):
        backend.get("missing")


# redactor -------------------------------------------------------------------------------------------------


def test_redactor_registered_values_longest_first() -> None:
    r = Redactor()
    r.add("abcd1234")
    r.add("abcd1234-extended")
    assert r.redact("x abcd1234-extended y abcd1234") == "x [REDACTED] y [REDACTED]"
    r.add("")  # ignored
    r.add("abc")  # too short to redact safely; ignored
    assert r.redact("abc") == "abc"


# Token-shaped fixtures are assembled at runtime so no credential-like literal exists in the repository
# (the secret scanner runs on the full history).
_ALNUM = "abcdefghijklmnopqrstuvwxyz0123456789"
_SHAPED = [
    "key " + "sk-" + "proj-" + _ALNUM[:24],
    "token " + "gh" + "p_" + _ALNUM,
    "pat " + "github" + "_pat_" + "11" + _ALNUM.upper()[:20] + "_" + _ALNUM,
    "aws " + "AK" + "IA" + _ALNUM.upper()[:16],
    "slack " + "xo" + "xb-" + "123456789012-" + _ALNUM[:10],
    "Authorization: " + "Bearer " + "abc.def." + _ALNUM[:16],
    "anthropic " + "sk-" + "ant-api03-" + _ALNUM[:26],
]


@pytest.mark.parametrize("text", _SHAPED)
def test_redactor_default_patterns(text: str) -> None:
    out = Redactor().redact(text)
    assert "[REDACTED]" in out and out != text


def test_redact_obj_walks_structures() -> None:
    r = Redactor()
    r.add(CANARY)
    out = r.redact_obj({"a": [CANARY, {"b": f"x{CANARY}"}], "n": 1})
    assert CANARY not in json.dumps(out) and out["n"] == 1


# end to end: the canary never reaches any output -----------------------------------------------------------


def test_canary_never_in_any_output(tmp_path: Path, make_manifest: ManifestFactory) -> None:
    redactor = Redactor()
    audit = AuditLog(tmp_path / "audit", redact=redactor.redact)
    logs = JsonlLogSink(tmp_path / "logs", redact=redactor.redact)
    policy = PolicyEngine(MemoryGrantStore(), audit)
    manifest = make_manifest(request=["secrets.read"], secrets=["provider.key"], panels=[])
    policy.register(manifest)
    policy.grant("demo", "secrets.read", actor="user")
    broker = SecretsBroker([MemoryBackend({"provider.key": CANARY})], policy, audit, redactor)
    services = ContextServices(policy=policy, logs=logs, panels=MemoryPanelRegistry(), bus=EventBus(audit),
                               brokers={"secrets.read": broker})  # fmt: skip
    ctx = ModuleContext(manifest, services)
    facade = ctx.secrets
    status = facade.use("secret://provider.key", lambda v: "ok" if v else "missing")  # type: ignore[attr-defined]
    assert status == "ok"
    ctx.log("demo", "called", note=f"the key was {CANARY}")  # a careless module
    with pytest.raises(SwitchyardError) as info:
        facade.use("secret://provider.key", lambda v: v)  # type: ignore[attr-defined]
    everything = "".join(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.jsonl")) + str(info.value)
    assert CANARY not in everything
    assert "[REDACTED]" in everything
    assert audit.verify().ok
