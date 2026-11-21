"""In-process, typed publish/subscribe (spec section 3, Events).

* Event types are dotted lower-case names with at least two parts (``module.activated``). Subscriptions
  take an exact type, ``<prefix>.*`` or ``*``.
* Handlers run synchronously in subscription order on a snapshot of the subscriber list, so subscribing during
  dispatch affects only later events.
* Event data must be JSON-compatible (string keys, finite numbers) and at most ``MAX_DATA_BYTES`` encoded.
  Each handler receives its own decoded copy behind a read-only top-level mapping, so no handler can change
  what another sees.
* A handler exception never reaches the publisher. It is audited with the exception class name only (messages
  can carry secrets) and passed to ``on_handler_error`` so the lifecycle manager can stop a failing module.
* Re-entrant publishing (a handler publishing) is limited to ``MAX_DEPTH`` per thread; deeper publishes are
  dropped and audited once per chain.

Modules publish only through ``ModuleContext.emit``, which restricts them to their own namespace.
"""

from __future__ import annotations

import json
import math
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from switchyard.capabilities import CORE_ACTOR, AuditSink
from switchyard.errors import SwitchyardError, UsageError

MAX_DATA_BYTES = 64 * 1024
MAX_DEPTH = 8
MAX_SUBSCRIPTIONS = 64  # per module: each one costs a call per matching event (H1 B-18)
_TYPE = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\Z")
_PREFIX = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\Z")

Handler = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    type: str
    source: str
    data: Mapping[str, Any]
    ts: str


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def check_type(type_: str) -> None:
    if not isinstance(type_, str) or not _TYPE.match(type_):
        raise SwitchyardError(
            f"invalid event type {type_!r} (expected dotted lower-case, e.g. 'module.activated')"
        )


def _check_pattern(pattern: str) -> None:
    if pattern == "*":
        return
    if pattern.endswith(".*") and _PREFIX.match(pattern[:-2]):
        return
    if _TYPE.match(pattern):
        return
    raise UsageError(f"invalid subscription pattern {pattern!r} (exact type, '<prefix>.*' or '*')")


def _matches(pattern: str, type_: str) -> bool:
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return type_.startswith(pattern[:-1])
    return pattern == type_


def _check_json(value: Any, depth: int = 0) -> None:
    if depth > 32:
        raise SwitchyardError("event data is nested too deeply")
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise SwitchyardError("event data contains a non-finite number")
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _check_json(item, depth + 1)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise UsageError("event data keys must be strings")
            _check_json(item, depth + 1)
        return
    raise SwitchyardError(f"event data contains a {type(value).__name__}, which is not JSON-compatible")


def encode_data(data: Mapping[str, Any]) -> str:
    """Validate and encode event data. Raises ``SwitchyardError``."""
    if not isinstance(data, Mapping):
        raise UsageError("event data must be a mapping")
    _check_json(data)
    text = json.dumps(data, separators=(",", ":"), allow_nan=False)
    if len(text.encode("utf-8")) > MAX_DATA_BYTES:
        raise SwitchyardError(f"event data is larger than {MAX_DATA_BYTES} bytes")
    return text


class EventBus:
    """Satisfies ``context.EventBusPort``. Thread-safe."""

    def __init__(
        self,
        audit: AuditSink,
        *,
        clock: Callable[[], str] = _utc_now,
        on_handler_error: Callable[[str, BaseException], None] | None = None,
    ) -> None:
        self._audit = audit
        self._clock = clock
        self._on_error = on_handler_error
        self._subs: list[tuple[str, str, Handler]] = []
        self._lock = threading.Lock()
        self._local = threading.local()

    def set_error_handler(self, handler: Callable[[str, BaseException], None] | None) -> None:
        """Replace the ``on_handler_error`` callback (the lifecycle manager attaches itself here)."""
        self._on_error = handler

    def subscribe(self, owner: str, type_: str, handler: Handler) -> None:
        _check_pattern(type_)
        with self._lock:
            if sum(1 for s in self._subs if s[0] == owner) >= MAX_SUBSCRIPTIONS:
                raise SwitchyardError(f"{owner!r} already has {MAX_SUBSCRIPTIONS} event subscriptions")
            self._subs.append((owner, type_, handler))

    def unsubscribe_all(self, owner: str) -> None:
        with self._lock:
            self._subs = [s for s in self._subs if s[0] != owner]

    def subscriptions(self, owner: str) -> int:
        with self._lock:
            return sum(1 for s in self._subs if s[0] == owner)

    def publish(self, source: str, type_: str, data: Mapping[str, Any]) -> int:
        """Deliver to matching handlers. Returns how many handlers completed without raising."""
        check_type(type_)
        text = encode_data(data)

        depth = getattr(self._local, "depth", 0)
        if depth >= MAX_DEPTH:
            if not getattr(self._local, "overflow_reported", False):
                self._local.overflow_reported = True
                self._audit.append(
                    actor=CORE_ACTOR, action="event.depth_exceeded", module=source, detail={"type": type_}
                )
            return 0

        with self._lock:
            targets = [(owner, h) for owner, pattern, h in self._subs if _matches(pattern, type_)]
        ts = self._clock()
        delivered = 0
        self._local.depth = depth + 1
        try:
            for owner, handler in targets:
                event = Event(type_, source, MappingProxyType(json.loads(text)), ts)
                try:
                    handler(event)
                    delivered += 1
                except Exception as exc:
                    self._audit.append(
                        actor=CORE_ACTOR,
                        action="event.handler_failed",
                        module=owner,
                        detail={"type": type_, "error": type(exc).__name__},
                    )
                    if self._on_error is not None:
                        self._on_error(owner, exc)
        finally:
            self._local.depth = depth
            if depth == 0:
                self._local.overflow_reported = False
        return delivered
