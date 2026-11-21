"""1.1 acceptance security review, spawning: batch files, the child environment and the programs list
(S1-1, S1-2, S1-4, S1-5, S1-7, S1-9)."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pytest
from sy_testing import ManifestFactory, RecordingAudit

from switchyard import process
from switchyard.capabilities import MemoryGrantStore, PolicyEngine
from switchyard.errors import CapabilityDenied, ManifestError, SwitchyardError
from switchyard.process import ProcessBroker


def _broker(
    make_manifest: ManifestFactory, audit: RecordingAudit, programs: list[str] | None
) -> ProcessBroker:
    policy = PolicyEngine(MemoryGrantStore(), audit)
    policy.register(make_manifest("demo", request=["process.spawn"], programs=programs))
    policy.grant("demo", "process.spawn", actor="t")
    return ProcessBroker(policy, audit)


@pytest.fixture
def batch_program(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path]:
    """A ``.cmd`` program on PATH that echoes its arguments, in a directory that is not the cwd."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "syechoargs.cmd").write_text("@echo off\r\necho ARGS=%*\r\n", encoding="ascii")
    monkeypatch.setenv("PATH", f"{bindir}{process.os.pathsep}{process.os.environ.get('PATH', '')}")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return "syechoargs", work


@pytest.mark.skipif(sys.platform != "win32", reason="batch files run through cmd.exe on Windows")
@pytest.mark.parametrize(
    "arg", ["a&echo=INJ", "a|more", "a>out.txt", "a^b", "%PATH%", "a!b", 'a"&echo=Q', "a(b)"]
)
def test_s1_1_cmd_metacharacters_never_reach_a_batch_file(
    make_manifest: ManifestFactory, audit: RecordingAudit, batch_program: tuple[str, Path], arg: str
) -> None:
    name, work = batch_program
    pb = _broker(make_manifest, audit, [name])
    with pytest.raises(SwitchyardError, match="batch file"):
        pb.run("demo", [name, arg])
    assert not (work / "out.txt").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="batch files run through cmd.exe on Windows")
def test_s1_1_plain_arguments_still_reach_a_batch_file(
    make_manifest: ManifestFactory, audit: RecordingAudit, batch_program: tuple[str, Path]
) -> None:
    name, _ = batch_program
    done = _broker(make_manifest, audit, [name]).run("demo", [name, "get", "password", "my-item.1"])
    assert "ARGS=get password my-item.1" in done.stdout


@pytest.mark.parametrize(
    "key", ["PATH", "Path", "PATHEXT", "COMSPEC", "GIT_SSH_COMMAND", "GIT_CONFIG_GLOBAL", "LD_PRELOAD",
            "DYLD_INSERT_LIBRARIES", "PYTHONPATH", "NODE_OPTIONS", "BASH_ENV", "PERL5OPT",
            "npm_config_script_shell", "SSH_ASKPASS", "EDITOR_COMMAND"],
)  # fmt: skip
def test_s1_2_the_caller_cannot_set_variables_that_choose_what_runs(
    make_manifest: ManifestFactory, audit: RecordingAudit, key: str
) -> None:
    pb = _broker(make_manifest, audit, None)
    with pytest.raises(SwitchyardError, match="environment variable"):
        pb.run("demo", [sys.executable, "-c", "pass"], env={key: "x"})


def test_s1_2_ordinary_variables_still_pass(make_manifest: ManifestFactory, audit: RecordingAudit) -> None:
    pb = _broker(make_manifest, audit, None)
    code = "import os; print(os.environ['BW_SESSION'], os.environ['NODE_EXTRA_CA_CERTS'])"
    done = pb.run("demo", [sys.executable, "-c", code], env={"BW_SESSION": "s", "NODE_EXTRA_CA_CERTS": "c"})
    assert done.stdout.split() == ["s", "c"]


def test_s1_4_an_empty_programs_list_allows_no_program(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    pb = _broker(make_manifest, audit, [])
    with pytest.raises(CapabilityDenied, match="may not run"):
        pb.run("demo", ["git", "--version"])


def test_s1_5_non_ascii_program_names_are_refused_when_programs_are_listed(
    make_manifest: ManifestFactory, audit: RecordingAudit
) -> None:
    pb = _broker(make_manifest, audit, ["kernel"])
    with pytest.raises(CapabilityDenied):
        pb.run("demo", ["\u212aernel"])  # KELVIN SIGN lower-cases to ASCII "k"


@pytest.mark.parametrize(
    "shell", ["cmd", "powershell", "pwsh", "bash", "sh", "python", "python3", "node", "env"]
)
def test_s1_7_shells_and_interpreters_cannot_be_listed(make_manifest: ManifestFactory, shell: str) -> None:
    with pytest.raises(ManifestError, match="shell or interpreter"):
        make_manifest("demo", request=["process.spawn"], programs=["bw", shell])


@pytest.mark.skipif(sys.platform != "win32", reason="taskkill is the Windows tree kill")
def test_s1_9_a_skipped_tree_kill_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(process, "system_program", lambda _name: None)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    with caplog.at_level(logging.WARNING, logger="switchyard.process"):
        process._kill_tree(proc)
    assert proc.wait(timeout=10) is not None
    assert any("taskkill" in r.getMessage() for r in caplog.records)
