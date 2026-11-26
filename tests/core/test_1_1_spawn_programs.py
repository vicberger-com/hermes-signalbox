"""1.1 backlog: a module may declare which programs process.spawn runs (H1 B-10 #103)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sy_testing import ManifestFactory, RecordingAudit

from hermes_signalbox.capabilities import MemoryGrantStore, PolicyEngine
from hermes_signalbox.errors import CapabilityDenied, ManifestError, SignalboxError
from hermes_signalbox.manifest import load_manifest
from hermes_signalbox.process import ProcessBroker

BUNDLED = Path(__file__).resolve().parents[2] / "src" / "hermes_signalbox" / "modules"


def _broker(
    make_manifest: ManifestFactory, audit: RecordingAudit, programs: list[str] | None
) -> ProcessBroker:
    policy = PolicyEngine(MemoryGrantStore(), audit)
    policy.register(make_manifest("demo", request=["process.spawn"], programs=programs))
    policy.grant("demo", "process.spawn", actor="t")
    return ProcessBroker(policy, audit)


def test_h1_b10_an_unlisted_program_is_denied_and_audited(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    pb = _broker(make_manifest, audit, ["bw"])
    with pytest.raises(CapabilityDenied, match="may not run"):
        pb.run("demo", ["cmd.exe", "/c", "echo"])
    denied = [r for r in audit.records if r["action"] == "policy.denied"]
    assert denied and denied[-1]["detail"]["program"] == "cmd.exe"


def test_h1_b10_a_listed_program_passes_the_policy(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    pb = _broker(make_manifest, audit, ["signalbox-no-such-program"])
    with pytest.raises(SignalboxError, match="not found") as info:  # past the policy: the PATH lookup fails
        pb.run("demo", ["signalbox-no-such-program"])
    assert not isinstance(info.value, CapabilityDenied)


def test_h1_b10_a_path_in_argv0_is_refused_when_programs_are_listed(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    pb = _broker(make_manifest, audit, ["signalbox-demo"])
    with pytest.raises(CapabilityDenied, match="bare program name"):
        pb.run("demo", [str(Path(sys.executable).parent / "signalbox-demo.exe"), "-c", "pass"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows program names ignore case and .exe")
def test_h1_b10_windows_names_ignore_case_and_extension(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    pb = _broker(make_manifest, audit, ["signalbox-no-such-program"])
    with pytest.raises(SignalboxError, match="not found"):
        pb.run("demo", ["SignalBox-No-Such-Program.EXE"])


def test_h1_b10_without_a_list_any_program_still_runs(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    pb = _broker(make_manifest, audit, None)
    assert pb.run("demo", [sys.executable, "-c", "pass"]).returncode == 0


def test_h1_b10_programs_need_process_spawn(make_manifest: ManifestFactory) -> None:
    with pytest.raises(ManifestError, match=r"'programs' needs 'process\.spawn'"):
        make_manifest("demo", request=["ui.panel"], programs=["bw"])


def test_h1_b10_bundled_spawning_modules_list_their_programs() -> None:
    assert set(load_manifest(BUNDLED / "offload").programs) == {"claude", "codex"}
    scanners = {"gitleaks", "bandit", "pip-audit", "osv-scanner", "semgrep", "trivy"}
    assert set(load_manifest(BUNDLED / "scanner").programs) == scanners
    assert set(load_manifest(BUNDLED / "secrets").programs) == {"bw", "secret-tool", "security"}
    spawning = [
        d.name
        for d in BUNDLED.iterdir()
        if (d / "module.toml").is_file() and "process.spawn" in load_manifest(d).requested
    ]
    assert all(load_manifest(BUNDLED / name).programs for name in spawning), spawning


def test_h1_b10_an_update_that_adds_a_program_widens(make_manifest: ManifestFactory, tmp_path: Path) -> None:
    from hermes_signalbox.sbom import sbom_delta

    old = make_manifest("demo", request=["process.spawn"], programs=["bw"])
    new = make_manifest("demo", request=["process.spawn"], programs=["bw", "curl"])
    delta = sbom_delta(old.directory, new.directory, old, new)
    assert any(w.startswith("programs: curl") for w in delta["widens"])
