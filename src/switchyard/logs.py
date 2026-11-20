"""Per-stream JSON Lines logs under ``<data_dir>/logs`` (Q&A question 8).

One file per stream (``<stream>.jsonl``), user-only permissions, every string redacted before writing.
Lines longer than ``MAX_LINE_BYTES`` keep their header and replace ``fields`` with ``{"truncated": true}``.
No prompt or completion text is logged unless a module's debug stream is turned on (DESIGN.md section 7).
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from switchyard.errors import SwitchyardError

MAX_LINE_BYTES = 16 * 1024
MAX_STREAM_BYTES = 20 * 1024 * 1024
_STREAM = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _redact_all(value: Any, redact: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_all(v, redact) for v in value]
    if isinstance(value, dict):
        return {k: _redact_all(v, redact) for k, v in value.items()}
    return value


class JsonlLogSink:
    """Satisfies ``context.LogSink``."""

    def __init__(
        self,
        directory: Path,
        *,
        redact: Callable[[str], str] | None = None,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self.directory = directory
        self._redact = redact or (lambda s: s)
        self._clock = clock
        self._lock = threading.Lock()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    def write(self, module_id: str, stream: str, event: str, fields: Mapping[str, Any]) -> None:
        if not isinstance(stream, str) or not _STREAM.match(stream) or ".." in stream:
            raise SwitchyardError(f"invalid log stream name {stream!r}")
        record: dict[str, Any] = {"ts": self._clock(), "module": module_id, "stream": stream, "event": event}
        # default=str turns paths and other objects into text before redaction sees them
        record["fields"] = json.loads(json.dumps(dict(fields), default=str))
        record = _redact_all(record, self._redact)
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
        if len(line) > MAX_LINE_BYTES:
            record["fields"] = {"truncated": True}
            line = (
                json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode("utf-8")[
                    : MAX_LINE_BYTES - 1
                ]
                + b"\n"
            )
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
        path = self.directory / f"{stream}.jsonl"
        with self._lock:
            # Bounded per stream (R1 review): at MAX_STREAM_BYTES the file becomes <stream>.1.jsonl, replacing
            # the previous one, so a stream never holds more than twice the limit on disk.
            try:
                if path.stat().st_size + len(line) > MAX_STREAM_BYTES:
                    os.replace(path, self.directory / f"{stream}.1.jsonl")
            except FileNotFoundError:
                pass
            fd = os.open(path, flags, 0o600)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
