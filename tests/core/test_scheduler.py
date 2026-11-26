"""Scheduler, trigger engine and cron parsing (spec section 3, Events and scheduler)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from sy_testing import RecordingAudit

from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.events import EventBus
from hermes_signalbox.scheduler import Cron, Scheduler, Trigger


class Clock:
    def __init__(self) -> None:
        self.mono = 1000.0
        self.wall = datetime(2026, 11, 19, 8, 0, 0)

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self.mono += seconds
        self.wall += timedelta(seconds=seconds)


def _setup(audit: RecordingAudit) -> tuple[Scheduler, EventBus, Clock]:
    clock = Clock()
    bus = EventBus(audit, clock=lambda: "t")
    sched = Scheduler(bus, audit, monotonic=lambda: clock.mono, now=lambda: clock.wall)
    return sched, bus, clock


def _counter() -> tuple[list[Any], Any]:
    calls: list[Any] = []
    return calls, lambda payload: calls.append(payload)


# cron -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "when", "match"),
    [
        ("* * * * *", datetime(2026, 1, 1, 0, 0), True),
        ("0 9 * * *", datetime(2026, 1, 1, 9, 0), True),
        ("0 9 * * *", datetime(2026, 1, 1, 9, 1), False),
        ("*/15 * * * *", datetime(2026, 1, 1, 3, 45), True),
        ("*/15 * * * *", datetime(2026, 1, 1, 3, 46), False),
        ("0 8-17/3 * * 1-5", datetime(2026, 11, 19, 14, 0), True),  # Thursday 14:00
        ("0 8-17/3 * * 1-5", datetime(2026, 11, 21, 14, 0), False),  # Saturday
        ("0 0 1,15 * *", datetime(2026, 2, 15, 0, 0), True),
        ("0 0 * * 0", datetime(2026, 11, 22, 0, 0), True),  # Sunday as 0
        ("0 0 * * 7", datetime(2026, 11, 22, 0, 0), True),  # Sunday as 7
        ("0 0 13 * 5", datetime(2026, 11, 20, 0, 0), True),  # dom OR dow when both are restricted: Friday
        ("0 0 13 * 5", datetime(2026, 11, 13, 0, 0), True),  # ... or the 13th
        ("0 0 13 * 5", datetime(2026, 11, 14, 0, 0), False),
        ("30 2 * 12 *", datetime(2026, 12, 3, 2, 30), True),
        ("50/5 * * * *", datetime(2026, 1, 1, 0, 55), True),  # start/step runs to the end of the range
        ("50/5 * * * *", datetime(2026, 1, 1, 0, 45), False),
    ],
)
def test_cron_matching(expr: str, when: datetime, match: bool) -> None:
    assert Cron.parse(expr).matches(when) is match


@pytest.mark.parametrize(
    "expr", ["", "* * * *", "60 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *", "* * * * 8",
             "*/0 * * * *", "*/x * * * *", "5-1 * * * *", "a * * * *", "1,,2 * * * *", "* * * * * *"],
)  # fmt: skip
def test_bad_cron_is_refused(expr: str) -> None:
    with pytest.raises(SignalboxError, match="cron"):
        Cron.parse(expr)


# validation -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "spec"),
    [
        ("time", {}),
        ("time", {"every": 0}),
        ("time", {"every": True}),
        ("time", {"every": 5, "cron": "* * * * *"}),
        ("time", {"cron": "nope"}),
        ("event", {"type": "x.**"}),
        ("event", {}),
        ("usage", {"metric": "tokens"}),
        ("usage", {"metric": "tokens", "above": 1, "below": 0}),
        ("capacity", {"metric": "", "below": 1}),
        ("capacity", {"metric": "ram", "below": "low"}),
        ("weather", {}),
    ],
)
def test_bad_trigger_specs_are_refused(audit: RecordingAudit, kind: str, spec: dict[str, Any]) -> None:
    sched, _, _ = _setup(audit)
    with pytest.raises(SignalboxError):
        sched.add(Trigger(id="t1", owner="demo", kind=kind, spec=spec, callback=lambda p: None))


def test_duplicate_ids_and_bad_names_are_refused(audit: RecordingAudit) -> None:
    sched, _, _ = _setup(audit)
    sched.add(Trigger(id="t1", owner="demo", kind="time", spec={"every": 5}, callback=lambda p: None))
    with pytest.raises(SignalboxError, match="already"):
        sched.add(Trigger(id="t1", owner="demo", kind="time", spec={"every": 5}, callback=lambda p: None))
    with pytest.raises(SignalboxError, match="trigger id"):
        sched.add(Trigger(id="Bad Id", owner="demo", kind="time", spec={"every": 5}, callback=lambda p: None))
    with pytest.raises(SignalboxError, match="min_interval"):
        sched.add(Trigger(id="t2", owner="d", kind="time", spec={"every": 5}, callback=lambda p: None,
                          min_interval_s=-1))  # fmt: skip


# time triggers --------------------------------------------------------------------------------------------


def test_every_fires_on_schedule(audit: RecordingAudit) -> None:
    sched, _, clock = _setup(audit)
    calls, cb = _counter()
    sched.add(Trigger(id="t1", owner="demo", kind="time", spec={"every": 60}, callback=cb))
    sched.tick()
    assert calls == []  # first run is one interval after adding
    clock.advance(59)
    sched.tick()
    assert calls == []
    clock.advance(1)
    sched.tick()
    sched.tick()  # same instant: no double run
    assert len(calls) == 1
    clock.advance(600)  # a long gap fires once, not ten times
    sched.tick()
    assert len(calls) == 2
    assert sched.stats("t1") == {"fired": 2, "skipped": 0, "failed": 0}


def test_cron_fires_once_per_matching_minute(audit: RecordingAudit) -> None:
    sched, _, clock = _setup(audit)
    calls, cb = _counter()
    sched.add(Trigger(id="t1", owner="demo", kind="time", spec={"cron": "*/2 * * * *"}, callback=cb))
    sched.tick()  # 08:00 matches
    clock.advance(30)
    sched.tick()  # 08:00:30, same minute
    assert len(calls) == 1
    clock.advance(30)
    sched.tick()  # 08:01 does not match
    clock.advance(60)
    sched.tick()  # 08:02 matches
    assert len(calls) == 2


def test_min_interval_skips_and_counts(audit: RecordingAudit) -> None:
    sched, bus, clock = _setup(audit)
    calls, cb = _counter()
    sched.add(
        Trigger(id="t1", owner="demo", kind="event", spec={"type": "x.y"}, callback=cb, min_interval_s=10)
    )
    bus.publish("core", "x.y", {})
    bus.publish("core", "x.y", {})
    clock.advance(10)
    bus.publish("core", "x.y", {})
    assert len(calls) == 2
    assert sched.stats("t1") == {"fired": 2, "skipped": 1, "failed": 0}


def test_event_trigger_receives_event_payload(audit: RecordingAudit) -> None:
    sched, bus, _ = _setup(audit)
    calls, cb = _counter()
    sched.add(Trigger(id="t1", owner="demo", kind="event", spec={"type": "module.*"}, callback=cb))
    bus.publish("core", "module.activated", {"module": "x"})
    bus.publish("core", "policy.denied", {})
    assert calls == [{"type": "module.activated", "source": "core", "data": {"module": "x"}}]


def test_trigger_cannot_reenter_itself(audit: RecordingAudit) -> None:
    sched, bus, _ = _setup(audit)
    calls: list[Any] = []

    def cb(payload: Any) -> None:
        calls.append(payload)
        bus.publish("demo", "x.y", {})  # would re-fire the same trigger while it runs

    sched.add(Trigger(id="t1", owner="demo", kind="event", spec={"type": "x.y"}, callback=cb))
    bus.publish("core", "x.y", {})
    assert len(calls) == 1 and sched.stats("t1")["skipped"] == 1


def test_failing_callback_is_isolated_and_audited(audit: RecordingAudit) -> None:
    sched, _, clock = _setup(audit)

    def boom(payload: Any) -> None:
        raise ValueError("token=abc")

    sched.add(Trigger(id="t1", owner="demo", kind="time", spec={"every": 1}, callback=boom))
    clock.advance(1)
    sched.tick()
    assert sched.stats("t1") == {"fired": 1, "skipped": 0, "failed": 1}
    assert audit.records[-1] == {
        "actor": "core", "action": "trigger.failed", "module": "demo",
        "detail": {"trigger": "t1", "error": "ValueError"},
    }  # fmt: skip


def test_fired_and_skipped_events_are_published(audit: RecordingAudit) -> None:
    sched, bus, clock = _setup(audit)
    seen: list[tuple[str, Any]] = []
    bus.subscribe("watch", "trigger.*", lambda e: seen.append((e.type, dict(e.data))))
    sched.add(Trigger(id="t1", owner="demo", kind="time", spec={"every": 1}, callback=lambda p: None,
                      min_interval_s=5))  # fmt: skip
    clock.advance(1)
    sched.tick()
    sched.fire("t1")  # manual run inside min_interval
    assert seen == [
        ("trigger.fired", {"trigger": "t1", "owner": "demo"}),
        ("trigger.skipped", {"trigger": "t1", "owner": "demo", "reason": "min_interval"}),
    ]


# metric triggers ------------------------------------------------------------------------------------------


def test_usage_threshold_is_edge_triggered(audit: RecordingAudit) -> None:
    sched, _, _ = _setup(audit)
    calls, cb = _counter()
    sched.add(
        Trigger(
            id="t1", owner="demo", kind="usage", spec={"metric": "tokens.day", "above": 1000}, callback=cb
        )
    )
    for value in (500, 1200, 1500, 800, 1100):
        sched.observe("tokens.day", value)
    assert [c["value"] for c in calls] == [1200, 1100]
    sched.observe("other", 99999)
    assert len(calls) == 2


def test_capacity_below_threshold(audit: RecordingAudit) -> None:
    sched, _, _ = _setup(audit)
    calls, cb = _counter()
    sched.add(Trigger(id="t1", owner="demo", kind="capacity", spec={"metric": "ram.free_ratio", "below": 0.1},
                      callback=cb))  # fmt: skip
    for value in (0.5, 0.05, 0.02, 0.3, 0.09):
        sched.observe("ram.free_ratio", value)
    assert [c["value"] for c in calls] == [0.05, 0.09]


def test_remove_and_remove_owner(audit: RecordingAudit) -> None:
    sched, bus, clock = _setup(audit)
    calls, cb = _counter()
    sched.add(Trigger(id="a1", owner="a", kind="event", spec={"type": "x.y"}, callback=cb))
    sched.add(Trigger(id="a2", owner="a", kind="time", spec={"every": 1}, callback=cb))
    sched.add(Trigger(id="b1", owner="b", kind="event", spec={"type": "x.y"}, callback=cb))
    sched.remove_owner("a")
    assert sched.ids() == ["b1"]
    bus.publish("core", "x.y", {})
    clock.advance(5)
    sched.tick()
    assert len(calls) == 1
    sched.remove("b1")
    sched.remove("b1")  # idempotent
    assert sched.ids() == []
    with pytest.raises(SignalboxError, match="unknown trigger"):
        sched.fire("b1")
    with pytest.raises(SignalboxError, match="unknown trigger"):
        sched.stats("b1")


@pytest.mark.parametrize(
    ("kind", "spec"),
    [
        ("time", {"every": float("nan")}),
        ("time", {"every": float("inf")}),
        ("usage", {"metric": "m", "above": float("nan")}),
        ("capacity", {"metric": "m", "below": float("-inf")}),
    ],
)
def test_h1_b21_non_finite_numbers_are_refused(kind: str, spec: dict[str, Any]) -> None:
    sched = Scheduler(EventBus(RecordingAudit()), RecordingAudit())
    with pytest.raises(SignalboxError):
        sched.add(Trigger(id="t1", owner="demo", kind=kind, spec=spec, callback=lambda p: None))
    with pytest.raises(SignalboxError):
        sched.add(Trigger(id="t2", owner="demo", kind="time", spec={"every": 5}, callback=lambda p: None,
                          min_interval_s=float("nan")))  # fmt: skip
