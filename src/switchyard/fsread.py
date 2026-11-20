"""File-read broker: the ``fs.read`` capability (``ctx.fs``), ADR-0003.

Absolute paths to regular files only (after resolving symlinks), size checked before reading and bounded while
reading, JSON with a nesting limit. Each read is audited as ``fs.read`` with the resolved path and byte count;
content is never recorded.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

from switchyard.capabilities import AuditSink, PolicyEngine
from switchyard.errors import SwitchyardError

DEFAULT_MAX_BYTES = 1 << 20
CEILING_BYTES = 32 << 20
MAX_JSON_DEPTH = 64


def _depth(value: Any, limit: int) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > limit:
            raise SwitchyardError(f"JSON nesting deeper than {limit}")
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)


class FsBroker:
    def __init__(self, policy: PolicyEngine, audit: AuditSink) -> None:
        self._policy = policy
        self._audit = audit

    def read_bytes(self, module_id: str, path: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
        raw = Path(path)
        if not raw.is_absolute():
            raise SwitchyardError("fs.read needs an absolute path")
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or not 0 < max_bytes <= CEILING_BYTES
        ):
            raise SwitchyardError(f"max_bytes must be between 1 and {CEILING_BYTES}")
        try:
            resolved = raw.resolve(strict=True)
        except (OSError, RuntimeError):
            self._policy.require(module_id, "fs.read", path=str(raw))
            raise SwitchyardError(f"cannot read {raw}: not found") from None
        self._policy.require(module_id, "fs.read", path=str(resolved))
        try:
            info = resolved.stat()
            if not stat.S_ISREG(info.st_mode):
                raise SwitchyardError(f"cannot read {resolved}: not a regular file")
            if info.st_size > max_bytes:
                raise SwitchyardError(f"{resolved} is larger than {max_bytes} bytes")
            with resolved.open("rb") as handle:
                data = handle.read(max_bytes + 1)
        except OSError as exc:
            raise SwitchyardError(f"cannot read {resolved}: {type(exc).__name__}") from None
        if len(data) > max_bytes:
            raise SwitchyardError(f"{resolved} is larger than {max_bytes} bytes")
        self._audit.append(actor="core", action="fs.read", module=module_id,
                           detail={"path": str(resolved), "bytes": str(len(data))})  # fmt: skip
        return data

    def read_text(self, module_id: str, path: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
        try:
            return self.read_bytes(module_id, path, max_bytes=max_bytes).decode("utf-8")
        except UnicodeDecodeError:
            raise SwitchyardError(f"{path} is not UTF-8 text") from None

    def read_json(self, module_id: str, path: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> Any:
        text = self.read_text(module_id, path, max_bytes=max_bytes)
        try:
            value = json.loads(text)
        except (ValueError, RecursionError):
            raise SwitchyardError(f"{path} is not valid JSON") from None
        _depth(value, MAX_JSON_DEPTH)
        return value

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
