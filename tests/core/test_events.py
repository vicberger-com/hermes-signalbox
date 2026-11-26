"""In-process event bus (spec section 3, Events)."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from sy_testing import RecordingAudit

from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.events import MAX_DATA_BYTES, MAX_DEPTH, Event, EventBus


def _bus(audit: RecordingAudit, **kw: Any) -> EventBus:
    return EventBus(audit, clock=lambda: "2026-11-19T00:00:00Z", **kw)


def test_publish_reaches_matching_subscribers_in_order(audit: RecordingAudit) -> None:
    bus = _bus(audit)
    seen: list[tuple[str, str]] = []
    bus.subscribe("a", "module.activated", lambda e: seen.append(("a", e.type)))
    bus.subscribe("b", "module.*", lambda e: seen.append(("b", e.type)))
    bus.subscribe("c", "*", lambda e: seen.append(("c", e.type)))
    bus.subscribe("d", "policy.denied", lambda e: seen.append(("d", e.type)))
    delivered = bus.publish("core", "module.activated", {"module": "x"})
    assert seen == [("a", "module.activated"), ("b", "module.activated"), ("c", "module.activated")]
    assert delivered == 3


def test_event_fields(audit: RecordingAudit) -> None:
    bus = _bus(audit)
    got: list[Event] = []
    bus.subscribe("a", "x.y", got.append)
    bus.publish("demo", "x.y", {"n": 1, "nested": {"k": [1, 2]}})
    [e] = got
    assert (e.type, e.source, e.ts) == ("x.y", "demo", "2026-11-19T00:00:00Z")
    assert e.data["n"] == 1 and e.data["nested"] == {"k": [1, 2]}


def test_handlers_cannot_mutate_what_others_see(audit: RecordingAudit) -> None:
    bus = _bus(audit)
    original = {"items": [1]}
    second: list[Any] = []

    def first(e: Event) -> None:
        with pytest.raises(TypeError):
            e.data["new"] = 1  # type: ignore[index]
        e.data["items"].append(99)  # nested values are copies, so this only changes this handler's copy

    bus.subscribe("a", "x.y", first)
    bus.subscribe("b", "x.y", lambda e: second.append(e.data["items"]))
    bus.publish("core", "x.y", original)
    assert second == [[1]] and original == {"items": [1]}


def test_failing_handler_is_isolated_and_audited(audit: RecordingAudit) -> None:
    failures: list[str] = []
    bus = _bus(audit, on_handler_error=lambda owner, exc: failures.append(owner))
    seen: list[str] = []

    def bad(e: Event) -> None:
        raise RuntimeError("secret-looking message sk-123")

    bus.subscribe("bad", "x.y", bad)
    bus.subscribe("good", "x.y", lambda e: seen.append("good"))
    assert bus.publish("core", "x.y", {}) == 1
    assert seen == ["good"] and failures == ["bad"]
    rec = audit.records[-1]
    assert rec["action"] == "event.handler_failed" and rec["module"] == "bad"
    assert rec["detail"] == {"type": "x.y", "error": "RuntimeError"}  # class name only, never the message


@pytest.mark.parametrize(
    "data",
    [{"x": object()}, {1: "a"}, {"big": "x" * (MAX_DATA_BYTES + 1)}, ["not", "a", "mapping"]],
    ids=["unserialisable", "int-key", "too-big", "list"],
)
def test_bad_data_is_refused(audit: RecordingAudit, data: Any) -> None:
    with pytest.raises(SignalboxError, match="event data"):
        _bus(audit).publish("core", "x.y", data)


@pytest.mark.parametrize("type_", ["", "X.y", "x..y", "x.", ".x", "x y", "x.*"])
def test_bad_event_types_are_refused(audit: RecordingAudit, type_: str) -> None:
    with pytest.raises(SignalboxError, match="event type"):
        _bus(audit).publish("core", type_, {})


@pytest.mark.parametrize("pattern", ["", "x.**", "*.x", "X", "x.*.y"])
def test_bad_patterns_are_refused(audit: RecordingAudit, pattern: str) -> None:
    with pytest.raises(SignalboxError, match="pattern"):
        _bus(audit).subscribe("a", pattern, lambda e: None)


def test_unsubscribe_all(audit: RecordingAudit) -> None:
    bus = _bus(audit)
    seen: list[str] = []
    bus.subscribe("a", "x.y", lambda e: seen.append("a"))
    bus.subscribe("b", "x.y", lambda e: seen.append("b"))
    bus.unsubscribe_all("a")
    bus.publish("core", "x.y", {})
    assert seen == ["b"]
    assert bus.subscriptions("a") == 0 and bus.subscriptions("b") == 1


def test_subscribing_during_dispatch_does_not_affect_current_event(audit: RecordingAudit) -> None:
    bus = _bus(audit)
    seen: list[str] = []

    def adder(e: Event) -> None:
        seen.append("adder")
        bus.subscribe("late", "x.y", lambda e2: seen.append("late"))

    bus.subscribe("a", "x.y", adder)
    bus.publish("core", "x.y", {})
    assert seen == ["adder"]


def test_reentrant_publish_is_depth_limited(audit: RecordingAudit) -> None:
    bus = _bus(audit)
    calls: list[int] = []

    def loop(e: Event) -> None:
        calls.append(1)
        bus.publish("loop", "x.y", {})

    bus.subscribe("loop", "x.y", loop)
    bus.publish("core", "x.y", {})
    assert len(calls) == MAX_DEPTH
    assert audit.actions().count("event.depth_exceeded") == 1


def test_threads_have_independent_depth(audit: RecordingAudit) -> None:
    bus = _bus(audit)
    count = 0
    lock = threading.Lock()

    def handler(e: Event) -> None:
        nonlocal count
        with lock:
            count += 1

    bus.subscribe("a", "x.y", handler)
    threads = [
        threading.Thread(target=lambda: [bus.publish("core", "x.y", {}) for _ in range(50)]) for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert count == 200


def test_non_finite_and_deep_data_are_refused(audit: RecordingAudit) -> None:
    bus = _bus(audit)
    with pytest.raises(SignalboxError, match="non-finite"):
        bus.publish("core", "x.y", {"n": float("nan")})
    deep: dict[str, Any] = {}
    node = deep
    for _ in range(40):
        node["k"] = {}
        node = node["k"]
    with pytest.raises(SignalboxError, match="nested"):
        bus.publish("core", "x.y", deep)


def test_default_clock(audit: RecordingAudit) -> None:
    bus = EventBus(audit)
    got: list[Event] = []
    bus.subscribe("a", "x.y", got.append)
    bus.publish("core", "x.y", {"t": (1, 2)})
    assert got[0].ts.endswith("Z") and got[0].data["t"] == [1, 2]
