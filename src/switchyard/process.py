"""Process broker: the ``process.spawn`` capability (``ctx.spawn``).

``ctx.spawn.run(argv, ...)`` starts a helper program for a module that was granted ``process.spawn``. The
child gets a minimal environment (an allow-list plus what the caller passes explicitly), stdin from the null
device unless ``input`` is given, a timeout, and no shell. Each run is audited with the program's base name
and exit code only; arguments, input and output are never recorded, because they can carry secret names or
values.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess  # nosec B404
import sys
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from switchyard.capabilities import AuditSink, PolicyEngine
from switchyard.errors import SwitchyardError

BASE_ENV = (
    "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA",
    "LOCALAPPDATA", "LANG", "LC_ALL", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
)  # fmt: skip
DEFAULT_TIMEOUT_S = 30.0
MAX_TIMEOUT_S = 600.0
DEFAULT_MAX_OUTPUT = 10_000_000
MAX_OUTPUT_BYTES = 50_000_000
MAX_INPUT_BYTES = 1_000_000  # H1 B-3


def _read_capped(handle: Any, limit: int) -> tuple[str, bool]:
    handle.seek(0)
    data = handle.read(limit + 1)
    return data[:limit].decode("utf-8", errors="replace"), len(data) > limit


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Kill the child and everything it started."""
    try:
        if sys.platform == "win32":
            killer = find_program("taskkill")
            if killer is not None:
                argv = [killer, "/T", "/F", "/PID", str(proc.pid)]
                subprocess.run(argv, capture_output=True, timeout=10, check=False)  # noqa: S603 # nosec B603
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
        proc.wait(timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def find_program(name: str) -> str | None:
    """Absolute path of ``name`` from PATH, never from the working directory.

    On Windows ``shutil.which`` looks in the current directory first, so a ``bw.cmd`` planted in a folder the
    user starts from would be chosen over the real one. Results that are relative or live in the working
    directory are refused.
    """
    exe = shutil.which(name)
    if exe is None or not os.path.isabs(exe) or not _outside_cwd(exe):
        return None
    return exe


def _outside_cwd(exe: str) -> bool:
    try:
        return Path(exe).resolve().parent != Path.cwd().resolve()
    except OSError:
        return False


def program_candidates(name: str) -> list[str]:
    """Every absolute ``name`` on PATH, in PATH order, minus anything in the working directory (H1 D-2)."""
    out: list[str] = []
    seen: set[str] = set()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            continue  # relative PATH entries resolve against the working directory
        exe = shutil.which(name, path=entry)
        if exe is None or not os.path.isabs(exe) or not _outside_cwd(exe):
            continue
        key = os.path.normcase(os.path.realpath(exe))
        if key not in seen:
            seen.add(key)
            out.append(exe)
    return out


def _runs(exe: str, probe: Sequence[str], timeout: float) -> bool:
    try:
        # Fixed argv from an absolute path; no shell.
        subprocess.run([exe, *probe], capture_output=True, timeout=timeout, check=True)  # noqa: S603 # nosec B603
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def find_runnable(
    name: str, *, configured: str | None = None, probe: Sequence[str] = ("--version",), timeout: float = 30.0
) -> str | None:
    """The first ``name`` on PATH that this process can actually run (H1 D-2: on Windows, Hermes Desktop
    puts a packaged git first on PATH that other processes may not execute). ``configured`` (an absolute path
    from the core settings) is used alone: if it does not run, the answer is ``None``, never another
    program."""
    if configured is not None:
        if not os.path.isabs(configured) or not os.path.isfile(configured):
            return None
        return configured if _runs(configured, probe, timeout) else None
    for exe in program_candidates(name):
        if _runs(exe, probe, timeout):
            return exe
    return None


def _feed(stdin: Any, data: bytes) -> None:
    """Write a child's input and close the pipe. A child that exits or closes its end early is not an error
    here; its exit code says what happened."""
    try:
        stdin.write(data)
    except OSError:
        pass
    finally:
        with contextlib.suppress(OSError):
            stdin.close()


class ProcessBroker:
    def __init__(self, policy: PolicyEngine, audit: AuditSink) -> None:
        self._policy = policy
        self._audit = audit

    def run(
        self,
        module_id: str,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        input: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        max_output: int = DEFAULT_MAX_OUTPUT,
        cwd: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if not argv or not all(isinstance(a, str) for a in argv):
            raise SwitchyardError("argv must be a non-empty list of strings")
        data = input.encode("utf-8") if input is not None else None
        if data is not None and len(data) > MAX_INPUT_BYTES:
            raise SwitchyardError(f"input is larger than {MAX_INPUT_BYTES} bytes")
        program = Path(argv[0]).name
        self._policy.require(module_id, "process.spawn", program=program)
        exe = find_program(argv[0])
        if exe is None:
            raise SwitchyardError(f"program {program!r} not found")
        child_env = {k: v for k in BASE_ENV if (v := os.environ.get(k)) is not None}
        child_env.update(env or {})
        child_env["NO_COLOR"] = "1"
        limit = min(max(int(max_output), 1), MAX_OUTPUT_BYTES)
        # Output goes to temporary files, not pipes (M10 review): on Windows a grandchild holding a pipe kept
        # ``subprocess.run`` from returning long after its timeout, and pipes are read whole into memory. On
        # timeout the whole process tree is killed. Output is decoded leniently and capped at ``max_output``.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                proc = subprocess.Popen(  # noqa: S603 # nosec B603 - an argv list and no shell
                    [exe, *argv[1:]],
                    env=child_env,
                    stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    cwd=cwd,
                    start_new_session=os.name != "nt",
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    if os.name == "nt"
                    else 0,
                )
            except OSError as exc:
                self._record(module_id, program, type(exc).__name__)
                raise SwitchyardError(f"{program} could not start: {type(exc).__name__}") from None
            # H1 B-3: one deadline covers writing stdin and waiting; the write runs on a thread so a child
            # that never reads cannot hold the caller, and every failure path kills the tree and is recorded.
            budget = min(max(timeout, 0.1), MAX_TIMEOUT_S)
            deadline = time.monotonic() + budget
            stdin = proc.stdin
            if data is not None and stdin is not None:
                threading.Thread(target=_feed, args=(stdin, data), daemon=True).start()
            try:
                code = proc.wait(timeout=max(deadline - time.monotonic(), 0.01))
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                self._record(module_id, program, "timeout")
                raise SwitchyardError(f"{program} timed out") from None
            except BaseException as exc:
                _kill_tree(proc)
                self._record(module_id, program, type(exc).__name__)
                raise
            stdout, truncated = _read_capped(out, limit)
            stderr, _ = _read_capped(err, min(limit, 1_000_000))
        self._record(module_id, program, str(code))
        done = subprocess.CompletedProcess([exe, *argv[1:]], code, stdout, stderr)
        done.truncated = truncated  # type: ignore[attr-defined]
        return done

    def _record(self, module_id: str, program: str, result: str) -> None:
        self._audit.append(actor="core", action="process.spawned", module=module_id,
                           detail={"program": program, "result": result})  # fmt: skip

    def for_module(self, module_id: str) -> ModuleProcess:
        return ModuleProcess(self, module_id)


class ModuleProcess:
    """What ``ctx.spawn`` returns: the broker bound to one module."""

    __slots__ = ("_broker", "_module_id")

    def __init__(self, broker: ProcessBroker, module_id: str) -> None:
        self._broker = broker
        self._module_id = module_id

    def run(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return self._broker.run(self._module_id, argv, **kwargs)
