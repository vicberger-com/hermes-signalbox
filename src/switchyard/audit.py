"""Append-only, hash-chained audit log in JSON Lines (spec section 3, Audit log).

Record fields: ``seq, ts, actor, action, module, detail, prev, hash``. ``hash`` is the SHA-256 of the
canonical JSON of the record without ``hash`` (sorted keys, no whitespace, UTF-8); ``prev`` is the previous
record's hash, ``GENESIS`` for the first. Files are ``audit-NNNNNN.jsonl`` and rotate at ``max_bytes``; the
chain runs across files. Every append is flushed and fsynced.

``verify`` detects an edited, deleted, inserted or reordered record. A log cut off at the end is still a valid
chain, so callers keep the last ``head`` (seq, hash) elsewhere (the state store) and pass it as
``expected_head``. The last record must end with a newline (H1 A-9: a stripped newline fails ``verify``).

A last line that is torn (no newline, not parseable) is what a crash mid-write leaves. It was never anchored,
so opening the log repairs it: the bytes move to a ``.torn-<ns>`` file and ``audit.torn_tail_repaired`` is
recorded. A torn line that held an anchored record still fails ``verify`` (the anchor is missing).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from switchyard.errors import AuditError
from switchyard.hostlock import FileLock

GENESIS = "0" * 64
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
MAX_NAME_CHARS = 128
MAX_DETAIL_CHARS = 1024
_FILE_RE = re.compile(r"audit-(\d{6})\.jsonl\Z")
_FIELDS = frozenset({"seq", "ts", "actor", "action", "module", "detail", "prev", "hash"})
_TAIL_PROBE_BYTES = 64 * 1024
MAX_RECORD_BYTES = 128 * 1024  # one record, serialised (H1 A-13)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canonical(obj: Mapping[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def record_hash(record: Mapping[str, Any]) -> str:
    """Hash of a record without its ``hash`` field."""
    return hashlib.sha256(_canonical({k: v for k, v in record.items() if k != "hash"})).hexdigest()


@dataclass(frozen=True)
class AuditRecord:
    seq: int
    ts: str
    actor: str
    action: str
    module: str
    detail: Mapping[str, str]
    prev: str
    hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq, "ts": self.ts, "actor": self.actor, "action": self.action,
            "module": self.module, "detail": dict(self.detail), "prev": self.prev, "hash": self.hash,
        }  # fmt: skip


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    records: int
    first_bad_seq: int | None = None
    reason: str = ""


def _files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    found = [(int(m.group(1)), p) for p in directory.iterdir() if (m := _FILE_RE.match(p.name))]
    return [p for _, p in sorted(found)]


def _iter_lines(directory: Path) -> Iterator[tuple[bytes, bool]]:
    """Raw non-empty lines and whether each ends with a newline. Splits on ``\\n`` only (H1 A-8): records
    are written with ``ensure_ascii=False``, so U+2028 and friends appear raw inside them."""
    for path in _files(directory):
        with path.open("rb") as fh:
            for line in fh:
                if line.strip():
                    yield line.rstrip(b"\n"), line.endswith(b"\n")


class _TornTail(AuditError):
    pass


class AuditLog:
    """Thread-safe writer and verifier for one audit directory. Satisfies ``capabilities.AuditSink``."""

    def __init__(
        self,
        directory: Path,
        *,
        redact: Callable[[str], str] | None = None,
        clock: Callable[[], str] = _utc_now,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self._dir = directory
        self._redact = redact or (lambda s: s)
        self._clock = clock
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        # (file name, size) right after our last write (1.1 #124)
        self._written: tuple[str, int] | None = None
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self._seq, self._prev, self._file_no = self._recover()
        except _TornTail:
            # H1 A-9: a crash mid-write is repaired now, so startup verification does not see it as tampering
            with self._lock, self._file_lock():
                self._seq, self._prev, self._file_no = self._recover_repairing()

    # state --------------------------------------------------------------------------------------------

    def _recover(self) -> tuple[int, str, int]:
        files = _files(self._dir)
        if not files:
            return 0, GENESIS, 1
        last = files[-1]
        match = _FILE_RE.match(last.name)
        if match is None:  # cannot happen: _files lists only names _FILE_RE matched (H1 A-29)
            raise AuditError(f"unexpected audit file name {last.name!r}")
        file_no = int(match.group(1))
        size = last.stat().st_size
        if size == 0:
            if len(files) == 1:
                return 0, GENESIS, file_no
            last = files[-2]
            size = last.stat().st_size
        probe = _TAIL_PROBE_BYTES
        with last.open("rb") as fh:
            while True:  # H1 A-13: widen the window until the last record is whole
                fh.seek(max(0, size - probe))
                tail = fh.read()
                if probe >= size or tail.rstrip(b"\n").count(b"\n") >= 1:
                    break
                probe *= 4
        if not tail.endswith(b"\n"):
            raise _TornTail(f"{last}: last record is incomplete (torn write); run 'switchyard audit verify'")
        try:
            rec = json.loads(tail.rstrip(b"\n").rsplit(b"\n", 1)[-1])
            seq, digest = int(rec["seq"]), str(rec["hash"])
        except (ValueError, KeyError, TypeError) as exc:
            raise AuditError(f"{last}: last record is unreadable: {exc}") from None
        return seq, digest, file_no

    @property
    def head(self) -> tuple[int, str]:
        """(seq, hash) of the last record; store it to detect tail truncation later."""
        with self._lock:
            return self._seq, self._prev

    # writing ------------------------------------------------------------------------------------------

    def _file_lock(self) -> FileLock:
        try:
            return FileLock(self._dir / ".append.lock")
        except OSError as exc:  # pragma: no cover - directory permissions
            raise AuditError(f"cannot lock the audit log: {exc}") from exc

    def _clean_detail(self, detail: Mapping[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, value in detail.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise AuditError("audit detail keys and values must be strings")
            clean = self._redact(value)
            try:  # a lone surrogate cannot be written (1.1 acceptance S1-10)
                key.encode("utf-8")
                clean.encode("utf-8")
            except UnicodeEncodeError:
                raise AuditError(f"audit detail {key[:40]!r} is not valid text") from None
            if len(key) > MAX_NAME_CHARS or len(clean) > MAX_DETAIL_CHARS:
                raise AuditError(f"audit detail {key[:40]!r} is too long")
            out[key] = clean
        return out

    def append(self, *, actor: str, action: str, module: str, detail: Mapping[str, str]) -> AuditRecord:
        for name, value in (("actor", actor), ("action", action), ("module", module)):
            if not isinstance(value, str) or len(value) > MAX_NAME_CHARS:
                raise AuditError(f"audit {name} must be a string of at most {MAX_NAME_CHARS} characters")
        clean = self._clean_detail(detail)
        try:
            return self._append_locked(actor, action, module, clean)
        except TimeoutError:
            raise AuditError("the audit log is locked by another process") from None
        except OSError as exc:  # the lock file could not be opened
            raise AuditError(f"cannot write audit record: {exc}") from exc

    def _append_locked(self, actor: str, action: str, module: str, clean: dict[str, str]) -> AuditRecord:
        with self._lock, self._file_lock():
            # Another process may have appended since our last write: recover the head under the shared
            # lock, so two writers never fork the chain (R1 review). 1.1 #124: when the newest file is still
            # the one we wrote last, at the size we left it, nobody else has written, and the tail re-read
            # is skipped.
            if not self._unchanged_since_our_write():
                self._seq, self._prev, self._file_no = self._recover_repairing()
            return self._emit(actor, action, module, clean)

    def _unchanged_since_our_write(self) -> bool:
        if self._written is None:
            return False
        files = _files(self._dir)
        if not files or files[-1].name != self._written[0]:
            return False
        try:
            return files[-1].stat().st_size == self._written[1]
        except OSError:
            return False

    def _recover_repairing(self) -> tuple[int, str, int]:
        """``_recover``; a torn last record is quarantined and the repair recorded (the caller holds both
        locks). A crash cut the record short: it was never anchored (R1 follow-up, H1 A-9)."""
        try:
            return self._recover()
        except _TornTail:
            quarantined = self._repair_torn_tail()
            self._seq, self._prev, self._file_no = self._recover()
            self._emit("core", "audit.torn_tail_repaired", "", {"quarantine": quarantined})
            return self._seq, self._prev, self._file_no

    def _repair_torn_tail(self) -> str:
        last = next(p for p in reversed(_files(self._dir)) if p.stat().st_size > 0)
        data = last.read_bytes()
        cut = data.rfind(b"\n") + 1
        target = last.with_name(f"{last.stem}.torn-{time.time_ns()}")
        target.write_bytes(data[cut:])
        with last.open("r+b") as fh:
            fh.truncate(cut)
        return target.name

    def _emit(self, actor: str, action: str, module: str, clean: dict[str, str]) -> AuditRecord:
        """Write one record; the caller holds both locks and has recovered the head."""
        body: dict[str, Any] = {
            "seq": self._seq + 1, "ts": self._clock(), "actor": actor, "action": action,
            "module": module, "detail": clean, "prev": self._prev,
        }  # fmt: skip
        body["hash"] = record_hash(body)
        line = _canonical(body) + b"\n"
        if len(line) > MAX_RECORD_BYTES:
            raise AuditError(f"audit record is too large ({len(line)} bytes; limit {MAX_RECORD_BYTES})")
        self._write(line)
        self._seq, self._prev = body["seq"], body["hash"]
        return AuditRecord(**{**body, "detail": MappingProxyType(clean)})

    def _write(self, line: bytes) -> None:
        path = self._dir / f"audit-{self._file_no:06d}.jsonl"
        if path.exists() and path.stat().st_size > 0 and path.stat().st_size + len(line) > self._max_bytes:
            self._file_no += 1
            path = self._dir / f"audit-{self._file_no:06d}.jsonl"
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(path, flags, 0o600)
            try:
                view = memoryview(line)
                while view:  # H1 A-14: a short write is continued, never left half done
                    written = os.write(fd, view)
                    if written <= 0:
                        raise AuditError("cannot write audit record: no progress")
                    view = view[written:]
                os.fsync(fd)
                self._written = (path.name, os.fstat(fd).st_size)
            finally:
                os.close(fd)
        except OSError as exc:
            raise AuditError(f"cannot write audit record: {exc}") from exc

    # reading ------------------------------------------------------------------------------------------

    def tail(self, n: int) -> list[dict[str, Any]]:
        """The last ``n`` records, oldest first."""
        if n <= 0:
            return []
        out: list[dict[str, Any]] = []
        with self._lock:
            for path in reversed(_files(self._dir)):
                text = path.read_text(encoding="utf-8", errors="replace")
                lines = [ln for ln in text.split("\n") if ln.strip()]  # "\n" only (H1 A-8)
                out[:0] = [json.loads(ln) for ln in lines[-(n - len(out)) :]]
                if len(out) >= n:
                    break
        return out

    def verify(self, expected_head: tuple[int, str] | None = None) -> VerifyResult:
        # Under the append lock: a read racing another process's write must not see half a record
        # (R1 follow-up).
        try:
            with self._lock, self._file_lock():
                return self.verify_directory(self._dir, expected_head)
        except TimeoutError:
            raise AuditError("the audit log is locked by another process") from None

    @staticmethod
    def verify_directory(directory: Path, expected_head: tuple[int, str] | None = None) -> VerifyResult:
        prev, seq, anchor_seen, last_terminated = GENESIS, 0, False, True
        for raw, terminated in _iter_lines(directory):
            last_terminated = terminated
            expected = seq + 1
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (
                ValueError,
                RecursionError,
            ):  # bad bytes or hostile nesting (H1 A-12): a report, not a crash
                return VerifyResult(False, seq, expected, "unparseable record")
            if not isinstance(rec, dict) or set(rec) != _FIELDS:
                return VerifyResult(False, seq, expected, "record has the wrong fields")
            bad = rec["seq"] if isinstance(rec["seq"], int) else expected
            if rec["seq"] != expected:
                return VerifyResult(False, seq, bad, f"sequence gap: expected {expected}")
            if rec["prev"] != prev:
                return VerifyResult(False, seq, bad, "chain broken: prev does not match")
            if rec["hash"] != record_hash(rec):
                return VerifyResult(False, seq, bad, "hash mismatch: record was modified")
            prev, seq = rec["hash"], expected
            if expected_head is not None and seq == expected_head[0]:
                if prev != expected_head[1]:
                    return VerifyResult(False, seq, seq, "head anchor hash does not match")
                anchor_seen = True
        if not last_terminated:
            return VerifyResult(False, seq, seq, "last record is not terminated by a newline")
        if expected_head is not None and expected_head[0] > 0 and not anchor_seen:
            return VerifyResult(
                False, seq, seq + 1, f"head anchor missing: log ends at {seq}, anchor is {expected_head[0]}"
            )
        return VerifyResult(True, seq)
