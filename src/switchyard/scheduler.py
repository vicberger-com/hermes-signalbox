"""Scheduler and trigger engine (spec section 3, Events and scheduler).

Trigger kinds and specs:

* ``time``: ``{"every": seconds}`` (first run one interval after ``add``; a long gap runs once, no catch-up)
  or ``{"cron": "m h dom mon dow"}`` (fires at most once per matching minute, local wall time from ``now``).
* ``event``: ``{"type": pattern}``; fires on matching bus events with ``{"type", "source", "data"}``.
* ``usage`` and ``capacity``: ``{"metric": name, "above": x}`` or ``{"metric": name, "below": x}``; fed
  by ``observe(metric, value)``. Edge-triggered: fires when the condition becomes true, re-arms when false.

Every trigger runs at most once at a time (a run requested while one is in progress is skipped) and not
again within ``min_interval_s``. Skips are counted and published as ``trigger.skipped``; runs as
``trigger.fired``.
A failing callback is counted, audited with the exception class name only, and never propagates.

The scheduler does not own a thread: standalone, the daemon calls ``tick()``; inside Hermes, a registered idle
task does. Clocks are injected for testability.
"""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from switchyard.capabilities import CORE_ACTOR, AuditSink
from switchyard.errors import SwitchyardError
from switchyard.events import Event, EventBus, _check_pattern

KINDS = frozenset({"time", "event", "usage", "capacity"})
_ID = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")

Callback = Callable[[dict[str, Any]], None]


# cron -----------------------------------------------------------------------------------------------------

_CRON_FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of month", 1, 31),
    ("month", 1, 12),
    ("weekday", 0, 7),
)
_NUM = re.compile(r"\d{1,2}\Z")


def _cron_field(text: str, name: str, low: int, high: int) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        base, _, step_text = part.partition("/")
        if step_text and not _NUM.match(step_text):
            raise SwitchyardError(f"cron {name}: bad step in {part!r}")
        step = int(step_text) if step_text else 1
        if step < 1:
            raise SwitchyardError(f"cron {name}: step must be at least 1")
        if base == "*":
            start, end = low, high
        else:
            first, _, last = base.partition("-")
            if not _NUM.match(first) or (last and not _NUM.match(last)):
                raise SwitchyardError(f"cron {name}: bad value {part!r}")
            start, end = int(first), int(last) if last else int(first)
            if step_text and not last:
                end = high
        if not (low <= start <= end <= high):
            raise SwitchyardError(f"cron {name}: {part!r} is outside {low}-{high} or reversed")
        values.update(range(start, end + 1, step))
    return frozenset(values)


@dataclass(frozen=True)
class Cron:
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]  # 0 = Sunday
    dom_restricted: bool
    dow_restricted: bool

    @classmethod
    def parse(cls, expr: str) -> Cron:
        parts = expr.split() if isinstance(expr, str) else []
        if len(parts) != 5:
            raise SwitchyardError(f"cron expression {expr!r} must have 5 fields")
        sets = [_cron_field(p, n, lo, hi) for p, (n, lo, hi) in zip(parts, _CRON_FIELDS, strict=True)]
        weekdays = frozenset(0 if d == 7 else d for d in sets[4])
        return cls(sets[0], sets[1], sets[2], sets[3], weekdays, parts[2] != "*", parts[4] != "*")

    def matches(self, when: datetime) -> bool:
        if when.minute not in self.minutes or when.hour not in self.hours or when.month not in self.months:
            return False
        dom = when.day in self.days
        dow = (when.isoweekday() % 7) in self.weekdays
        if self.dom_restricted and self.dow_restricted:
            return dom or dow  # classic cron: either restriction may match
        return dom and dow


# triggers -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Trigger:
    id: str
    owner: str
    kind: str
    spec: Mapping[str, Any]
    callback: Callback
    min_interval_s: float = 0.0


