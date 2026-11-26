"""M9 inbox (spec: README.md in this directory).

Stores operator notifications: ``core.notify`` (any module with ``notify``) and alert events from the bundled
modules. The dashboard shows them; nothing is sent anywhere. Listing is human-only: notification text comes
from modules and is meant for the operator, not the model.

Settings, ``[modules.inbox]``::

    min_severity = "low"   # info, low, medium, high, critical: lower ones are dropped
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from typing import Any

from hermes_signalbox.errors import SignalboxError

SEVERITIES = ("info", "low", "medium", "high", "critical")
KEEP = 1000
# event type -> (default severity, title)
SOURCES: dict[str, tuple[str, str]] = {
    "core.notify": ("info", ""),
    "supervisor.alert": ("high", "Supervisor alert"),
    "meter.exhausted": ("high", "Quota exhausted"),
    "meter.threshold": ("medium", "Quota threshold reached"),
    "workers.stuck": ("medium", "Worker running too long"),
    "workers.loop": ("low", "Repeated delegation refused"),
    "module.failed": ("high", "Module failed"),
}
STATES = ("open", "acked", "all")


def _line(text: object, limit: int) -> str:
    return " ".join(str(text).split())[:limit]


class InboxModule:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.ctx: Any = None
        self.clock = clock
        self.min_severity = "low"
        self._lock = threading.Lock()

    def activate(self, ctx: Any) -> None:
        cfg = dict(ctx.config)
        extra = set(cfg) - {"min_severity"}
        if extra:
            raise SignalboxError(f"unknown [modules.inbox] setting(s) {sorted(extra)}")
        self.min_severity = cfg.get("min_severity", "low")
        if self.min_severity not in SEVERITIES:
            raise SignalboxError(f"[modules.inbox] min_severity must be one of {list(SEVERITIES)}")
        ctx.state.create_table(
            "items",
            [
                ("id", "TEXT"),
                ("at", "REAL"),
                ("module", "TEXT"),
                ("type", "TEXT"),
                ("severity", "TEXT"),
                ("title", "TEXT"),
                ("detail", "TEXT"),
                ("state", "TEXT"),
            ],
            primary_key=["id"],
        )
        actions: dict[str, dict[str, type]] = {
            "list": {"state": str, "limit": int},
            "ack": {"id": str},
            "ack_all": {},
        }
        for name, params in actions.items():
            ctx.register_action(name, getattr(self, name), params=params, read_only=False)
        ctx.register_panel("inbox.status", self.status)
        self.ctx = ctx
        for event_type in SOURCES:
            ctx.subscribe(event_type, self.on_event)

    def deactivate(self) -> None:
        self.ctx = None

    def health(self) -> tuple[bool, str]:
        if self.ctx is None:
            return False, "stopped"
        return True, f"{self._count('open')} open"

    def _t(self) -> str:
        return str(self.ctx.state.table("items"))

    def _count(self, state: str) -> int:
        rows = self.ctx.state.execute(f"SELECT count(*) FROM {self._t()} WHERE state = ?", (state,))  # nosec B608
        return int(rows[0][0])

    def on_event(self, event: Any) -> None:
        if self.ctx is None:
            return
        data = dict(getattr(event, "data", {}) or {})
        event_type = str(getattr(event, "type", ""))
        if event_type == "core.notify" and getattr(event, "source", "") != "core":
            return  # only the notify broker may publish it
        default, title = SOURCES.get(event_type, ("info", event_type))
        severity = data.get("severity") if data.get("severity") in SEVERITIES else default
        if SEVERITIES.index(severity) < SEVERITIES.index(self.min_severity):
            return
        module = _line(data.get("module") or getattr(event, "source", "") or "", 32)
        if event_type == "core.notify":
            title, detail = _line(data.get("title", ""), 120), _line(data.get("detail", ""), 500)
        else:
            parts = [
                f"{k}={_line(v, 80)}" for k, v in sorted(data.items()) if k not in ("severity", "module")
            ]
            detail = _line(", ".join(parts), 500)
        with self._lock:
            t = self._t()
            self.ctx.state.execute(
                f"INSERT INTO {t} VALUES (?, ?, ?, ?, ?, ?, ?, 'open')",  # nosec B608
                (secrets.token_hex(8), self.clock(), module, event_type, severity, title, detail),
            )
            count = self.ctx.state.execute(f"SELECT count(*) FROM {t}")[0][0]  # nosec B608
            if count > KEEP:  # acked first, then least severe, then oldest (M9 review: a flood of low items
                # must not evict an unacknowledged critical alert)
                rank = (
                    "CASE severity WHEN 'info' THEN 0 WHEN 'low' THEN 1 WHEN 'medium' THEN 2 "
                    "WHEN 'high' THEN 3 ELSE 4 END"
                )
                sql = (
                    f"DELETE FROM {t} WHERE id IN (SELECT id FROM {t} "  # nosec B608
                    f"ORDER BY state = 'open', {rank}, at LIMIT ?)"
                )
                self.ctx.state.execute(sql, (count - KEEP,))

    def list(self, state: str = "open", limit: int = 50) -> dict[str, Any]:
        if state not in STATES:
            raise SignalboxError(f"state must be one of {list(STATES)}")
        if not 1 <= limit <= 500:
            raise SignalboxError("limit must be from 1 to 500")
        where, args = ("", ()) if state == "all" else (" WHERE state = ?", (state,))
        cols = "id, at, module, type, severity, title, detail, state"
        sql = f"SELECT {cols} FROM {self._t()}{where} ORDER BY at DESC LIMIT ?"  # nosec B608
        rows = self.ctx.state.execute(sql, (*args, limit))
        keys = ("id", "at", "module", "type", "severity", "title", "detail", "state")
        return {"items": [dict(zip(keys, row, strict=True)) for row in rows]}

    def ack(self, id: str) -> dict[str, Any]:
        with self._lock:
            found = self.ctx.state.execute(f"SELECT state FROM {self._t()} WHERE id = ?", (id[:32],))  # nosec B608
            if not found:
                raise SignalboxError("no such notification")
            self.ctx.state.execute(f"UPDATE {self._t()} SET state = 'acked' WHERE id = ?", (id[:32],))  # nosec B608
        return {"acked": id[:32]}

    def ack_all(self) -> dict[str, Any]:
        with self._lock:
            n = self._count("open")
            self.ctx.state.execute(f"UPDATE {self._t()} SET state = 'acked' WHERE state = 'open'")  # nosec B608
        self.ctx.audit("ack_all", count=str(n))
        return {"acked": n}

    def status(self) -> dict[str, Any]:
        sql = f"SELECT severity, count(*) FROM {self._t()} WHERE state = 'open' GROUP BY severity"  # nosec B608
        return {"open": dict(self.ctx.state.execute(sql)), "latest": self.list("open", 20)["items"]}
