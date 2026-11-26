"""1.1 backlog batch 1: secret handling (H1 A-17 #90, A-24 #92)."""

from __future__ import annotations

from typing import Any

import pytest
from sy_testing import ManifestFactory, RecordingAudit

from hermes_signalbox import secrets as secrets_mod
from hermes_signalbox.capabilities import MemoryGrantStore, PolicyEngine
from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.secrets import MASK, MemoryBackend, Redactor, SecretsBroker

VALUE = "plain-" + "4c1d9e7a22-value"  # matches no credential pattern, so only the value list redacts it


def test_a17_memory_backend_needs_the_flag_even_when_pytest_is_loaded() -> None:
    # The old guard was "pytest" in sys.modules: any stub module named pytest opened it.
    with pytest.raises(SignalboxError, match="allow_test_backend"):
        MemoryBackend({"a": "b"})
    assert MemoryBackend({"a": "b"}, allow_test_backend=True).get("a") == "b"


def test_a17_no_sys_modules_guard_remains() -> None:
    assert not hasattr(secrets_mod, "_running_under_pytest")


def test_a24_redactor_keeps_a_bounded_number_of_values() -> None:
    redactor = Redactor()
    limit = secrets_mod.MAX_REDACT_VALUES
    values = [f"value-{i:06d}-padding" for i in range(limit + 10)]
    for v in values:
        redactor.add(v)
    assert len(redactor) == limit
    assert redactor.redact(values[-1]) == MASK  # the most recent are kept
    assert redactor.redact(values[0]) == values[0]  # the oldest are dropped


def test_a24_using_a_value_again_keeps_it() -> None:
    redactor = Redactor()
    limit = secrets_mod.MAX_REDACT_VALUES
    redactor.add(VALUE)
    for i in range(limit - 1):
        redactor.add(f"value-{i:06d}-padding")
    redactor.add(VALUE)  # used again: now the most recent
    redactor.add("one-more-value-padding")
    assert redactor.redact(VALUE) == MASK


def test_a24_removing_a_modules_backend_forgets_its_values(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    policy = PolicyEngine(MemoryGrantStore(), audit)
    policy.register(make_manifest(request=["secrets.read"], secrets=["vault.key"], panels=[]))
    policy.grant("demo", "secrets.read", actor="user")
    redactor = Redactor()
    broker = SecretsBroker([], policy, audit, redactor)
    broker.add_backend("vaultmod", MemoryBackend({"vault.key": VALUE}, name="vault", allow_test_backend=True))
    seen: list[Any] = []
    broker.use("demo", "secret://vault.key", lambda v: seen.append(len(v)))
    assert redactor.redact(f"x {VALUE} y") == f"x {MASK} y"
    broker.remove_backends("vaultmod")
    assert len(redactor) == 0
    assert redactor.redact(VALUE) == VALUE
