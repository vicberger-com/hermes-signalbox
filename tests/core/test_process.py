"""Process broker (``ctx.spawn``): grant required, minimal environment, audit without arguments."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sy_testing import RecordingAudit

from hermes_signalbox.capabilities import MemoryGrantStore, PolicyEngine
from hermes_signalbox.errors import CapabilityDenied, SignalboxError
from hermes_signalbox.process import ProcessBroker


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
    monkeypatch.setenv("SIGNALBOX_TEST_LEAK", "should-not-pass")
    code = (
        "import os, sys; print(sorted(k for k in os.environ if k.startswith('SIGNALBOX')), sys.stdin.read())"
    )
    argv = [sys.executable, "-c", code, "secret-arg"]
    done = pb.for_module("demo").run(argv, env={"SIGNALBOX_X": "1"}, input="hello")
    assert done.returncode == 0 and "['SIGNALBOX_X'] hello" in done.stdout
    record = audit.records[-1]
    assert record["action"] == "process.spawned" and record["detail"]["result"] == "0"
    assert "secret-arg" not in str(audit.records) and Path(sys.executable).name == record["detail"]["program"]


def test_timeout_missing_program_and_bad_argv(broker: tuple[ProcessBroker, PolicyEngine]) -> None:
    pb, policy = broker
    policy.grant("demo", "process.spawn", actor="t")
    with pytest.raises(SignalboxError, match="timed out"):
        pb.run("demo", [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2)
    with pytest.raises(SignalboxError, match="not found"):
        pb.run("demo", ["definitely-not-a-program-xyz"])
    with pytest.raises(SignalboxError, match="argv"):
        pb.run("demo", [])


def test_helper_planted_in_the_working_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hermes_signalbox.process import find_program

    name = "planted-helper-xyz"
    script = tmp_path / (name + (".cmd" if sys.platform == "win32" else ""))
    script.write_text("@echo off\n" if sys.platform == "win32" else "#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    assert find_program(name) is None  # in the working directory, even when PATH lists it
    assert find_program(sys.executable) is not None
    assert find_program("definitely-not-a-program-xyz") is None


# H1 WP4: program resolution (findings D-2, D-15) ----------------------------------------------------------


def _fake_program(directory: Path, name: str, works: bool) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        path = directory / f"{name}.cmd"
        path.write_text(
            "@echo off\r\n" + ("echo fake 1.0\r\n" if works else "exit /b 5\r\n"), encoding="utf-8"
        )
    else:
        path = directory / name
        path.write_text("#!/bin/sh\n" + ("echo fake 1.0\n" if works else "exit 5\n"), encoding="utf-8")
        path.chmod(0o755)
    return path


def test_h1_d2_first_runnable_candidate_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hermes_signalbox.process import find_runnable, program_candidates

    name = "sy-fake-tool"
    broken = _fake_program(tmp_path / "a", name, works=False)
    good = _fake_program(tmp_path / "b", name, works=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join([str(tmp_path / "a"), "relative-dir", str(tmp_path / "b")]))
    found = program_candidates(name)
    assert [Path(p).resolve() for p in found] == [broken.resolve(), good.resolve()]
    assert Path(find_runnable(name) or "").resolve() == good.resolve()
    assert find_runnable(name, configured=str(broken)) is None  # a configured path is never second-guessed
    assert Path(find_runnable(name, configured=str(good)) or "").resolve() == good.resolve()
    assert find_runnable(name, configured="relative/tool") is None
    monkeypatch.setenv("PATH", str(tmp_path / "a"))
    assert find_runnable(name) is None


def test_h1_d15_working_directory_hit_from_path_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from hermes_signalbox import process

    planted = _fake_program(tmp_path, "sy-planted", works=True)
    monkeypatch.chdir(tmp_path)
    # shutil.which returns an absolute path inside the working directory (PATH lists it): still refused
    monkeypatch.setattr(shutil, "which", lambda name, path=None: str(planted.resolve()))
    assert process.find_program("sy-planted") is None
    assert process.program_candidates("sy-planted") == []


def test_h1_d2_git_resolves_and_runs_here() -> None:
    """On a machine with any runnable git (every CI runner, and this workstation with Git for Windows behind
    the Hermes Desktop copy), the updates path finds it."""
    from hermes_signalbox.updates import git_usable, resolved_git

    assert git_usable() is True
    assert resolved_git() is not None


def test_h1_b3_deadline_covers_stdin_and_every_failure_is_recorded(
    broker: tuple[ProcessBroker, PolicyEngine], audit: RecordingAudit
) -> None:
    import time

    pb, policy = broker
    policy.grant("demo", "process.spawn", actor="t")
    code = "import time; time.sleep(30)"  # never reads its stdin
    start = time.monotonic()
    with pytest.raises(SignalboxError, match="timed out"):
        pb.run("demo", [sys.executable, "-c", code], input="x" * 900_000, timeout=1.0)
    assert time.monotonic() - start < 6
    assert audit.records[-1]["detail"] == {"program": Path(sys.executable).name, "result": "timeout"}
    with pytest.raises(SignalboxError, match="input"):
        pb.run("demo", [sys.executable, "-c", "pass"], input="x" * 1_000_001)
    done = pb.run("demo", [sys.executable, "-c", "import sys; print(len(sys.stdin.read()))"], input="abc")
    assert done.stdout.strip() == "3"