@dataclass
class _State:
    trigger: Trigger
    cron: Cron | None = None
    every: float | None = None
    next_due: float = 0.0
    last_minute: datetime | None = None
    last_run: float | None = None
    running: bool = False
    tripped: bool = False
    counts: dict[str, int] = field(default_factory=lambda: {"fired": 0, "skipped": 0, "failed": 0})


def _number(value: Any) -> bool:
    """A real, finite number: NaN or infinity would make a trigger silently never fire (H1 B-21)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate(t: Trigger) -> None:
    if not isinstance(t.id, str) or not _ID.match(t.id):
        raise SwitchyardError(f"invalid trigger id {t.id!r}")
    if t.kind not in KINDS:
        raise SwitchyardError(f"trigger {t.id}: kind must be one of {sorted(KINDS)}")
    if not _number(t.min_interval_s) or t.min_interval_s < 0:
        raise SwitchyardError(f"trigger {t.id}: min_interval_s must be a number >= 0")
    spec = dict(t.spec)
    if t.kind == "time":
        if set(spec) == {"every"}:
            if not _number(spec["every"]) or spec["every"] <= 0:
                raise SwitchyardError(f"trigger {t.id}: 'every' must be a positive number of seconds")
        elif set(spec) == {"cron"}:
            Cron.parse(spec["cron"])
        else:
            raise SwitchyardError(f"trigger {t.id}: time spec needs exactly one of 'every' or 'cron'")
    elif t.kind == "event":
        if set(spec) != {"type"}:
            raise SwitchyardError(f"trigger {t.id}: event spec needs exactly 'type'")
        _check_pattern(spec["type"])
    else:
        bounds = set(spec) - {"metric"}
        metric = spec.get("metric")
        if not isinstance(metric, str) or not metric or len(bounds) != 1 or not bounds <= {"above", "below"}:
            raise SwitchyardError(
                f"trigger {t.id}: {t.kind} spec needs 'metric' and one of 'above' or 'below'"
            )
        if not _number(spec[bounds.pop()]):
            raise SwitchyardError(f"trigger {t.id}: threshold must be a number")


# A wall clock that steps back by up to this much (NTP correction, DST fall-back) does not fire a cron trigger
# again for minutes it already passed; a larger step is a clock correction and starts afresh (H1 B-5).
CLOCK_STEP_BACK_TOLERANCE = timedelta(hours=3)


class Scheduler:
    def __init__(
        self,
        bus: EventBus,
        audit: AuditSink,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._bus = bus
        self._audit = audit
        self._mono = monotonic
        self._now = now
        self._states: dict[str, _State] = {}
        self._owner_listeners: list[Callable[[str], None]] = []
        self._lock = threading.RLock()

    # registry -----------------------------------------------------------------------------------------

    def add(self, trigger: Trigger) -> None:
        _validate(trigger)
        state = _State(trigger)
        if trigger.kind == "time":
            if "every" in trigger.spec:
                state.every = float(trigger.spec["every"])
                state.next_due = self._mono() + state.every
            else:
                state.cron = Cron.parse(trigger.spec["cron"])
        with self._lock:
            if trigger.id in self._states:
                raise SwitchyardError(f"trigger {trigger.id!r} already exists")
            self._states[trigger.id] = state
        if trigger.kind == "event":
            self._bus.subscribe(f"trigger:{trigger.id}", trigger.spec["type"], self._on_event(trigger.id))

    def _on_event(self, trigger_id: str) -> Callable[[Event], None]:
        def handler(event: Event) -> None:
            self._run(trigger_id, {"type": event.type, "source": event.source, "data": dict(event.data)})

        return handler

    def remove(self, trigger_id: str) -> None:
        with self._lock:
            state = self._states.pop(trigger_id, None)
        if state is not None and state.trigger.kind == "event":
            self._bus.unsubscribe_all(f"trigger:{trigger_id}")

    def remove_owner(self, owner: str) -> None:
        with self._lock:
            ids = [i for i, s in self._states.items() if s.trigger.owner == owner]
            listeners = list(self._owner_listeners)
        for trigger_id in ids:
            self.remove(trigger_id)
        for listener in listeners:  # e.g. the schedule broker drops the module's worker (H1 B-19)
            listener(owner)

    def on_owner_removed(self, listener: Callable[[str], None]) -> None:
        with self._lock:
            self._owner_listeners.append(listener)

    @staticmethod
    def _cron_due(s: _State, minute: datetime) -> bool:
        if not s.cron or not s.cron.matches(minute):
            return False
        last = s.last_minute
        # Not again for a minute already passed, nor after a small step back of the clock (H1 B-5).
        return last is None or not last - CLOCK_STEP_BACK_TOLERANCE <= minute <= last

    def ids(self) -> list[str]:
        with self._lock:
            return sorted(self._states)

    def stats(self, trigger_id: str) -> dict[str, int]:
        with self._lock:
            return dict(self._state(trigger_id).counts)

    def _state(self, trigger_id: str) -> _State:
        state = self._states.get(trigger_id)
        if state is None:
            raise SwitchyardError(f"unknown trigger {trigger_id!r}")
        return state

    # driving ------------------------------------------------------------------------------------------

    def tick(self) -> None:
        """Run due time triggers. Call about once per second to once per minute."""
        mono, wall = self._mono(), self._now()
        minute = wall.replace(second=0, microsecond=0)
        due: list[str] = []
        with self._lock:
            for trigger_id, s in self._states.items():
                if s.every is not None and mono >= s.next_due:
                    s.next_due = mono + s.every
                    due.append(trigger_id)
                elif s.cron is not None and self._cron_due(s, minute):
                    s.last_minute = minute
                    due.append(trigger_id)
        for trigger_id in due:
            self._run(trigger_id, {"trigger": trigger_id})

    def observe(self, metric: str, value: float) -> None:
        """Feed a metric sample to usage and capacity triggers."""
        fire: list[str] = []
        with self._lock:
            for trigger_id, s in self._states.items():
                spec = s.trigger.spec
                if s.trigger.kind not in ("usage", "capacity") or spec["metric"] != metric:
                    continue
                hit = value > spec["above"] if "above" in spec else value < spec["below"]
                if hit and not s.tripped:
                    fire.append(trigger_id)
                s.tripped = hit
        for trigger_id in fire:
            self._run(trigger_id, {"metric": metric, "value": value})

    def fire(self, trigger_id: str, payload: Mapping[str, Any] | None = None) -> bool:
        """Run a trigger now (manual). Returns False if it was skipped."""
        with self._lock:
            self._state(trigger_id)
        return self._run(trigger_id, dict(payload or {"trigger": trigger_id}))

    def _skip(self, s: _State, reason: str) -> bool:
        s.counts["skipped"] += 1
        self._bus.publish(
            "core", "trigger.skipped", {"trigger": s.trigger.id, "owner": s.trigger.owner, "reason": reason}
        )
        return False

    def _run(self, trigger_id: str, payload: dict[str, Any]) -> bool:
        with self._lock:
            s = self._states.get(trigger_id)
            if s is None:
                return False
            mono = self._mono()
            if s.running:
                reason = "running"
            elif s.last_run is not None and mono - s.last_run < s.trigger.min_interval_s:
                reason = "min_interval"
            else:
                reason = ""
                s.running, s.last_run = True, mono
                s.counts["fired"] += 1
        if reason:
            return self._skip(s, reason)
        t = s.trigger
        try:
            self._bus.publish("core", "trigger.fired", {"trigger": t.id, "owner": t.owner})
            t.callback(payload)
        except Exception as exc:
            with self._lock:
                s.counts["failed"] += 1
            self._audit.append(
                actor=CORE_ACTOR,
                action="trigger.failed",
                module=t.owner,
                detail={"trigger": t.id, "error": type(exc).__name__},
            )
        finally:
            with self._lock:
                s.running = False
        return True
