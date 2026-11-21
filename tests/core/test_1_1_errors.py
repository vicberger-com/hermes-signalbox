"""1.1 backlog: error classes say what kind of failure happened (H1 A-31 #97)."""

from __future__ import annotations

from typing import Any

import pytest
from sy_testing import ManifestFactory, RecordingAudit

from switchyard import errors
from switchyard.api import _STATUS_ERRORS, ApiUnavailable
from switchyard.capabilities import MemoryGrantStore, PolicyEngine
from switchyard.context import ContextServices, ModuleContext
from switchyard.errors import CapabilityDenied, NotAvailable, PolicyRefused, SwitchyardError, UsageError
from switchyard.secrets import SecretUnavailable


class _Nothing:
    def __getattr__(self, name: str) -> Any:
        return lambda *a, **k: None


def _ctx(make_manifest: ManifestFactory, audit: RecordingAudit) -> ModuleContext:
    policy = PolicyEngine(MemoryGrantStore(), audit)
    m = make_manifest()
    policy.register(m)
    services = ContextServices(policy=policy, logs=_Nothing(), panels=_Nothing(), bus=_Nothing(), audit=audit)
    return ModuleContext(m, services)


def test_h1_a31_the_three_kinds_exist_under_the_base() -> None:
    for cls in (UsageError, PolicyRefused, NotAvailable):
        assert issubclass(cls, SwitchyardError)
    assert issubclass(CapabilityDenied, PolicyRefused)
    assert issubclass(SecretUnavailable, NotAvailable) and issubclass(ApiUnavailable, NotAvailable)


def test_h1_a31_ops_usage_error_is_the_same_class() -> None:
    from switchyard import ops

    assert ops.UsageError is errors.UsageError


def test_h1_a31_an_undeclared_log_stream_is_a_policy_refusal(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    with pytest.raises(PolicyRefused) as info:
        _ctx(make_manifest, audit).log("undeclared", "x")
    assert not isinstance(info.value, CapabilityDenied)


def test_h1_a31_a_missing_host_service_is_not_available(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    with pytest.raises(NotAvailable):
        _ = _ctx(make_manifest, audit).state


def test_h1_a31_a_missing_update_channel_has_its_own_class() -> None:
    from switchyard.errors import ChannelNotFound, UpdateError

    assert issubclass(ChannelNotFound, UpdateError) and issubclass(ChannelNotFound, NotAvailable)
    import inspect

    from switchyard import updates

    assert '"not found" in str(exc)' not in inspect.getsource(updates)


def test_h1_a31_the_api_client_keeps_the_kind() -> None:
    assert _STATUS_ERRORS[400] is UsageError
    assert _STATUS_ERRORS[503] is NotAvailable
