"""One hosting process per data directory.

Several Hermes processes (CLI, TUI, gateway) and ``switchyard api serve`` can open the same data directory.
Only the holder of ``<data_dir>/host.lock`` hosts modules (activates them, runs triggers); the others work on
persistent state only. The lock is an OS lock on an open file (``msvcrt.locking`` on Windows, ``fcntl.flock``
elsewhere), so the operating system drops it when the holder exits, even after a crash.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path


class HostLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None
        self._lock = threading.Lock()

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        """Try to take the lock without waiting. Returns True if this object holds it."""
        with self._lock:
            if self._fd is not None:
                return True
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
            try:
                if sys.platform == "win32":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                return False
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode("ascii"))
            self._fd = fd
            return True

    def release(self) -> None:
        with self._lock:
            fd, self._fd = self._fd, None
            if fd is None:
                return
            try:
                if sys.platform == "win32":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


class FileLock:
    """A blocking OS lock on ``path`` for short critical sections shared between processes (the audit log's
    hash chain: R1 review). Waits up to ``timeout`` seconds."""

    def __init__(self, path: Path, timeout: float = 10.0) -> None:
        self.path = path
        self.timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> FileLock:
        import time

        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    os.close(fd)
                    raise TimeoutError(f"could not lock {self.path.name}") from None
                time.sleep(0.01)
        self._fd = fd
        return self

    def __exit__(self, *exc: object) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
