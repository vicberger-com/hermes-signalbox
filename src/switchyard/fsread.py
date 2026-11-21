r"""File-read broker: the ``fs.read`` capability (``ctx.fs``), ADR-0003.

Order of checks, chosen so that nothing touches the file system or the network before the policy allows it:

1. syntax: absolute, local path. On Windows the path must start with a drive letter (``C:\``); UNC paths
   (``\\host\share``) would make Windows contact the host and send NTLM credentials, and device paths
   (``\\.\``, ``\\?\``, ``CON``, ``NUL`` ...) are not files;
2. the ``fs.read`` grant;
3. open (POSIX: non-blocking, so a FIFO cannot hang the host), then ``fstat`` on the open handle: regular file
   and within ``max_bytes``; the read itself is bounded too.

JSON is screened before parsing: nesting depth and the number of containers and separators are counted on the
text with string literals blanked, so a file cannot make the parser build a structure much larger than its
budget. Every read is audited as ``fs.read`` (resolved path, bytes) and every refusal after the grant check as
``fs.read_failed`` (path, reason); content is never recorded.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path, PureWindowsPath
from typing import Any

from switchyard.capabilities import AuditSink, PolicyEngine
from switchyard.errors import SwitchyardError

DEFAULT_MAX_BYTES = 1 << 20
CEILING_BYTES = 32 << 20
MAX_JSON_DEPTH = 64
MAX_JSON_ITEMS = 1_000_000
_DRIVE = re.compile(r"[A-Za-z]:\Z")
_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
_BRACKETS = re.compile(r"[\[\]{}]")
_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *(f"COM{i}" for i in range(10)),
        *(f"LPT{i}" for i in range(10)),
    }
)
_SUPERSCRIPT = str.maketrans("\u00b9\u00b2\u00b3", "123")  # COM¹ LPT³: legacy device aliases (H1 B-6)


def _device_stem(part: str) -> str:
    """The name Windows matches against device names: before any ``:`` (``NUL:``, ``CON:stream``), before the
    first ``.``, trailing spaces and dots dropped, superscript digits as digits, upper case."""
    stem = part.split(":", 1)[0].split(".", 1)[0].rstrip(" .")
    return stem.translate(_SUPERSCRIPT).upper()


class FsReadFailed(SwitchyardError):
    """A read was allowed but did not succeed (missing, not a regular file, too large, not text, not JSON)."""


def check_local_path(path: str | Path, *, windows: bool | None = None) -> Path:
    """Return ``path`` if it is an absolute local path, else raise. No file-system access."""
    text = str(path)
    if "\x00" in text:
        raise SwitchyardError("path contains a NUL character")
    on_windows = sys.platform == "win32" if windows is None else windows
    if on_windows:
        pure = PureWindowsPath(text)
        if not _DRIVE.match(pure.drive) or not pure.root:
            raise SwitchyardError(
                "fs.read needs an absolute local path with a drive letter (no UNC or device path)"
            )
        for part in pure.parts[1:]:
            if _device_stem(part) in _RESERVED:
                raise SwitchyardError("fs.read refuses Windows device names")
        return Path(text)
    if not text.startswith("/"):
        raise SwitchyardError("fs.read needs an absolute path")
    return Path(text)


def screen_json(text: str) -> None:
    """Reject JSON nested deeper than ``MAX_JSON_DEPTH`` or holding more than ``MAX_JSON_ITEMS`` values."""
    bare = _STRING.sub('""', text)
    if bare.count(",") + bare.count("[") + bare.count("{") > MAX_JSON_ITEMS:
        raise SwitchyardError(f"JSON holds more than {MAX_JSON_ITEMS} values")
    depth = 0
    for match in _BRACKETS.finditer(bare):
        depth += 1 if match.group() in "[{" else -1
        if depth > MAX_JSON_DEPTH:
            raise SwitchyardError(f"JSON nesting deeper than {MAX_JSON_DEPTH}")


class FsBroker:
    def __init__(self, policy: PolicyEngine, audit: AuditSink) -> None:
        self._policy = policy
        self._audit = audit

    def _fail(self, module_id: str, path: Path, reason: str, message: str) -> FsReadFailed:
        detail = {"path": str(path), "reason": reason}
        self._audit.append(actor="core", action="fs.read_failed", module=module_id, detail=detail)
        return FsReadFailed(message)

    def read_bytes(self, module_id: str, path: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
        raw = check_local_path(path)
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or not 0 < max_bytes <= CEILING_BYTES
        ):
            raise SwitchyardError(f"max_bytes must be between 1 and {CEILING_BYTES}")
        self._policy.require(module_id, "fs.read", path=str(raw))
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            resolved = raw.resolve(strict=True)
            if resolved.is_dir():  # Windows cannot open a directory; report it the same way as POSIX
                raise self._fail(
                    module_id, resolved, "not_regular", f"cannot read {resolved}: not a regular file"
                )
            fd = os.open(resolved, flags)
        except (OSError, RuntimeError, ValueError):
            raise self._fail(
                module_id, raw, "not_found", f"cannot read {raw}: not found or not readable"
            ) from None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise self._fail(
                    module_id, resolved, "not_regular", f"cannot read {resolved}: not a regular file"
                )
            if info.st_size > max_bytes:
                raise self._fail(
                    module_id, resolved, "too_large", f"{resolved} is larger than {max_bytes} bytes"
                )
            with os.fdopen(fd, "rb", closefd=True) as handle:
                fd = -1
                data = handle.read(max_bytes + 1)
        except OSError as exc:
            raise self._fail(
                module_id, resolved, "io_error", f"cannot read {resolved}: {type(exc).__name__}"
            ) from None
        finally:
            if fd >= 0:
                os.close(fd)
        if len(data) > max_bytes:
            raise self._fail(module_id, resolved, "too_large", f"{resolved} is larger than {max_bytes} bytes")
        detail = {"path": str(resolved), "bytes": str(len(data))}
        self._audit.append(actor="core", action="fs.read", module=module_id, detail=detail)
        return data

    def read_text(self, module_id: str, path: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
        data = self.read_bytes(module_id, path, max_bytes=max_bytes)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise self._fail(module_id, Path(str(path)), "not_utf8", f"{path} is not UTF-8 text") from None

    def read_json(self, module_id: str, path: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> Any:
        text = self.read_text(module_id, path, max_bytes=max_bytes)
        try:
            screen_json(text)
            return json.loads(text)
        except SwitchyardError as exc:
            raise self._fail(module_id, Path(str(path)), "not_json", str(exc)) from None
        except (ValueError, RecursionError):
            raise self._fail(module_id, Path(str(path)), "not_json", f"{path} is not valid JSON") from None

    def for_module(self, module_id: str) -> ModuleFs:
        return ModuleFs(self, module_id)


class ModuleFs:
    """What ``ctx.fs`` returns: the broker bound to one module."""

    __slots__ = ("_broker", "_module_id")

    def __init__(self, broker: FsBroker, module_id: str) -> None:
        self._broker = broker
        self._module_id = module_id

    def read_text(self, path: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
        return self._broker.read_text(self._module_id, path, max_bytes=max_bytes)

    def read_json(self, path: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> Any:
        return self._broker.read_json(self._module_id, path, max_bytes=max_bytes)
