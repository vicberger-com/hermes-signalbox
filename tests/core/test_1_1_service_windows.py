"""1.1 S-7: running the daemon from Task Scheduler.

Task Scheduler starts programs in ``C:\\Windows\\System32``. ``shutil.which`` then finds ``icacls`` as
``.\\icacls.EXE`` in the working directory, ``find_program`` refuses it (H1 D-15), the API token could not be
restricted, and ``hermes-signalbox api serve`` died with a traceback. Windows system tools now come from
``%SystemRoot%\\System32`` directly, and a start failure is a clean error.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from hermes_signalbox import api, process
from hermes_signalbox.errors import SignalboxError


@pytest.fixture
def system32(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake Windows directory that is also the working directory and on PATH, as under Task Scheduler."""
    root = tmp_path / "Windows"
    s32 = root / "System32"
    s32.mkdir(parents=True)
    for name in ("icacls.exe", "taskkill.exe"):
        (s32 / name).write_bytes(b"")
    monkeypatch.setenv("SYSTEMROOT", str(root))
    monkeypatch.setenv("PATH", str(s32))
    monkeypatch.chdir(s32)
    return s32


def test_system_program_resolves_from_system_root_even_as_working_directory(system32: Path) -> None:
    found = process.system_program("icacls")
    assert found is not None and Path(found) == system32 / "icacls.exe"
    assert process.find_program("icacls") is None  # PATH lookup still refuses the working directory


def test_system_program_is_none_without_system_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SYSTEMROOT", raising=False)
    assert process.system_program("icacls") is None


def test_token_acl_uses_the_system_icacls(
    system32: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    token = tmp_path / "api.token"
    token.write_text("x", encoding="utf-8")
    api._restrict_windows_acl(token)
    assert calls and Path(calls[0][0]) == system32 / "icacls.exe"
    assert token.exists()


def test_kill_tree_uses_the_system_taskkill(system32: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(process.sys, "platform", "win32")
    monkeypatch.setattr(
        subprocess, "run", lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0)
    )
    proc = type("P", (), {"pid": 4242, "kill": lambda self: None, "wait": lambda self, timeout=None: 0})()
    process._kill_tree(proc)  # type: ignore[arg-type]
    assert calls and Path(calls[0][0]) == system32 / "taskkill.exe" and "4242" in calls[0]


def test_serve_start_failure_is_a_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from hermes_signalbox import cli

    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)

    def refuse(self: Any) -> None:
        raise SignalboxError("could not restrict access to api.token: OSError")

    monkeypatch.setattr(api.ControlServer, "start", refuse)
    code = cli.main(["--data-dir", str(tmp_path / "data"), "api", "serve"])
    assert code == 1
    assert "error: could not restrict access to api.token" in capsys.readouterr().err
