"""Module schedules: the ``schedule`` capability (``ctx.schedule``), ADR-0006.

A thin facade over the core ``Scheduler``: a module registers named repeating jobs; ids are namespaced
``<module>.<name>``, the scheduler skips a run while the previous one is still going, failures are counted,
and every job of a module is removed when it stops (``Scheduler.remove_owner``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from switchyard.errors import SwitchyardError
from switchyard.scheduler import Scheduler, Trigger

_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
MIN_SECONDS, MAX_SECONDS = 10, 86_400


class ScheduleBroker:
    def __init__(self, scheduler: Scheduler) -> None:
        self._scheduler = scheduler

    def for_module(self, module_id: str) -> ModuleSchedule:
        return ModuleSchedule(self._scheduler, module_id)


class ModuleSchedule:
    """What ``ctx.schedule`` returns."""

    __slots__ = ("_module_id", "_scheduler")

    def __init__(self, scheduler: Scheduler, module_id: str) -> None:
        self._scheduler = scheduler
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
            fn()

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
