"""M7 workers, personas and teams (spec: README.md in this directory).

Roles bind a Hermes ``delegate_task`` task to a model pool (resources consumer ``subagent:<role>``, chosen by
the router: free first, paid only by the router's rules *and* this module's ``llm.paid`` grant) or to a Hermes
profile (a persona: its own model, skills, SOUL.md and tool policy). Teams group roles. A ledger records each
routed task and the subagent it became (linked by a digest of the goal: the module never sees goal text),
survives restarts, flags workers running past their role's limit (``workers.stuck``), and refuses a task
delegated again and again (loop detection).

Settings, ``[modules.workers]``::

    default_role = ""          # role used when the model gives none; "" = worker_role is required
    loop_window_minutes = 10   # 1-1440
    loop_limit = 3             # 2-20: routes of the same goal within the window before refusing
    check_seconds = 60         # 10-3600: stuck-worker check interval
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from collections.abc import Callable
from functools import partial
from typing import Any

from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.modkit import StateTables, int_setting

_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_PROFILE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
TIER_TOKENS = {"T1": 1000, "T2": 4000, "T3": 16000, "T4": 64000, "T5": 200000}
MAX_ROLES = 64
MAX_TEAMS = 32
KEEP_ROUTES = 5000
KEEP_RUNS = 5000
LINK_WINDOW = 600.0
STATES = ("running", "stuck", "done", "failed", "all")


def _check(pattern: re.Pattern[str], value: str, what: str) -> None:
    if not isinstance(value, str) or not pattern.match(value):
        raise SignalboxError(f"invalid {what}")


def _line(text: str, limit: int) -> str:
    return " ".join(str(text).split())[:limit]


_int_setting = partial(int_setting, "workers")


class WorkersModule(StateTables):
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.ctx: Any = None
        self.clock = clock
        self.settings: dict[str, Any] = {}
        self._lock = threading.Lock()

    # lifecycle ----------------------------------------------------------------------------------------

    def activate(self, ctx: Any) -> None:
        cfg = dict(ctx.config)
        unknown = set(cfg) - {"default_role", "loop_window_minutes", "loop_limit", "check_seconds"}
        if unknown:
            raise SignalboxError(f"unknown [modules.workers] setting(s) {sorted(unknown)}")
        default_role = cfg.get("default_role", "")
        if default_role != "":
            _check(_NAME, default_role, "[modules.workers] default_role")
        self.settings = {
            "default_role": default_role,
            "loop_window_minutes": _int_setting(cfg, "loop_window_minutes", 10, 1, 1440),
            "loop_limit": _int_setting(cfg, "loop_limit", 3, 2, 20),
            "check_seconds": _int_setting(cfg, "check_seconds", 60, 10, 3600),
        }
        text, num, real = "TEXT", "INTEGER", "REAL"
        ctx.state.create_table(
            "roles",
            [
                ("name", text),
                ("description", text),
                ("profile", text),
                ("tier", text),
                ("max_minutes", num),
                ("paid", num),
            ],
            primary_key=["name"],
        )
        ctx.state.create_table(
            "teams", [("name", text), ("roles", text), ("description", text)], primary_key=["name"]
        )
        ctx.state.create_table(
            "routes",
            [
                ("id", text),
                ("at", real),
                ("role", text),
                ("goal_sha", text),
                ("target", text),
                ("outcome", text),
                ("linked", num),
            ],
            primary_key=["id"],
        )
        ctx.state.create_table(
            "runs",
            [
                ("child", text),
                ("role", text),
                ("goal_sha", text),
                ("target", text),
                ("started_at", real),
                ("ended_at", real),
                ("status", text),
                ("duration_ms", num),
            ],
            primary_key=["child"],
        )
        read_only = {"report", "roles", "teams", "ledger"}
        params: dict[str, dict[str, type]] = {
            "report": {},
            "roles": {},
            "teams": {},
            "ledger": {"state": str, "limit": int},
            "role_set": {
                "name": str,
                "description": str,
                "profile": str,
                "tier": str,
                "max_minutes": int,
                "paid": bool,
            },
            "role_remove": {"name": str},
            "team_set": {"name": str, "roles": str, "description": str},
            "team_remove": {"name": str},
        }
        for name, spec in params.items():
            ctx.register_action(name, getattr(self, name), params=spec, read_only=name in read_only)
        ctx.register_panel("workers.status", self.report)
        self.ctx = ctx
        ctx.hermes_hook("subagent_start", self.on_start)
        ctx.hermes_hook("subagent_stop", self.on_stop)
        ctx.hermes_delegation(self.route, self.role_list)
        ctx.schedule.every("stuck", self.settings["check_seconds"], self.check_stuck)

    def deactivate(self) -> None:
        self.ctx = None

    def health(self) -> tuple[bool, str]:
        if self.ctx is None:
            return False, "stopped"
        running = self._q(f"SELECT count(*) FROM {self._t('runs')} WHERE status = 'running'")[0][0]  # nosec B608
        stuck = self._q(f"SELECT count(*) FROM {self._t('runs')} WHERE status = 'stuck'")[0][0]  # nosec B608
        return True, f"{running} running, {stuck} stuck"

    # helpers ------------------------------------------------------------------------------------------

    def _role(self, name: str) -> tuple[Any, ...] | None:
        cols = "name, description, profile, tier, max_minutes, paid"
        sql = f"SELECT {cols} FROM {self._t('roles')} WHERE name = ?"  # nosec B608
        rows = self._q(sql, (name,))
        return rows[0] if rows else None

    def _record_route(self, role: str, goal: str, target: str, outcome: str) -> None:
        routes = self._t("routes")
        self._q(
            f"INSERT INTO {routes} VALUES (?, ?, ?, ?, ?, ?, 0)",  # nosec B608
            (secrets.token_hex(8), self.clock(), role, goal, target, outcome),
        )
        count = self._q(f"SELECT count(*) FROM {routes}")[0][0]  # nosec B608
        if count > KEEP_ROUTES:
            sql = f"DELETE FROM {routes} WHERE id IN (SELECT id FROM {routes} ORDER BY at LIMIT ?)"  # nosec B608
            self._q(sql, (count - KEEP_ROUTES,))

    # Hermes delegation (ADR-0007) ---------------------------------------------------------------------

    def role_list(self) -> list[tuple[str, str]]:
        if self.ctx is None:
            return []
        teams: dict[str, list[str]] = {}
        for team, members in self._q(f"SELECT name, roles FROM {self._t('teams')} ORDER BY name"):  # nosec B608
            for member in json.loads(members):
                teams.setdefault(member, []).append(team)
        out = []
        for name, description in self._q(f"SELECT name, description FROM {self._t('roles')} ORDER BY name"):  # nosec B608
            text = description
            if name in teams:
                text = f"{text} (teams: {', '.join(teams[name])})".strip()
            out.append((name, text))
        return out

    def route(self, meta: dict[str, Any]) -> dict[str, Any]:
        """Route one task. Returns a route or ``{"refuse": code}`` (the core writes the message)."""
        if self.ctx is None:
            return {"refuse": "workers_stopped"}
        role_name = meta.get("worker_role") or self.settings["default_role"]
        goal = str(meta.get("goal_sha") or "")
        with self._lock:
            if not role_name:
                return {"refuse": "worker_role_required"}
            role = self._role(role_name)
            if role is None:
                return {"refuse": "unknown_role"}
            since = self.clock() - self.settings["loop_window_minutes"] * 60
            if goal:
                routes = self._t("routes")
                sql = f"SELECT count(*) FROM {routes} WHERE goal_sha = ? AND at >= ? AND outcome = 'routed'"  # nosec B608
                if self._q(sql, (goal, since))[0][0] >= self.settings["loop_limit"]:
                    self._record_route(role_name, goal, "", "loop")
                    self.ctx.audit("loop_refused", role=role_name)
                    self.ctx.emit("workers.loop", {"role": role_name, "goal_sha": goal})
                    return {"refuse": "repeated_delegation"}
            answer, target = self._target(role)
            if "refuse" in answer:
                self._record_route(role_name, goal, "", answer["refuse"])
                return answer
            self._record_route(role_name, goal, target, "routed")
            return answer

    def _target(self, role: tuple[Any, ...]) -> tuple[dict[str, Any], str]:
        name, _desc, profile, tier, _max, paid = role
        consumer = f"subagent:{name}"
        if profile:
            # A persona runs its profile's own model. The operator declares whether that model is paid; a paid
            # persona needs this module's llm.paid grant, and the child's requests are still steered by the
            # router within the role's consumer (paid rules, budget, quotas) (M7 review).
            if paid and not self.ctx.has("llm.paid"):
                return {"refuse": "paid_not_granted"}, ""
            return {"profile": profile, "consumer": consumer, "free_only": not paid}, f"profile:{profile}"
        try:
            plan = self.ctx.call(
                "router", "explain", {"consumer": f"subagent:{name}", "tokens": TIER_TOKENS[tier]}
            )
        except SignalboxError:
            return {"refuse": "router_unavailable"}, ""
        paid_blocked = False
        for option in plan.get("providers", []):
            if not option.get("chosen") or not option.get("model"):
                continue
            if option.get("cost_class") == "paid" and not self.ctx.has("llm.paid"):
                paid_blocked = True
                continue
            route = {
                "model": option["model"],
                "provider": option["provider"],
                "consumer": consumer,
                "free_only": not self.ctx.has("llm.paid"),
            }
            return route, str(option["chosen"])
        return {"refuse": "paid_not_granted" if paid_blocked else "no_model_available"}, ""

    # Hermes observers ---------------------------------------------------------------------------------

    def on_start(self, meta: dict[str, Any]) -> None:
        child = str(meta.get("child_session_id") or meta.get("child_subagent_id") or "")[:128]
        if not child or self.ctx is None:
            return
        goal = str(meta.get("goal_sha") or "")
        now = self.clock()
        with self._lock:
            routes = self._t("routes")
            sql = (
                f"SELECT id, role, target FROM {routes} WHERE goal_sha = ? AND outcome = 'routed' "  # nosec B608
                "AND linked = 0 AND at >= ? ORDER BY at LIMIT 1"
            )
            found = self._q(sql, (goal, now - LINK_WINDOW)) if goal else []
            role, target = "", ""
            if found:
                self._q(f"UPDATE {routes} SET linked = 1 WHERE id = ?", (found[0][0],))  # nosec B608
                role, target = found[0][1], found[0][2]
            runs = self._t("runs")
            self._q(
                f"INSERT OR REPLACE INTO {runs} VALUES (?, ?, ?, ?, ?, NULL, 'running', NULL)",  # nosec B608
                (child, role, goal, target, now),
            )
            count = self._q(f"SELECT count(*) FROM {runs}")[0][0]  # nosec B608
            if count > KEEP_RUNS:
                sql = (
                    f"DELETE FROM {runs} WHERE child IN (SELECT child FROM {runs} "  # nosec B608
                    "WHERE status != 'running' ORDER BY started_at LIMIT ?)"
                )
                self._q(sql, (count - KEEP_RUNS,))

    def on_stop(self, meta: dict[str, Any]) -> None:
        child = str(meta.get("child_session_id") or meta.get("child_subagent_id") or "")[:128]
        if not child or self.ctx is None:
            return
        status = _line(meta.get("child_status") or "", 32)
        final = "done" if status in ("completed", "success", "succeeded") else "failed"
        duration = meta.get("duration_ms")
        duration = duration if isinstance(duration, int) and not isinstance(duration, bool) else None
        with self._lock:
            sql = f"UPDATE {self._t('runs')} SET ended_at = ?, status = ?, duration_ms = ? WHERE child = ?"  # nosec B608
            self._q(sql, (self.clock(), final, duration, child))

    def check_stuck(self) -> int:
        """Mark workers running past their role's limit (roles without one: 60 minutes) and announce them.
        Hermes gives plugins no handle to stop a ``delegate_task`` child: this reports, the operator stops."""
        if self.ctx is None:
            return 0
        now = self.clock()
        newly = 0
        with self._lock:
            limits = dict(self._q(f"SELECT name, max_minutes FROM {self._t('roles')}"))  # nosec B608
            rows = self._q(f"SELECT child, role, started_at FROM {self._t('runs')} WHERE status = 'running'")  # nosec B608
            for child, role, started in rows:
                if now - started > limits.get(role, 60) * 60:
                    self._q(f"UPDATE {self._t('runs')} SET status = 'stuck' WHERE child = ?", (child,))  # nosec B608
                    self.ctx.audit("stuck", role=role or "-", child=child[:64])
                    self.ctx.emit(
                        "workers.stuck",
                        {"role": role, "child": child[:64], "minutes": int((now - started) // 60)},
                    )
                    newly += 1
        return newly

    # actions ------------------------------------------------------------------------------------------

    def report(self) -> dict[str, Any]:
        counts = dict(self._q(f"SELECT status, count(*) FROM {self._t('runs')} GROUP BY status"))  # nosec B608
        since = self.clock() - 86400
        outcomes = dict(
            self._q(
                f"SELECT outcome, count(*) FROM {self._t('routes')} WHERE at >= ? GROUP BY outcome",  # nosec B608
                (since,),
            )
        )
        return {
            "roles": len(self.role_list()),
            "runs": counts,
            "routes_24h": outcomes,
            "default_role": self.settings["default_role"] or None,
            "paid_allowed": bool(self.ctx and self.ctx.has("llm.paid")),
        }

    def roles(self) -> dict[str, Any]:
        cols = "name, description, profile, tier, max_minutes, paid"
        sql = f"SELECT {cols} FROM {self._t('roles')} ORDER BY name"  # nosec B608
        rows = self._q(sql)
        return {
            "roles": [
                {
                    "name": n,
                    "description": d,
                    "profile": p or None,
                    "tier": t,
                    "max_minutes": m,
                    "paid": bool(pd),
                }
                for n, d, p, t, m, pd in rows
            ]
        }

    def teams(self) -> dict[str, Any]:
        rows = self._q(f"SELECT name, roles, description FROM {self._t('teams')} ORDER BY name")  # nosec B608
        return {"teams": [{"name": n, "roles": json.loads(r), "description": d} for n, r, d in rows]}

    def ledger(self, state: str = "all", limit: int = 50) -> dict[str, Any]:
        if state not in STATES:
            raise SignalboxError(f"state must be one of {list(STATES)}")
        if not 1 <= limit <= 500:
            raise SignalboxError("limit must be from 1 to 500")
        where, args = ("", ()) if state == "all" else (" WHERE status = ?", (state,))
        sql = (
            f"SELECT child, role, target, started_at, ended_at, status, duration_ms FROM {self._t('runs')}"  # nosec B608
            f"{where} ORDER BY started_at DESC LIMIT ?"
        )
        rows = self._q(sql, (*args, limit))
        keys = ("child", "role", "target", "started_at", "ended_at", "status", "duration_ms")
        return {"runs": [dict(zip(keys, row, strict=True)) for row in rows]}

    def role_set(
        self,
        name: str,
        description: str = "",
        profile: str = "",
        tier: str = "T2",
        max_minutes: int = 30,
        paid: bool = False,
    ) -> dict[str, Any]:
        """``paid`` declares that a persona's profile model is paid (pool roles: cost from the registry)."""
        _check(_NAME, name, "role name")
        if profile:
            _check(_PROFILE, profile, "profile name")
        if tier not in TIER_TOKENS:
            raise SignalboxError(f"tier must be one of {sorted(TIER_TOKENS)}")
        if not 1 <= max_minutes <= 1440:
            raise SignalboxError("max_minutes must be from 1 to 1440")
        with self._lock:
            count = self._q(f"SELECT count(*) FROM {self._t('roles')}")[0][0]  # nosec B608
            if self._role(name) is None and count >= MAX_ROLES:
                raise SignalboxError(f"at most {MAX_ROLES} roles")
            self._q(
                f"INSERT OR REPLACE INTO {self._t('roles')} VALUES (?, ?, ?, ?, ?, ?)",  # nosec B608
                (
                    name,
                    _line(description, 200),
                    profile,
                    tier,
                    max_minutes,
                    int(bool(paid) and bool(profile)),
                ),
            )
        self.ctx.audit(
            "role_set", role=name, target=f"profile:{profile}" if profile else f"pool:subagent:{name}"
        )
        return {
            "role": name,
            "consumer": f"subagent:{name}",
            "profile": profile or None,
            "note": "takes effect in new Hermes sessions (the delegate_task schema is built per session)",
        }

    def role_remove(self, name: str) -> dict[str, Any]:
        _check(_NAME, name, "role name")
        with self._lock:
            if self._role(name) is None:
                raise SignalboxError(f"no role {name!r}")
            self._q(f"DELETE FROM {self._t('roles')} WHERE name = ?", (name,))  # nosec B608
            for team, members in self._q(f"SELECT name, roles FROM {self._t('teams')}"):  # nosec B608
                kept = [m for m in json.loads(members) if m != name]
                self._q(f"UPDATE {self._t('teams')} SET roles = ? WHERE name = ?", (json.dumps(kept), team))  # nosec B608
        self.ctx.audit("role_remove", role=name)
        return {"removed": name}

    def team_set(self, name: str, roles: str, description: str = "") -> dict[str, Any]:
        _check(_NAME, name, "team name")
        members = [r.strip() for r in roles.split(",") if r.strip()]
        if not 1 <= len(members) <= MAX_ROLES:
            raise SignalboxError("a team needs at least one role")
        with self._lock:
            missing = [m for m in members if not _NAME.match(m) or self._role(m) is None]
            if missing:
                raise SignalboxError(f"unknown role(s) {sorted(missing)[:5]}")
            exists = self._q(f"SELECT 1 FROM {self._t('teams')} WHERE name = ?", (name,))  # nosec B608
            if not exists and self._q(f"SELECT count(*) FROM {self._t('teams')}")[0][0] >= MAX_TEAMS:  # nosec B608
                raise SignalboxError(f"at most {MAX_TEAMS} teams")
            self._q(
                f"INSERT OR REPLACE INTO {self._t('teams')} VALUES (?, ?, ?)",  # nosec B608
                (name, json.dumps(sorted(set(members))), _line(description, 200)),
            )
        self.ctx.audit("team_set", team=name)
        return {"team": name, "roles": sorted(set(members))}

    def team_remove(self, name: str) -> dict[str, Any]:
        _check(_NAME, name, "team name")
        with self._lock:
            if not self._q(f"SELECT 1 FROM {self._t('teams')} WHERE name = ?", (name,)):  # nosec B608
                raise SignalboxError(f"no team {name!r}")
            self._q(f"DELETE FROM {self._t('teams')} WHERE name = ?", (name,))  # nosec B608
        self.ctx.audit("team_remove", team=name)
        return {"removed": name}
