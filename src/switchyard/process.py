"""Process broker: the ``process.spawn`` capability (``ctx.spawn``).

``ctx.spawn.run(argv, ...)`` starts a helper program for a module that was granted ``process.spawn``. The
child gets a minimal environment (an allow-list plus what the caller passes explicitly), stdin from the null
device unless ``input`` is given, a timeout, and no shell. Each run is audited with the program's base name
and exit code only; arguments, input and output are never recorded, because they can carry secret names or
values.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
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


def find_program(name: str) -> str | None:
    """Absolute path of ``name`` from PATH, never from the working directory.

    On Windows ``shutil.which`` looks in the current directory first, so a ``bw.cmd`` planted in a folder the
    user starts from would be chosen over the real one. Results that are relative or live in the working
    directory are refused.
    """
    exe = shutil.which(name)
    if exe is None or not os.path.isabs(exe):
        return None
    try:
        if Path(exe).resolve().parent == Path.cwd().resolve():
            return None
    except OSError:
        return None
    return exe


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
    ) -> subprocess.CompletedProcess[str]:
        if not argv or not all(isinstance(a, str) for a in argv):
            raise SwitchyardError("argv must be a non-empty list of strings")
        program = Path(argv[0]).name
        self._policy.require(module_id, "process.spawn", program=program)
        exe = find_program(argv[0])
        if exe is None:
            raise SwitchyardError(f"program {program!r} not found")
        child_env = {k: v for k in BASE_ENV if (v := os.environ.get(k)) is not None}
        child_env.update(env or {})
        child_env["NO_COLOR"] = "1"
        try:
            # An argv list and no shell.
            done = subprocess.run(  # noqa: S603 # nosec B603
                [exe, *argv[1:]],
                env=child_env,
                input=input,
                stdin=None if input is not None else subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=min(max(timeout, 0.1), MAX_TIMEOUT_S),
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._record(module_id, program, "timeout")
            raise SwitchyardError(f"{program} timed out") from None
        except OSError as exc:
            self._record(module_id, program, type(exc).__name__)
            raise SwitchyardError(f"{program} could not start: {type(exc).__name__}") from None
        self._record(module_id, program, str(done.returncode))
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
