"""Secret backends for the core broker (ADR-0002). Each satisfies ``switchyard.secrets.SecretBackend``:
``name``, ``available()``, ``get(name)`` (``KeyError`` when the backend does not hold the name); writable ones
add ``set(name, value)``.

Rules every backend follows: a secret name never reaches a shell (argv lists only, through ``ctx.spawn``);
values are read from stdout or written through stdin or ctypes, never placed on a command line; helper
stderr is never copied into an error (it can echo input); a locked or missing helper raises ``SecretLocked``
so the broker fails closed instead of falling through to another backend.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from switchyard.errors import SwitchyardError

SERVICE = "switchyard"  # keychain service / secret-tool attribute / Windows target prefix

Runner = Callable[..., Any]  # ctx.spawn.run: (argv, *, env=None, input=None, timeout=...) -> CompletedProcess


class SecretLocked(SwitchyardError):
    """The backend exists but cannot be read now (locked, signed out, helper failing). Fails closed."""


def check_name(name: str) -> None:
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 64
        or name[0] in "-."
        or not all(c.isascii() and (c.islower() or c.isdigit() or c in "._-") for c in name)
    ):
        raise SwitchyardError("invalid secret name")


class EnvBackend:
    """Development only: ``SWITCHYARD_SECRET_<NAME>`` (dots and dashes become underscores, upper case)."""

    name = "env"
    PREFIX = "SWITCHYARD_SECRET_"

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else os.environ

    @classmethod
    def variable(cls, name: str) -> str:
        return cls.PREFIX + name.upper().replace(".", "_").replace("-", "_")

    def available(self) -> bool:
        return True

    def get(self, name: str) -> str:
        check_name(name)
        return self._environ[self.variable(name)]


class WinCredBackend:
    """Windows Credential Manager: generic credentials, target ``switchyard:<name>`` (ctypes, advapi32)."""

    name = "wincred"

    def available(self) -> bool:
        return sys.platform == "win32"

    @staticmethod
    def target(name: str) -> str:
        return f"{SERVICE}:{name}"

    def get(self, name: str) -> str:
        check_name(name)
        return _wincred().read(self.target(name))

    def set(self, name: str, value: str) -> None:
        check_name(name)
        _wincred().write(self.target(name), name, value)

    def delete(self, name: str) -> None:
        check_name(name)
        _wincred().delete(self.target(name))


class _CliBackend:
    def __init__(self, run: Runner, program: str) -> None:
        self._run = run
        self._program = program

    def _helper_present(self) -> bool:
        return shutil.which(self._program) is not None


class KeychainBackend(_CliBackend):
    """macOS login keychain via ``security`` (read only in M1: ``add-generic-password`` takes the value as an
    argument, which would expose it in the process list)."""

    name = "keychain"

    def __init__(self, run: Runner) -> None:
        super().__init__(run, "security")

    def available(self) -> bool:
        return sys.platform == "darwin" and self._helper_present()

    def get(self, name: str) -> str:
        check_name(name)
        done = self._run(["security", "find-generic-password", "-s", SERVICE, "-a", name, "-w"])
        if done.returncode == 44:  # errSecItemNotFound
            raise KeyError(name)
        if done.returncode != 0:
            raise SecretLocked(f"keychain read failed (exit {done.returncode})")
        return str(done.stdout).rstrip("\n")


class SecretToolBackend(_CliBackend):
    """Linux Secret Service (GNOME Keyring, KWallet) via libsecret's ``secret-tool``."""

    name = "secret-tool"

    def __init__(self, run: Runner) -> None:
        super().__init__(run, "secret-tool")

    def available(self) -> bool:
        return sys.platform.startswith("linux") and self._helper_present()

    def get(self, name: str) -> str:
        check_name(name)
        done = self._run(["secret-tool", "lookup", "service", SERVICE, "account", name])
        if done.returncode == 1 and not done.stdout and not str(done.stderr or "").strip():
            raise KeyError(name)  # not found: exit 1, no output; a D-Bus or keyring error prints to stderr
        if done.returncode != 0:
            raise SecretLocked(f"secret-tool lookup failed (exit {done.returncode})")
        return str(done.stdout)

    def set(self, name: str, value: str) -> None:
        check_name(name)
        label = f"--label={SERVICE} {name}"
        done = self._run(["secret-tool", "store", label, "service", SERVICE, "account", name], input=value)
        if done.returncode != 0:
            raise SecretLocked(f"secret-tool store failed (exit {done.returncode})")


