"""Process broker (``ctx.spawn``): grant required, minimal environment, audit without arguments."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sy_testing import RecordingAudit

from switchyard.capabilities import MemoryGrantStore, PolicyEngine
from switchyard.errors import CapabilityDenied, SwitchyardError
from switchyard.process import ProcessBroker


@pytest.fixture
def broker(make_manifest, audit: RecordingAudit) -> tuple[ProcessBroker, PolicyEngine]:  # type: ignore[no-untyped-def]
    policy = PolicyEngine(MemoryGrantStore(), audit)
    policy.register(make_manifest("demo", request=["process.spawn"]))
    return ProcessBroker(policy, audit), policy


def test_needs_the_grant(broker: tuple[ProcessBroker, PolicyEngine]) -> None:
    pb, _ = broker
    with pytest.raises(CapabilityDenied):
        pb.run("demo", [sys.executable, "-c", "pass"])


def test_runs_with_minimal_env_and_audits_program_only(
    broker: tuple[ProcessBroker, PolicyEngine], audit: RecordingAudit, monkeypatch: pytest.MonkeyPatch
) -> None:
    pb, policy = broker
    policy.grant("demo", "process.spawn", actor="t")
    monkeypatch.setenv("SWITCHYARD_TEST_LEAK", "should-not-pass")
    code = (
        "import os, sys; print(sorted(k for k in os.environ if k.startswith('SWITCHYARD')), sys.stdin.read())"
    )
    argv = [sys.executable, "-c", code, "secret-arg"]
    done = pb.for_module("demo").run(argv, env={"SWITCHYARD_X": "1"}, input="hello")
    assert done.returncode == 0 and "['SWITCHYARD_X'] hello" in done.stdout
    record = audit.records[-1]
    assert record["action"] == "process.spawned" and record["detail"]["result"] == "0"
    assert "secret-arg" not in str(audit.records) and Path(sys.executable).name == record["detail"]["program"]


def test_timeout_missing_program_and_bad_argv(broker: tuple[ProcessBroker, PolicyEngine]) -> None:
    pb, policy = broker
    policy.grant("demo", "process.spawn", actor="t")
    with pytest.raises(SwitchyardError, match="timed out"):
        pb.run("demo", [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2)
    with pytest.raises(SwitchyardError, match="not found"):
        pb.run("demo", ["definitely-not-a-program-xyz"])
    with pytest.raises(SwitchyardError, match="argv"):
        pb.run("demo", [])
