"""1.1 backlog batch 10: the scheduler (H1 B-5 #98, B-19 #110)."""

from __future__ import annotations

import threading
import time
from datetime import datetime

from sy_testing import RecordingAudit

from hermes_signalbox.events import EventBus
from hermes_signalbox.schedule import ScheduleBroker
from hermes_signalbox.scheduler import Scheduler, Trigger


class _Clock:
    def __init__(self, wall: datetime) -> None:
        self.wall = wall
        self.mono = 1000.0


def _cron(clock: _Clock, expr: str) -> tuple[Scheduler, list[datetime]]:
    sched = Scheduler(EventBus(RecordingAudit()), RecordingAudit(), monotonic=lambda: clock.mono,
                      now=lambda: clock.wall)  # fmt: skip
    fired: list[datetime] = []
    trigger = Trigger(
        id="t", owner="demo", kind="time", spec={"cron": expr}, callback=lambda p: fired.append(clock.wall)
    )
    sched.add(trigger)
    return sched, fired


def test_h1_b5_a_clock_step_back_does_not_fire_the_job_again() -> None:
    clock = _Clock(datetime(2026, 11, 20, 10, 5))
    sched, fired = _cron(clock, "5 * * * *")
    sched.tick()
    clock.wall = datetime(2026, 11, 20, 9, 5)  # NTP correction or DST fall-back: an hour back
    sched.tick()
    clock.wall = datetime(2026, 11, 20, 10, 5)  # the same minute again
    sched.tick()
    assert len(fired) == 1
    clock.wall = datetime(2026, 11, 20, 11, 5)
    sched.tick()
    assert len(fired) == 2


def test_h1_b5_a_large_correction_resets_so_jobs_do_not_stop_for_days() -> None:
    clock = _Clock(datetime(2026, 11, 22, 10, 5))  # the clock was two days ahead
    sched, fired = _cron(clock, "5 * * * *")
    sched.tick()
    clock.wall = datetime(2026, 11, 20, 10, 5)  # corrected
    sched.tick()
    assert len(fired) == 2


def test_h1_b19_removing_a_module_releases_its_job_worker() -> None:
    audit = RecordingAudit()
    sched = Scheduler(EventBus(audit), audit)
    broker = ScheduleBroker(sched, audit, timeout=5)
    ran = threading.Event()
    broker.run("demo", "demo.job", ran.set)
    assert ran.wait(5)
    workers = lambda: [t for t in threading.enumerate() if t.name.startswith("sy-job-demo")]  # noqa: E731
    assert workers()
    sched.remove_owner("demo")
    deadline = time.monotonic() + 5
    while workers() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not workers()
    ran.clear()
    broker.run("demo", "demo.job", ran.set)  # a module activated again gets a fresh worker
    assert ran.wait(5)
    broker.close()