class BitwardenBackend(_CliBackend):
    """Vaultwarden or Bitwarden through the ``bw`` CLI.

    The operator unlocks ``bw`` and exports the session key in ``session_env`` (default ``BW_SESSION``); the
    backend never unlocks anything itself. Item name = secret name; the value is the item's password field.
    """

    name = "bw"

    def __init__(self, run: Runner, *, session_env: str = "BW_SESSION",
                 environ: Mapping[str, str] | None = None) -> None:  # fmt: skip
        super().__init__(run, "bw")
        self._session_env = session_env
        self._environ = environ if environ is not None else os.environ

    def _env(self) -> dict[str, str]:
        session = self._environ.get(self._session_env, "")
        env = {"BW_SESSION": session} if session else {}
        for key in ("BITWARDENCLI_APPDATA_DIR", "NODE_EXTRA_CA_CERTS"):
            if key in self._environ:
                env[key] = self._environ[key]
        return env

    def available(self) -> bool:
        return self._helper_present()

    def status(self) -> str:
        done = self._run(["bw", "status", "--nointeraction"], env=self._env())
        if done.returncode != 0:
            return "error"
        try:
            value = json.loads(done.stdout).get("status", "error")
        except (ValueError, AttributeError):
            return "error"
        return str(value) if value in ("unauthenticated", "locked", "unlocked") else "error"

    def get(self, name: str) -> str:
        check_name(name)
        status = self.status()
        if status != "unlocked":
            raise SecretLocked(f"bw is {status}; unlock it and export {self._session_env}")
        done = self._run(["bw", "get", "password", name, "--nointeraction"], env=self._env())
        if done.returncode != 0:
            if "not found" in str(done.stderr).lower():
                raise KeyError(name)
            raise SecretLocked(f"bw get failed (exit {done.returncode})")
        return str(done.stdout)


# Windows Credential Manager --------------------------------------------------------------------------------


class _WinCred:  # pragma: no cover - exercised on Windows only (CI windows jobs and local runs)
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        self.ctypes = ctypes
        self.CREDENTIAL = CREDENTIAL
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.read_fn = advapi.CredReadW
        self.read_fn.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]  # fmt: skip
        self.read_fn.restype = wintypes.BOOL
        self.write_fn = advapi.CredWriteW
        self.write_fn.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
        self.write_fn.restype = wintypes.BOOL
        self.delete_fn = advapi.CredDeleteW
        self.delete_fn.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.delete_fn.restype = wintypes.BOOL
        self.free_fn = advapi.CredFree
        self.free_fn.argtypes = [ctypes.c_void_p]

    def _error(self, what: str) -> int:
        code: int = self.ctypes.get_last_error()
        if code != self.ERROR_NOT_FOUND:
            raise SecretLocked(f"Credential Manager {what} failed (error {code})")
        return code

    def read(self, target: str) -> str:
        ctypes = self.ctypes
        pointer = ctypes.POINTER(self.CREDENTIAL)()
        if not self.read_fn(target, self.CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            self._error("read")
            raise KeyError(target)
        try:
            cred = pointer.contents
            raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        finally:
            self.free_fn(pointer)
        return str(raw.decode("utf-16-le"))

    def write(self, target: str, user: str, value: str) -> None:
        ctypes = self.ctypes
        blob = value.encode("utf-16-le")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = self.CREDENTIAL()
        cred.Type = self.CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.UserName = user
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        if not self.write_fn(ctypes.byref(cred), 0):
            self._error("write")
            raise SecretLocked("Credential Manager write failed")

    def delete(self, target: str) -> None:
        if not self.delete_fn(target, self.CRED_TYPE_GENERIC, 0):
            self._error("delete")


_WINCRED: _WinCred | None = None


def _wincred() -> _WinCred:
    global _WINCRED
    if sys.platform != "win32":
        raise SecretLocked("Windows Credential Manager is only available on Windows")
    if _WINCRED is None:  # pragma: no cover - Windows only
        _WINCRED = _WinCred()
    return _WINCRED  # pragma: no cover - Windows only


def default_order() -> list[str]:
    if sys.platform == "win32":
        return ["wincred"]
    if sys.platform == "darwin":
        return ["keychain"]
    return ["secret-tool"]


def build(names: Sequence[str], run: Runner, *, session_env: str, allow_env: bool) -> list[Any]:
    """Backends in ``names`` order. ``env`` is refused unless ``allow_env``."""
    made: list[Any] = []
    for name in names:
        if name == "env":
            if not allow_env:
                raise SwitchyardError("the env backend is for development; set allow_env_backend = true")
            made.append(EnvBackend())
        elif name == "wincred":
            made.append(WinCredBackend())
        elif name == "keychain":
            made.append(KeychainBackend(run))
        elif name == "secret-tool":
            made.append(SecretToolBackend(run))
        elif name == "bw":
            made.append(BitwardenBackend(run, session_env=session_env))
        else:
            raise SwitchyardError(f"unknown secret backend {name!r}")
    return made
