"""``fs.read`` broker (ADR-0003)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from sy_testing import RecordingAudit

from switchyard.capabilities import MemoryGrantStore, PolicyEngine
from switchyard.errors import CapabilityDenied, SwitchyardError
from switchyard.fsread import CEILING_BYTES, FsBroker


@pytest.fixture
def fs(make_manifest, audit: RecordingAudit) -> tuple[FsBroker, PolicyEngine]:  # type: ignore[no-untyped-def]
    policy = PolicyEngine(MemoryGrantStore(), audit)
    policy.register(make_manifest("demo", request=["fs.read"]))
    return FsBroker(policy, audit), policy


def test_needs_the_grant_even_for_missing_files(fs: tuple[FsBroker, PolicyEngine], tmp_path: Path) -> None:
    broker, _ = fs
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    with pytest.raises(CapabilityDenied):
        broker.read_text("demo", tmp_path / "a.txt")
    with pytest.raises(CapabilityDenied):
        broker.read_text("demo", tmp_path / "missing.txt")


def test_reads_and_audits_path_not_content(
    fs: tuple[FsBroker, PolicyEngine], tmp_path: Path, audit: RecordingAudit
) -> None:
    broker, policy = fs
    policy.grant("demo", "fs.read", actor="t")
    (tmp_path / "c.json").write_text(json.dumps({"k": "content-marker"}), encoding="utf-8")
    module = broker.for_module("demo")
    assert module.read_json(tmp_path / "c.json") == {"k": "content-marker"}
    assert module.read_text(str(tmp_path / "c.json")).startswith("{")
    record = audit.records[-1]
    assert record["action"] == "fs.read" and record["detail"]["path"].endswith("c.json")
    assert "content-marker" not in str(audit.records)


def test_rules(fs: tuple[FsBroker, PolicyEngine], tmp_path: Path) -> None:
    broker, policy = fs
    policy.grant("demo", "fs.read", actor="t")
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * 2048)
    with pytest.raises(SwitchyardError, match="absolute"):
        broker.read_text("demo", "relative.txt")
    with pytest.raises(SwitchyardError, match="larger"):
        broker.read_text("demo", big, max_bytes=1024)
    for bad in (0, -1, CEILING_BYTES + 1, True):
        with pytest.raises(SwitchyardError, match="max_bytes"):
            broker.read_text("demo", big, max_bytes=bad)
    with pytest.raises(SwitchyardError, match="regular file"):
        broker.read_text("demo", tmp_path)
    with pytest.raises(SwitchyardError, match="not found"):
        broker.read_text("demo", tmp_path / "missing")
    (tmp_path / "bin").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(SwitchyardError, match="UTF-8"):
        broker.read_text("demo", tmp_path / "bin")
    (tmp_path / "bad.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(SwitchyardError, match="valid JSON"):
        broker.read_json("demo", tmp_path / "bad.json")
    (tmp_path / "deep.json").write_text("[" * 70 + "]" * 70, encoding="utf-8")
    with pytest.raises(SwitchyardError, match="nesting"):
        broker.read_json("demo", tmp_path / "deep.json")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX device file")
def test_device_files_are_refused(fs: tuple[FsBroker, PolicyEngine]) -> None:
    broker, policy = fs
    policy.grant("demo", "fs.read", actor="t")
    with pytest.raises(SwitchyardError, match="regular file"):
        broker.read_text("demo", os.devnull)
