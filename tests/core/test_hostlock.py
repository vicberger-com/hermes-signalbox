"""Single host process per data directory: OS-level exclusive lock."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from hermes_signalbox.core import Core
from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.hostlock import HostLock


def test_second_holder_is_refused_until_release(tmp_path: Path) -> None:
    first, second = HostLock(tmp_path / "host.lock"), HostLock(tmp_path / "host.lock")
    assert first.acquire() is True
    assert first.acquire() is True  # re-entrant for the holder
    assert second.acquire() is False
    first.release()
    first.release()  # idempotent
    assert second.acquire() is True
    second.release()


def test_lock_is_released_when_the_process_dies(tmp_path: Path) -> None:
    lock_path = tmp_path / "host.lock"
    code = textwrap.dedent(f"""
        from pathlib import Path
        from hermes_signalbox.hostlock import HostLock
        lock = HostLock(Path({str(lock_path)!r}))
        assert lock.acquire()
        print("held", flush=True)
        import os
        os._exit(0)  # no release: the OS must drop the lock
    """)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=True)  # noqa: S603
    assert "held" in out.stdout
    lock = HostLock(lock_path)
    assert lock.acquire() is True
    lock.release()


def test_core_hosting_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)
    data = tmp_path / "data"
    with Core(data_dir=data, hosting=True) as host:
        assert host.hosting
        with pytest.raises(SignalboxError, match="another process"):
            Core(data_dir=data, hosting=True)
        with Core(data_dir=data, hosting=None) as maybe:
            assert not maybe.hosting
        with Core(data_dir=data, hosting=False) as client:
            assert not client.hosting
            assert client.run("module", "list", {}, actor="cli") == []
            with pytest.raises(SignalboxError, match="does not host"):
                client.run("module", "activate", {"id": "x"}, actor="cli")
    with Core(data_dir=data, hosting=None) as later:
        assert later.hosting  # the lock was released on close


def test_h1_d12_file_lock_times_out_on_every_os(tmp_path: Path) -> None:
    import time

    from hermes_signalbox.hostlock import FileLock

    path = tmp_path / "chain.lock"
    with FileLock(path):
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="could not lock"), FileLock(path, timeout=0.2):
            pass
        assert time.monotonic() - started < 5
    with FileLock(path, timeout=0.2):  # released: free again
        pass
