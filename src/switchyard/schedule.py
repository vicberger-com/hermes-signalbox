"""Module schedules: the ``schedule`` capability (``ctx.schedule``), ADR-0006.

A thin facade over the core ``Scheduler``: a module registers named repeating jobs; ids are namespaced
``<module>.<name>``, the scheduler skips a run while the previous one is still going, failures are counted,
and every job of a module is removed when it stops (``Scheduler.remove_owner``).
"""

from __future__ import annotations

import concurrent.futures
import re
import threading
from collections.abc import Callable
from typing import Any

from switchyard.capabilities import CORE_ACTOR, AuditSink
from switchyard.errors import SwitchyardError
from switchyard.scheduler import Scheduler, Trigger

_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
MIN_SECONDS, MAX_SECONDS = 10, 86_400


RUN_TIMEOUT = 5.0


class ScheduleBroker:
    def __init__(self, scheduler: Scheduler, audit: AuditSink, timeout: float = RUN_TIMEOUT) -> None:
        self._scheduler = scheduler
        self._audit = audit
        self.timeout = timeout
        self._pools: dict[str, concurrent.futures.ThreadPoolExecutor] = {}
        self._inflight: dict[str, concurrent.futures.Future[Any]] = {}
        self._lock = threading.Lock()
        scheduler.on_owner_removed(self.release)

    def release(self, module_id: str) -> None:
        """Drop the module's worker when its jobs are removed (H1 B-19); a later job starts a fresh one."""
        with self._lock:
            pool = self._pools.pop(module_id, None)
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    def for_module(self, module_id: str) -> ModuleSchedule:
        return ModuleSchedule(self, module_id)

    def run(self, module_id: str, trigger_id: str, fn: Callable[[], Any]) -> None:
        """Run one job on the module's own worker, waiting at most ``timeout`` (M6 review): a slow job cannot
        stall the tick, and a job still running from last time is skipped rather than stacked."""
        with self._lock:
            previous = self._inflight.get(trigger_id)
            skipped = previous is not None and not previous.done()
        if skipped:  # a job still running from last time is visible, not silent (M10 review)
            self._audit.append(
                actor=CORE_ACTOR, action="module.job_skipped", module=module_id, detail={"job": trigger_id}
            )
            return
        with self._lock:
            pool = self._pools.get(module_id)
            if pool is None:
                pool = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix=f"sy-job-{module_id}"
                )
                self._pools[module_id] = pool
            future = pool.submit(fn)
            self._inflight[trigger_id] = future
        try:
            future.result(timeout=self.timeout)
        except concurrent.futures.TimeoutError:
            self._audit.append(
                actor=CORE_ACTOR,
                action="module.job_timeout",
                module=module_id,
                detail={"job": trigger_id, "seconds": str(self.timeout)},
            )

    def close(self) -> None:
        with self._lock:
            pools, self._pools = list(self._pools.values()), {}
        for pool in pools:
            pool.shutdown(wait=False, cancel_futures=True)


class ModuleSchedule:
    """What ``ctx.schedule`` returns."""

    __slots__ = ("_broker", "_module_id", "_scheduler")

    def __init__(self, broker: ScheduleBroker, module_id: str) -> None:
        self._broker = broker
        self._scheduler = broker._scheduler
        self._module_id = module_id

    def every(self, name: str, seconds: int, fn: Callable[[], Any]) -> str:
        """Run ``fn()`` every ``seconds`` (10 to 86400) on the core tick. Returns the trigger id."""
        if not isinstance(name, str) or not _NAME.match(name):
            raise SwitchyardError(f"invalid schedule name {str(name)[:40]!r}")
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, int)
            or not MIN_SECONDS <= seconds <= MAX_SECONDS
        ):
            raise SwitchyardError(f"seconds must be an integer from {MIN_SECONDS} to {MAX_SECONDS}")
        trigger_id = f"{self._module_id}.{name}"

        def run(_payload: Any) -> None:
            self._broker.run(self._module_id, trigger_id, fn)

        self._scheduler.add(
            Trigger(
                id=trigger_id,
                owner=self._module_id,
                kind="time",
                spec={"every": seconds},
                callback=run,
                min_interval_s=seconds / 2,
            )
        )
        return trigger_id

    def cancel(self, name: str) -> None:
        self._scheduler.remove(f"{self._module_id}.{name}")

    def stats(self, name: str) -> dict[str, int]:
        return self._scheduler.stats(f"{self._module_id}.{name}")
