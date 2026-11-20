"""M5 skill activation manager (spec: README.md in this directory).

Inventory of installed Hermes skills with the prompt cost of each (its line in the ``<available_skills>``
index), presets that switch sets of skills on and off, a benchmark of the index size a preset gives, and an
optional time limit after which the previous state comes back. Every change goes through
``ctx.hermes_config`` (ADR-0005): backed up, audited, read back, rolled back on failure, reversible.

Preset entries: a skill name, ``category:<name>``, or ``*`` (every skill).
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from switchyard.errors import SwitchyardError

KEY = "skills.disabled"
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_ENTRY = re.compile(r"(\*|category:[A-Za-z0-9][A-Za-z0-9._/-]{0,127}|[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127})\Z")
MAX_ENTRIES = 500
MAX_TTL_MINUTES = 7 * 24 * 60


def line_tokens(skill: dict[str, str]) -> int:
    """Estimated tokens of a skill's ``- name: description`` row in Hermes's ``<available_skills>`` index."""
    row = (
        f"    - {skill['name']}: {skill['description']}"
        if skill.get("description")
        else f"    - {skill['name']}"
    )
    return (len(row) + 1 + 3) // 4


def _entries(text: str) -> list[str]:
    items = sorted({e.strip() for e in text.split(",") if e.strip()})
    if len(items) > MAX_ENTRIES:
        raise SwitchyardError(f"at most {MAX_ENTRIES} entries")
    for item in items:
        if not _ENTRY.match(item):
            raise SwitchyardError(f"invalid preset entry {item[:80]!r} (name, 'category:<name>' or '*')")
    return items


def expand(entries: list[str], skills: list[dict[str, str]]) -> set[str]:
    names: set[str] = set()
    for entry in entries:
        if entry == "*":
            names |= {s["name"] for s in skills}
        elif entry.startswith("category:"):
            category = entry.split(":", 1)[1]
            names |= {
                s["name"]
                for s in skills
                if s["category"] == category or s["category"].startswith(category + "/")
            }
        else:
            names.add(entry)
    return names


class ActivationModule:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.ctx: Any = None
        self.clock = clock
        self._lock = threading.Lock()

    # lifecycle ----------------------------------------------------------------------------------------

    def activate(self, ctx: Any) -> None:
        if set(ctx.config):
            raise SwitchyardError(f"unknown [modules.activation] setting(s) {sorted(ctx.config)}")
        text = "TEXT"
        ctx.state.create_table(
            "presets",
            [("name", text), ("enable", text), ("disable", text), ("description", text)],
            primary_key=["name"],
        )
        ctx.state.create_table(
            "active",
            [("slot", text), ("preset", text), ("baseline", text), ("until", "REAL"), ("applied_at", "REAL")],
            primary_key=["slot"],
        )
        read_only = {"inventory", "presets", "benchmark", "history"}
        params: dict[str, dict[str, type]] = {
            "inventory": {"category": str},
            "presets": {},
            "benchmark": {"name": str},
            "history": {"n": int},
            "preset_add": {"name": str, "enable": str, "disable": str, "description": str},
            "preset_remove": {"name": str},
            "apply": {"name": str, "ttl_minutes": int},
            "restore": {},
            "undo": {"backup": str},
        }
        for name, spec in params.items():
            ctx.register_action(name, getattr(self, name), params=spec, read_only=name in read_only)
        ctx.register_panel("activation.status", self.status)
        ctx.hermes_hook("pre_llm_call", self.on_turn)
        self.ctx = ctx

    def deactivate(self) -> None:
        self.ctx = None

    def health(self) -> tuple[bool, str]:
        if self.ctx is None:
            return False, "stopped"
        self._expire()
        active = self._active()
        return True, f"preset {active['preset']}" if active else "no preset active"

    # helpers ------------------------------------------------------------------------------------------

    def _q(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = self.ctx.state.execute(sql, params)
        return rows

    def _t(self, name: str) -> str:
        return str(self.ctx.state.table(name))

    def _skills(self) -> list[dict[str, str]]:
        skills: list[dict[str, str]] = self.ctx.hermes_config.skills()
        return skills

    def _preset(self, name: str) -> dict[str, Any]:
        sql = f"SELECT name, enable, disable, description FROM {self._t('presets')} WHERE name = ?"  # nosec B608
        rows = self._q(sql, (name,))
        if not rows:
            raise SwitchyardError(f"no preset {name!r}")
        return {
            "name": rows[0][0],
            "enable": json.loads(rows[0][1]),
            "disable": json.loads(rows[0][2]),
            "description": rows[0][3],
        }

    def _active(self) -> dict[str, Any] | None:
        sql = f"SELECT preset, baseline, until, applied_at FROM {self._t('active')} WHERE slot = 'skills'"  # nosec B608
        rows = self._q(sql)
        if not rows:
            return None
        return {"preset": rows[0][0], "baseline": rows[0][1], "until": rows[0][2], "applied_at": rows[0][3]}

    def _target(self, preset: dict[str, Any], skills: list[dict[str, str]], disabled: set[str]) -> list[str]:
        return sorted((disabled | expand(preset["disable"], skills)) - expand(preset["enable"], skills))

    @staticmethod
    def _index_tokens(skills: list[dict[str, str]], disabled: set[str]) -> int:
        return sum(line_tokens(s) for s in skills if s["name"] not in disabled)

    def _expire(self) -> None:
        with self._lock:
            active = self._active()
            if active and active["until"] and self.clock() >= active["until"]:
                self.ctx.hermes_config.revert(active["baseline"], actor="activation:ttl")
                self._q(f"DELETE FROM {self._t('active')} WHERE slot = 'skills'")  # nosec B608
                self.ctx.audit("expired", preset=active["preset"])

    def on_turn(self, _kw: dict[str, Any]) -> None:
        if self.ctx is not None:
            self._expire()

    # read-only actions --------------------------------------------------------------------------------

    def inventory(self, category: str = "") -> dict[str, Any]:
        skills = self._skills()
        disabled = set(self.ctx.hermes_config.get(KEY))
        rows: list[dict[str, Any]] = [
            {**s, "enabled": s["name"] not in disabled, "tokens": line_tokens(s)}
            for s in skills
            if not category or s["category"] == category
        ]
        rows.sort(key=lambda r: (-r["tokens"], r["name"]))
        return {
            "skills": [{k: r[k] for k in ("name", "category", "enabled", "tokens")} for r in rows[:500]],
            "count": len(rows),
            "enabled_tokens": sum(r["tokens"] for r in rows if r["enabled"]),
            "disabled_tokens": sum(r["tokens"] for r in rows if not r["enabled"]),
            "active": self._active(),
            "method": "chars/4 of each skill's '- name: description' row in the <available_skills> index",
        }

    def presets(self) -> dict[str, Any]:
        rows = self._q(f"SELECT name FROM {self._t('presets')} ORDER BY name")  # nosec B608
        return {"presets": [self._preset(r[0]) for r in rows]}

    def benchmark(self, name: str) -> dict[str, Any]:
        """Index size now and with ``name`` applied (no change is made)."""
        preset = self._preset(name)
        skills = self._skills()
        disabled = set(self.ctx.hermes_config.get(KEY))
        before = self._index_tokens(skills, disabled)
        after = self._index_tokens(skills, set(self._target(preset, skills, disabled)))
        saved = before - after
        return {
            "preset": name,
            "before_tokens": before,
            "after_tokens": after,
            "saved_tokens": saved,
            "reduction_percent": round(100 * saved / before, 1) if before else 0.0,
        }

    def history(self, n: int = 20) -> dict[str, Any]:
        if not 1 <= n <= 200:
            raise SwitchyardError("n must be from 1 to 200")
        return {"backups": self.ctx.hermes_config.backups(n)}

    def status(self) -> dict[str, Any]:
        try:
            inv = self.inventory()
        except SwitchyardError as exc:  # no Hermes config in this host (tests, standalone CLI)
            return {"available": False, "error": str(exc)[:200]}
        return {k: inv[k] for k in ("count", "enabled_tokens", "disabled_tokens", "active")}

    # human-only actions -------------------------------------------------------------------------------

    def preset_add(
        self, name: str, enable: str = "", disable: str = "", description: str = ""
    ) -> dict[str, Any]:
        if not _NAME.match(name):
            raise SwitchyardError(f"invalid preset name {name[:64]!r}")
        on, off = _entries(enable), _entries(disable)
        if not on and not off:
            raise SwitchyardError("a preset needs at least one entry in enable or disable")
        sql = f"INSERT OR REPLACE INTO {self._t('presets')} VALUES (?, ?, ?, ?)"  # nosec B608
        self._q(sql, (name, json.dumps(on), json.dumps(off), description[:200]))
        self.ctx.audit("preset_add", preset=name, enable=str(len(on)), disable=str(len(off)))
        return self._preset(name)

    def preset_remove(self, name: str) -> dict[str, Any]:
        self._preset(name)
        self._q(f"DELETE FROM {self._t('presets')} WHERE name = ?", (name,))  # nosec B608
        self.ctx.audit("preset_remove", preset=name)
        return {"removed": name}

    def apply(self, name: str, ttl_minutes: int = 0) -> dict[str, Any]:
        """Apply a preset. With ``ttl_minutes`` the previous state comes back after that time (checked
        before each Hermes turn and on every health poll). Over an active preset, the first baseline stays."""
        if not 0 <= ttl_minutes <= MAX_TTL_MINUTES:
            raise SwitchyardError(f"ttl_minutes must be from 0 to {MAX_TTL_MINUTES}")
        preset = self._preset(name)
        with self._lock:
            skills = self._skills()
            disabled = set(self.ctx.hermes_config.get(KEY))
            result = self.ctx.hermes_config.set(
                KEY, self._target(preset, skills, disabled), actor="activation", note=f"preset {name}"
            )
            active = self._active()
            baseline = active["baseline"] if active else result["backup"]
            now = self.clock()
            until = now + ttl_minutes * 60 if ttl_minutes else None
            sql = f"INSERT OR REPLACE INTO {self._t('active')} VALUES ('skills', ?, ?, ?, ?)"  # nosec B608
            self._q(sql, (name, baseline, until, now))
        return {
            "preset": name,
            "backup": result["backup"],
            "disabled": len(result["stored"]),
            "refused": result["refused"],
            "until": until,
            "baseline": baseline,
        }

    def restore(self) -> dict[str, Any]:
        """Return to the state before the first active preset."""
        with self._lock:
            active = self._active()
            if not active:
                raise SwitchyardError("no preset is active")
            result = self.ctx.hermes_config.revert(active["baseline"], actor="activation")
            self._q(f"DELETE FROM {self._t('active')} WHERE slot = 'skills'")  # nosec B608
        return {"restored": active["baseline"], "backup": result["backup"]}

    def undo(self, backup: str) -> dict[str, Any]:
        """Restore the value recorded before any single change (itself backed up)."""
        result: dict[str, Any] = self.ctx.hermes_config.revert(backup, actor="activation")
        return result
