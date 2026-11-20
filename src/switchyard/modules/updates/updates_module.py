"""M12 scheduled update checks (spec: README.md in this directory; ADR-0011).

Every ``interval_hours`` the module asks the core (``ctx.core.update_checks()``, ``core.read``) to compare
each git-installed module's installed commit with the head of its update channel, and announces each newly
available commit once (``notify``). It cannot fetch, preview or apply updates: those are operator commands
(``module preview`` and ``module update``).

Settings, ``[modules.updates]``::

    interval_hours = 24     # 1-168
"""

from __future__ import annotations

import threading
import time
from typing import Any

from switchyard.errors import SwitchyardError


class UpdatesModule:
    def __init__(self) -> None:
        self.ctx: Any = None
        self._lock = threading.Lock()
        self._checking = threading.Lock()
        self._last: dict[str, Any] = {"checked_at": None, "modules": []}
        self._announced: set[tuple[str, str]] = set()

    def activate(self, ctx: Any) -> None:
        cfg = dict(ctx.config)
        if set(cfg) - {"interval_hours"}:
            raise SwitchyardError(
                f"unknown [modules.updates] setting(s) {sorted(set(cfg) - {'interval_hours'})}"
            )
        hours = cfg.get("interval_hours", 24)
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 168:
            raise SwitchyardError("[modules.updates] interval_hours must be an integer from 1 to 168")
        ctx.register_action("report", self.report, params={}, read_only=True)
        ctx.register_action("check_now", self.check_now, params={}, read_only=False)
        ctx.register_panel("updates.status", self.report)
        ctx.schedule.every("check", hours * 3600, self.check_now)
        self.ctx = ctx

    def deactivate(self) -> None:
        self.ctx = None

    def health(self) -> tuple[bool, str]:
        return (self.ctx is not None, "running" if self.ctx is not None else "stopped")

    def report(self) -> dict[str, Any]:
        with self._lock:
            return {
                "checked_at": self._last["checked_at"],
                "modules": [dict(m) for m in self._last["modules"]],
            }

    def check_now(self) -> dict[str, Any]:
        ctx = self.ctx
        if ctx is None:
            return {"skipped": "not running"}
        if not self._checking.acquire(blocking=False):
            return {"skipped": "a check is already running"}
        try:
            rows = ctx.core.update_checks(max_age_s=0)  # fresh, within the core's minimum interval
        finally:
            self._checking.release()
        available = errors = 0
        for row in rows:
            if row.get("error"):
                errors += 1
                continue
            if not row.get("update"):
                continue
            available += 1
            key = (str(row["id"]), str(row["available"]))
            if key in self._announced:
                continue
            self._announced.add(key)
            if ctx.has("notify"):
                ctx.notify.send("info", f"update available: {row['id']} ({row['channel']} {key[1][:12]})")
        with self._lock:
            self._last = {"checked_at": int(time.time()), "modules": rows}
        ctx.audit("checked", modules=str(len(rows)), available=str(available), errors=str(errors))
        return {"modules": len(rows), "available": available, "errors": errors}
