"""M10 scanner connectors (spec: README.md in this directory).

Runs external security scanners (gitleaks, bandit, pip-audit, osv-scanner, semgrep, trivy) as separate
processes through the ``process.spawn`` broker, on a schedule or on demand, against operator-configured
targets. Findings are normalised, de-duplicated and stored; new high and critical findings are announced
through ``notify``. A scanner that is missing, times out, exits unexpectedly or prints output that does not
parse is itself a finding (``scanner:<name>:failed``): failure is reported, never silent.

Settings, ``[modules.scanner]``::

    targets = ["C:/src/project"]   # absolute directories (required to scan anything)
    scanners = ["gitleaks", "bandit", "pip-audit", "osv-scanner", "semgrep", "trivy"]
    interval_hours = 24            # 1-168
    timeout_seconds = 300          # 10-600
    semgrep_config = "p/security-audit"
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.modkit import StateTables

from .parsers import MAX_FINDINGS, MAX_OUTPUT, SCANNERS, SEVERITIES, ParseError, clean

KEEP_RESOLVED = 5000
KEEP_RUNS = 500


def _int(cfg: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    value = cfg.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SignalboxError(f"[modules.scanner] {key} must be an integer from {low} to {high}")
    return value


class ScannerModule(StateTables):
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.ctx: Any = None
        self.clock = clock
        self.settings: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._scanning = threading.Lock()

    def activate(self, ctx: Any) -> None:
        cfg = dict(ctx.config)
        known = {"targets", "scanners", "interval_hours", "timeout_seconds", "semgrep_config"}
        if set(cfg) - known:
            raise SignalboxError(f"unknown [modules.scanner] setting(s) {sorted(set(cfg) - known)}")
        targets = cfg.get("targets", [])
        if (
            not isinstance(targets, list)
            or len(targets) > 32
            or not all(isinstance(t, str) and Path(t).is_absolute() and "\x00" not in t for t in targets)
        ):
            raise SignalboxError("[modules.scanner] targets must be a list of absolute paths")
        scanners = cfg.get("scanners", sorted(SCANNERS))
        if not isinstance(scanners, list) or not scanners or not set(scanners) <= set(SCANNERS):
            raise SignalboxError(f"[modules.scanner] scanners must be a list from {sorted(SCANNERS)}")
        semgrep_config = cfg.get("semgrep_config", "p/security-audit")
        if not isinstance(semgrep_config, str) or not semgrep_config or semgrep_config.startswith("-"):
            raise SignalboxError("[modules.scanner] semgrep_config must be a rule set name or path")
        self.settings = {
            "targets": targets,
            "scanners": scanners,
            "semgrep_config": semgrep_config,
            "interval_hours": _int(cfg, "interval_hours", 24, 1, 168),
            "timeout_seconds": _int(cfg, "timeout_seconds", 300, 10, 600),
        }
        text, real, num = "TEXT", "REAL", "INTEGER"
        ctx.state.create_table(
            "findings",
            [
                ("key", text),
                ("scanner", text),
                ("rule", text),
                ("severity", text),
                ("target", text),
                ("path", text),
                ("line", num),
                ("title", text),
                ("first_seen", real),
                ("last_seen", real),
                ("state", text),
            ],
            primary_key=["key"],
        )
        ctx.state.create_table(
            "runs",
            [
                ("id", text),
                ("at", real),
                ("scanner", text),
                ("target", text),
                ("outcome", text),
                ("findings", num),
                ("seconds", real),
            ],
            primary_key=["id"],
        )
        params: dict[str, dict[str, type]] = {
            "report": {},
            "findings": {"state": str, "limit": int},
            "run_now": {},
        }
        for name, spec in params.items():
            ctx.register_action(name, getattr(self, name), params=spec, read_only=name == "report")
        ctx.register_panel("scanner.status", self.report)
        self.ctx = ctx
        ctx.schedule.every("scan", self.settings["interval_hours"] * 3600, self.scan_all)

    def deactivate(self) -> None:
        self.ctx = None

    def health(self) -> tuple[bool, str]:
        if self.ctx is None:
            return False, "stopped"
        failed = self._q(
            f"SELECT count(*) FROM {self._t('findings')} WHERE state = 'open' "  # nosec B608
            "AND scanner = 'scanner'"
        )[0][0]
        return failed == 0, f"{failed} scanner failure(s)" if failed else "ok"

    # scanning -----------------------------------------------------------------------------------------

    def scan_all(self) -> dict[str, Any]:
        """Run every configured scanner against every target. One scan at a time: a scheduled run and
        ``run_now`` never overlap (M10 review). Returns counts."""
        if self.ctx is None:
            return {}
        if not self._scanning.acquire(blocking=False):
            return {"skipped": "a scan is already running"}
        try:
            self._forget_unconfigured()
            summary = {"runs": 0, "failures": 0, "new": 0}
            for target in self.settings["targets"]:
                for name in self.settings["scanners"]:
                    if self.ctx is None:  # deactivated mid-scan
                        return summary
                    ok, new = self._scan(name, target)
                    summary["runs"] += 1
                    summary["failures"] += 0 if ok else 1
                    summary["new"] += new
            return summary
        finally:
            self._scanning.release()

    def _forget_unconfigured(self) -> None:
        """Resolve findings and failures of scanners or targets no longer configured (M10 review)."""
        t = self._t("findings")
        configured = {(n, tg) for n in self.settings["scanners"] for tg in self.settings["targets"]}
        with self._lock:
            rows = self._q(f"SELECT key, scanner, rule, target FROM {t} WHERE state != 'resolved'")  # nosec B608
            for key, scanner, rule, target in rows:
                name = rule.rsplit(":failed", 1)[0] if scanner == "scanner" else scanner
                if (name, target) not in configured:
                    self._q(f"UPDATE {t} SET state = 'resolved' WHERE key = ?", (key,))  # nosec B608

    def _scan(self, name: str, target: str) -> tuple[bool, int]:
        build, parse, ok_codes = SCANNERS[name]
        started = self.clock()
        outcome, findings = "ok", []
        try:
            done = self.ctx.spawn.run(
                build(target, self.settings), timeout=self.settings["timeout_seconds"], max_output=MAX_OUTPUT
            )
            if getattr(done, "truncated", False):
                outcome = "output too large"
            elif done.returncode not in ok_codes:
                outcome = f"exit {done.returncode}"
            else:
                findings = parse(done.stdout)
                if len(findings) > MAX_FINDINGS:  # partial results must not resolve anything (M10 review)
                    outcome, findings = f"truncated: more than {MAX_FINDINGS} findings", []
        except SignalboxError as exc:  # missing program, timeout, could not start, not granted
            outcome = " ".join(str(exc).split())[:120]
        except ParseError as exc:
            outcome = str(exc)[:120]
        except Exception as exc:  # anything else is a failure too, and the other scanners still run
            outcome = f"error: {type(exc).__name__}"
        with self._lock:
            if self.ctx is None:
                return False, 0
            new = self._store(name, target, outcome, findings, started)
        return outcome == "ok", new

    def _store(
        self, name: str, target: str, outcome: str, findings: list[dict[str, Any]], started: float
    ) -> int:
        now = self.clock()
        t = self._t("findings")
        fail_key = hashlib.sha256(f"fail|{name}|{target}".encode()).hexdigest()[:32]
        new_alerts: list[tuple[str, str]] = []
        if outcome != "ok":
            # failure is a finding of its own; the scanner's previous findings stay as they were
            if not self._q(f"SELECT 1 FROM {t} WHERE key = ? AND state = 'open'", (fail_key,)):  # nosec B608
                new_alerts.append(("medium", f"{name} failed on {target}: {outcome}"))
            self._q(
                f"INSERT OR REPLACE INTO {t} VALUES (?, 'scanner', ?, 'medium', ?, '', 0, ?, "  # nosec B608
                "COALESCE((SELECT first_seen FROM " + t + " WHERE key = ?), ?), ?, 'open')",
                (fail_key, f"{name}:failed", target, f"{name}: {outcome}", fail_key, now, now),
            )
        else:
            self._q(f"UPDATE {t} SET state = 'resolved' WHERE key = ?", (fail_key,))  # nosec B608
            seen = set()
            for f in findings:
                key = hashlib.sha256(
                    f"{name}|{target}|{f['rule']}|{f['path']}|{f['line']}".encode()
                ).hexdigest()[:32]
                seen.add(key)
                row = self._q(f"SELECT state FROM {t} WHERE key = ?", (key,))  # nosec B608
                fresh = not row or row[0][0] == "resolved"
                if fresh and SEVERITIES.index(f["severity"]) >= SEVERITIES.index("high"):
                    new_alerts.append((f["severity"], f"{name}: {f['rule']} in {f['path']}"))
                self._q(
                    f"INSERT OR REPLACE INTO {t} VALUES (?, ?, ?, ?, ?, ?, ?, ?, "  # nosec B608
                    "COALESCE((SELECT first_seen FROM " + t + " WHERE key = ?), ?), ?, "
                    "CASE WHEN (SELECT state FROM "
                    + t
                    + " WHERE key = ?) = 'acked' THEN 'acked' ELSE 'open' END)",
                    (
                        key,
                        name,
                        f["rule"],
                        f["severity"],
                        target,
                        f["path"],
                        f["line"],
                        f["title"],
                        key,
                        now,
                        now,
                        key,
                    ),
                )
            # findings this scanner no longer reports for this target are resolved
            for (key,) in self._q(
                f"SELECT key FROM {t} WHERE scanner = ? AND target = ? AND state != 'resolved'",  # nosec B608
                (name, target),
            ):
                if key not in seen:
                    self._q(f"UPDATE {t} SET state = 'resolved' WHERE key = ?", (key,))  # nosec B608
        runs = self._t("runs")
        self._q(
            f"INSERT INTO {runs} VALUES (?, ?, ?, ?, ?, ?, ?)",  # nosec B608
            (
                hashlib.sha256(f"{started}|{name}|{target}|{now}".encode()).hexdigest()[:16],
                started,
                name,
                target,
                outcome,
                len(findings),
                round(now - started, 3),
            ),
        )
        self._q(
            f"DELETE FROM {runs} WHERE id IN (SELECT id FROM {runs} ORDER BY at DESC LIMIT -1 OFFSET ?)",  # nosec B608
            (KEEP_RUNS,),
        )
        self._q(
            f"DELETE FROM {t} WHERE key IN (SELECT key FROM {t} WHERE state = 'resolved' "  # nosec B608
            "ORDER BY last_seen DESC LIMIT -1 OFFSET ?)",
            (KEEP_RESOLVED,),
        )
        self.ctx.audit(
            "scan", scanner=name, outcome="ok" if outcome == "ok" else "failed", findings=str(len(findings))
        )
        for severity, title in new_alerts[:20]:
            self._announce(severity, title)
        if len(new_alerts) > 20:
            self._announce("high", f"{len(new_alerts) - 20} more new findings from {name}")
        return len(new_alerts)

    def _announce(self, severity: str, title: str) -> None:
        title = clean(title, 200)  # repository text: no control characters (M10 review)
        self.ctx.emit("scanner.finding", {"severity": severity, "title": title})
        if self.ctx.has("notify"):
            self.ctx.notify.send(severity, title[:120])

    # actions ------------------------------------------------------------------------------------------

    def report(self) -> dict[str, Any]:
        counts = self._q(
            f"SELECT scanner, severity, count(*) FROM {self._t('findings')} "  # nosec B608
            "WHERE state = 'open' GROUP BY scanner, severity"
        )
        sql = f"SELECT scanner, target, outcome, at FROM {self._t('runs')} ORDER BY at DESC LIMIT 20"  # nosec B608
        last = self._q(sql)
        return {
            "open": [{"scanner": s, "severity": v, "count": n} for s, v, n in counts],
            "recent_runs": [{"scanner": s, "target": t, "outcome": o, "at": a} for s, t, o, a in last],
            "targets": len(self.settings["targets"]),
            "scanners": self.settings["scanners"],
        }

    def findings(self, state: str = "open", limit: int = 100) -> dict[str, Any]:
        if state not in ("open", "acked", "resolved", "all"):
            raise SignalboxError("state must be open, acked, resolved or all")
        if not 1 <= limit <= 1000:
            raise SignalboxError("limit must be from 1 to 1000")
        where, args = ("", ()) if state == "all" else (" WHERE state = ?", (state,))
        rows = self._q(
            f"SELECT key, scanner, rule, severity, target, path, line, title, state FROM "  # nosec B608
            f"{self._t('findings')}{where} ORDER BY last_seen DESC LIMIT ?",
            (*args, limit),
        )
        keys = ("key", "scanner", "rule", "severity", "target", "path", "line", "title", "state")
        return {"findings": [dict(zip(keys, r, strict=True)) for r in rows]}

    def run_now(self) -> dict[str, Any]:
        if not self.settings["targets"]:
            raise SignalboxError("no targets: set [modules.scanner] targets")
        return self.scan_all()
