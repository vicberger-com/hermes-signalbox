"""M6 supervisor (spec: README.md in this directory).

A background manager that runs deterministic checks on a schedule and keeps a list of findings: modules that
failed, a broken audit chain, quotas near or over their limit, and router requests that went out with a model
the operator had ruled out. Findings are de-duplicated, resolved automatically when the condition clears,
and new high or critical ones raise ``supervisor.alert`` (audited). No model is called: every check is
deterministic, so the supervisor makes zero LLM calls and cannot spend (``llm.*`` is not even requested).

Settings, ``[modules.supervisor]``::

    interval_seconds = 300     # 60-3600
    audit_check_hours = 24     # 1-168
    quota_warn_percent = 80    # 1-100
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from switchyard.errors import SwitchyardError

SEVERITIES = ("info", "low", "medium", "high", "critical")
KEEP_RUNS = 500
KEEP_RESOLVED = 500
MAX_FINDINGS_PER_RUN = 200


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _int_setting(cfg: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    value = cfg.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SwitchyardError(f"[modules.supervisor] {key} must be an integer from {low} to {high}")
    return value


SAFETY = frozenset({"router", "meter", "resources", "secrets", "supervisor"})


class SupervisorModule:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._was_active: set[str] = set()
        self.ctx: Any = None
        self.clock = clock
        self.settings: dict[str, int] = {}
        self._lock = threading.Lock()
        self._last_audit_check = 0.0

    # lifecycle ----------------------------------------------------------------------------------------

    def activate(self, ctx: Any) -> None:
        cfg = dict(ctx.config)
        unknown = set(cfg) - {"interval_seconds", "audit_check_hours", "quota_warn_percent"}
        if unknown:
            raise SwitchyardError(f"unknown [modules.supervisor] setting(s) {sorted(unknown)}")
        self.settings = {
            "interval_seconds": _int_setting(cfg, "interval_seconds", 300, 60, 3600),
            "audit_check_hours": _int_setting(cfg, "audit_check_hours", 24, 1, 168),
            "quota_warn_percent": _int_setting(cfg, "quota_warn_percent", 80, 1, 100),
        }
        text, num, real = "TEXT", "INTEGER", "REAL"
        ctx.state.create_table(
            "findings",
            [
                ("key", text),
                ("severity", text),
                ("source", text),
                ("message", text),
                ("first_seen", real),
                ("last_seen", real),
                ("count", num),
                ("state", text),
                ("resolved_at", real),
            ],
            primary_key=["key"],
        )
        ctx.state.create_table(
            "runs",
            [("at", real), ("duration_ms", num), ("checks", num), ("open", num), ("errors", num)],
            primary_key=["at"],
        )
        ctx.state.create_table("kv", [("key", text), ("value", text)], primary_key=["key"])
        read_only = {"report", "findings"}
        params: dict[str, dict[str, type]] = {
            "report": {},
            "findings": {"state": str, "limit": int},
            "ack": {"key": str},
            "run_now": {},
        }
        for name, spec in params.items():
            ctx.register_action(name, getattr(self, name), params=spec, read_only=name in read_only)
        ctx.register_panel("supervisor.status", self.report)
        self.ctx = ctx
        rows = self._q(f"SELECT value FROM {self._t('kv')} WHERE key = 'last_audit_check'")  # nosec B608
        self._last_audit_check = float(rows[0][0]) if rows else 0.0  # survives restarts
        ctx.schedule.every("checks", self.settings["interval_seconds"], self.run_checks)

    def deactivate(self) -> None:
        self.ctx = None

    def health(self) -> tuple[bool, str]:
        if self.ctx is None:
            return False, "stopped"
        counts = self._q(
            f"SELECT severity, count(*) FROM {self._t('findings')} WHERE state = 'open' "  # nosec B608
            "GROUP BY severity"
        )
        summary = ", ".join(f"{n} {sev}" for sev, n in sorted(counts)) or "no open findings"
        return True, summary

    # helpers ------------------------------------------------------------------------------------------

    def _q(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = self.ctx.state.execute(sql, params)
        return rows

    def _t(self, name: str) -> str:
        return str(self.ctx.state.table(name))

    def _call(self, module_id: str, action: str) -> Any:
        """A read-only action of another module, or None when that module is not running."""
        try:
            return self.ctx.call(module_id, action, {})
        except SwitchyardError:
            return None

    # checks -------------------------------------------------------------------------------------------

    def _check_modules(self) -> list[tuple[str, str, str]]:
        out = []
        active = set()
        for m in self.ctx.core.modules():
            if m["status"] == "active":
                active.add(m["id"])
            elif (m["status"] != "failed" and m["id"] in self._was_active
                  and str(m.get("stop_reason", "")).startswith("revoked")):  # fmt: skip
                # A module that ran at the last pass was stopped by a revoked grant: that can switch off a
                # safety module (router, meter) without failing it (R1 review). Idle and operator stops are
                # expected and not reported (R1 follow-up).
                out.append((f"module:{m['id']}:stopped", "high" if m["id"] in SAFETY else "medium",
                            f"module {m['id']} is {m['status']}"))  # fmt: skip
            if m["status"] == "failed":
                out.append(
                    (
                        f"module:{m['id']}:failed",
                        "high",
                        f"module {m['id']} failed: {m['error'] or 'unknown error'}",
                    )
                )
        self._was_active = active
        return out

    def _check_audit(self, now: float) -> list[tuple[str, str, str]]:
        due = now - self._last_audit_check >= self.settings["audit_check_hours"] * 3600
        if not due:
            current = self._q(
                f"SELECT key, severity, message FROM {self._t('findings')} "  # nosec B608
                "WHERE key = 'audit:chain' AND state != 'resolved'"
            )
            return [(r[0], r[1], r[2]) for r in current]  # keep the last result until the next check
        result = self.ctx.core.verify_audit()  # if this raises, the check stays due and runs next pass
        self._last_audit_check = now
        sql = f"INSERT OR REPLACE INTO {self._t('kv')} VALUES ('last_audit_check', ?)"  # nosec B608
        self._q(sql, (str(now),))
        if result["ok"]:
            return []
        return [
            (
                "audit:chain",
                "critical",
                f"audit chain broken at record {result['first_bad_seq']}: {result['reason'][:200]}",
            )
        ]

    def _check_quotas(self) -> list[tuple[str, str, str]]:
        quotas = self._call("meter", "quotas")
        out = []
        for q in (quotas or {}).get("quotas", []):
            percent = float(q.get("percent") or 0)
            if percent >= 100:
                out.append((f"quota:{q['name']}", "high", f"quota {q['name']} exhausted ({percent:.0f} %)"))
            elif percent >= self.settings["quota_warn_percent"]:
                out.append((f"quota:{q['name']}", "medium", f"quota {q['name']} at {percent:.0f} %"))
        return out

    def _check_router(self) -> list[tuple[str, str, str]]:
        status = self._call("router", "status")
        recent = (status or {}).get("recent", [])
        passed = [d for d in recent if "passed through" in str(d.get("reason", ""))]
        if not passed:
            return []
        return [
            (
                "router:passthrough",
                "medium",
                f"{len(passed)} of the last {len(recent)} requests went out with a ruled-out model",
            )
        ]

    def run_checks(self) -> dict[str, Any]:
        """One supervision pass. Each check is isolated: a failing check becomes a finding of its own."""
        if self.ctx is None:
            return {}
        with self._lock:
            start = time.monotonic()
            now = self.clock()
            found: list[tuple[str, str, str]] = []
            errors = 0
            checks: list[tuple[str, Callable[[], list[tuple[str, str, str]]]]] = [
                ("modules", self._check_modules),
                ("audit", lambda: self._check_audit(now)),
                ("quotas", self._check_quotas),
                ("router", self._check_router),
            ]
            for name, check in checks:
                try:
                    found.extend(check())
                except Exception as exc:
                    errors += 1
                    found.append(
                        (f"supervisor:check:{name}", "low", f"check {name} failed: {type(exc).__name__}")
                    )
            opened = self._store(found[:MAX_FINDINGS_PER_RUN], now)
            duration = int((time.monotonic() - start) * 1000)
            sql = f"SELECT count(*) FROM {self._t('findings')} WHERE state != 'resolved'"  # nosec B608
            open_count = self._q(sql)[0][0]
            self._q(
                f"INSERT OR REPLACE INTO {self._t('runs')} VALUES (?, ?, ?, ?, ?)",  # nosec B608
                (now, duration, len(checks), open_count, errors),
            )
            self._prune()
        for key, severity, message in opened:
            if severity in ("high", "critical"):
                self.ctx.audit("alert", finding=key[:200], severity=severity)
                self.ctx.emit("supervisor.alert", {"key": key, "severity": severity, "message": message})
            self.ctx.log("supervisor", "finding", key=key, severity=severity)
        return {"open": open_count, "new": len(opened), "duration_ms": duration, "errors": errors}

    def _store(self, found: list[tuple[str, str, str]], now: float) -> list[tuple[str, str, str]]:
        t = self._t("findings")
        seen: set[str] = set()
        opened = []
        for key, severity, message in found:
            key, message = key[:200], message[:500]
            if key in seen:
                continue
            seen.add(key)
            row = self._q(f"SELECT state, severity FROM {t} WHERE key = ?", (key,))  # nosec B608
            if row and row[0][0] != "resolved":
                state = row[0][0]
                if severity != row[0][1] and SEVERITIES.index(severity) > SEVERITIES.index(row[0][1]):
                    state = "open"  # escalated: an acknowledgement no longer covers it
                    opened.append((key, severity, message))
                self._q(
                    f"UPDATE {t} SET severity = ?, message = ?, last_seen = ?, count = count + 1, state = ? "  # nosec B608
                    "WHERE key = ?",
                    (severity, message, now, state, key),
                )
            else:
                self._q(
                    f"INSERT OR REPLACE INTO {t} VALUES (?, ?, ?, ?, ?, ?, 1, 'open', NULL)",  # nosec B608
                    (key, severity, key.split(":", 1)[0], message, now, now),
                )
                opened.append((key, severity, message))
        stale = self._q(f"SELECT key FROM {t} WHERE state != 'resolved'")  # nosec B608
        for (key,) in stale:
            if key not in seen:
                self._q(f"UPDATE {t} SET state = 'resolved', resolved_at = ? WHERE key = ?", (now, key))  # nosec B608
        return opened

    def _prune(self) -> None:
        runs = self._t("runs")
        count = self._q(f"SELECT count(*) FROM {runs}")[0][0]  # nosec B608
        if count > KEEP_RUNS:
            sql = f"SELECT at FROM {runs} ORDER BY at DESC LIMIT 1 OFFSET ?"  # nosec B608
            cutoff = self._q(sql, (KEEP_RUNS - 1,))[0][0]
            self._q(f"DELETE FROM {runs} WHERE at < ?", (cutoff,))  # nosec B608
        findings = self._t("findings")
        resolved = self._q(f"SELECT count(*) FROM {findings} WHERE state = 'resolved'")[0][0]  # nosec B608
        if resolved > KEEP_RESOLVED:
            cutoff = self._q(
                f"SELECT resolved_at FROM {findings} WHERE state = 'resolved' "  # nosec B608
                "ORDER BY resolved_at DESC LIMIT 1 OFFSET ?",
                (KEEP_RESOLVED - 1,),
            )[0][0]
            self._q(f"DELETE FROM {findings} WHERE state = 'resolved' AND resolved_at < ?", (cutoff,))  # nosec B608

    # actions ------------------------------------------------------------------------------------------

    def _rows(self, where: str, args: tuple[Any, ...], limit: int) -> list[dict[str, Any]]:
        cols = "key, severity, source, message, first_seen, last_seen, count, state, resolved_at"
        rows = self._q(
            f"SELECT {cols} FROM {self._t('findings')} WHERE {where} "  # nosec B608
            "ORDER BY last_seen DESC LIMIT ?",
            (*args, limit),
        )
        out = []
        for r in rows:
            item = dict(zip(cols.split(", "), r, strict=True))
            for k in ("first_seen", "last_seen", "resolved_at"):
                item[k] = _iso(item[k]) if item[k] else None
            out.append(item)
        out.sort(key=lambda f: -SEVERITIES.index(f["severity"]) if f["severity"] in SEVERITIES else 0)
        return out

    def report(self) -> dict[str, Any]:
        sql = f"SELECT at, duration_ms, open, errors FROM {self._t('runs')} ORDER BY at DESC LIMIT 1"  # nosec B608
        last = self._q(sql)
        return {
            "open": self._rows("state != 'resolved'", (), 100),
            "last_run": {
                "at": _iso(last[0][0]),
                "duration_ms": last[0][1],
                "open": last[0][2],
                "errors": last[0][3],
            }
            if last
            else None,
            "interval_seconds": self.settings["interval_seconds"],
            "llm_calls": 0,
        }

    def findings(self, state: str = "open", limit: int = 50) -> dict[str, Any]:
        if state not in ("open", "acked", "resolved", "all") or not 1 <= limit <= 500:
            raise SwitchyardError("state must be open, acked, resolved or all; limit 1-500")
        if state == "all":
            return {"findings": self._rows("1 = 1", (), limit)}
        return {"findings": self._rows("state = ?", (state,), limit)}

    def ack(self, key: str) -> dict[str, Any]:
        """Acknowledge an open finding: it stays listed but no longer counts as new until it escalates."""
        key = key[:200]
        rows = self._q(f"SELECT state FROM {self._t('findings')} WHERE key = ?", (key[:200],))  # nosec B608
        if not rows or rows[0][0] == "resolved":
            raise SwitchyardError(f"no open finding {key[:80]!r}")
        self._q(f"UPDATE {self._t('findings')} SET state = 'acked' WHERE key = ?", (key,))  # nosec B608
        self.ctx.audit("ack", finding=key[:200])
        return {"acked": key}

    def run_now(self) -> dict[str, Any]:
        return self.run_checks()
