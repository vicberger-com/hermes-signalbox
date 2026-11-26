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

from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.modkit import StateTables

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
        raise SignalboxError(f"at most {MAX_ENTRIES} entries")
    for item in items:
        if not _ENTRY.match(item):
            raise SignalboxError(f"invalid preset entry {item[:80]!r} (name, 'category:<name>' or '*')")
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


class ActivationModule(StateTables):
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.ctx: Any = None
        self.clock = clock
        self._lock = threading.Lock()

    # lifecycle ----------------------------------------------------------------------------------------

    def activate(self, ctx: Any) -> None:
        if set(ctx.config):
            raise SignalboxError(f"unknown [modules.activation] setting(s) {sorted(ctx.config)}")
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
        """Read-only (H1 C-16): a dashboard poll never ends a preset or writes Hermes config. An expired
        preset ends at the next turn (``pre_llm_call``) or the next ``apply``/``restore``."""
        if self.ctx is None:
            return False, "stopped"
        active = self._active()
        if not active:
            return True, "no preset active"
        if active["until"] and self.clock() >= active["until"]:
            return True, f"preset {active['preset']} (expired; ends at the next turn)"
        return True, f"preset {active['preset']}"

    # helpers ------------------------------------------------------------------------------------------

    def _skills(self) -> list[dict[str, str]]:
        skills: list[dict[str, str]] = self.ctx.hermes_config.skills()
        return skills

    def _preset(self, name: str) -> dict[str, Any]:
        sql = f"SELECT name, enable, disable, description FROM {self._t('presets')} WHERE name = ?"  # nosec B608
        rows = self._q(sql, (name,))
        if not rows:
            raise SignalboxError(f"no preset {name!r}")
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
        state = json.loads(rows[0][1])
        return {"preset": rows[0][0], "backup": state["backup"], "before": state["before"],
                "applied": state["applied"], "until": rows[0][2], "applied_at": rows[0][3]}  # fmt: skip

    def _target(self, preset: dict[str, Any], skills: list[dict[str, str]], disabled: set[str]) -> list[str]:
        return sorted((disabled | expand(preset["disable"], skills)) - expand(preset["enable"], skills))

    @staticmethod
    def _index_tokens(skills: list[dict[str, str]], disabled: set[str]) -> int:
        return sum(line_tokens(s) for s in skills if s["name"] not in disabled)

    def _undo_preset(self, active: dict[str, Any], actor: str) -> dict[str, Any]:
        """Take back only what the presets changed: names they disabled are re-enabled, names they enabled
        are disabled again. Edits made since (in Hermes or by hand) are kept; a difference is audited."""
        before, applied = set(active["before"]), set(active["applied"])
        current = set(self.ctx.hermes_config.get(KEY))
        target = sorted((current - (applied - before)) | (before - applied))
        if current != applied:
            self.ctx.audit("drift", preset=active["preset"], changed=str(len(current ^ applied)))
        note = f"end of preset {active['preset']}"
        result: dict[str, Any] = self.ctx.hermes_config.set(KEY, target, actor=actor, note=note)
        self._q(f"DELETE FROM {self._t('active')} WHERE slot = 'skills'")  # nosec B608
        return result

    def _expire_locked(self) -> None:
        active = self._active()
        if active and active["until"] and self.clock() >= active["until"]:
            self._undo_preset(active, actor="activation:ttl")
            self.ctx.audit("expired", preset=active["preset"])

    def _expire(self) -> None:
        with self._lock:
            self._expire_locked()

    def on_turn(self, _kw: dict[str, Any]) -> None:
        if self.ctx is not None:
            self._expire()

    # read-only actions --------------------------------------------------------------------------------

    def inventory(self, category: str = "") -> dict[str, Any]:
        skills = self._skills()
        cfg = self.ctx.hermes_config
        disabled = set(cfg.get(KEY)) - cfg.essential()
        per_platform = cfg.read("skills.platform_disabled")
        rows: list[dict[str, Any]] = [
            {
                **s,
                "enabled": s["name"] not in disabled,
                "tokens": line_tokens(s),
                "disabled_on": sorted(p for p, names in per_platform.items() if s["name"] in names),
            }
            for s in skills
            if not category or s["category"] == category
        ]
        rows.sort(key=lambda r: (-r["tokens"], r["name"]))
        return {
            "skills": [
                {k: r[k] for k in ("name", "category", "enabled", "tokens", "disabled_on")}
                for r in rows[:500]
            ],
            "count": len(rows),
            "not_listed": cfg.dropped,
            "scope": "global skills.disabled; disabled_on: platforms that also disable it (not managed here)",
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
        essential = self.ctx.hermes_config.essential()
        disabled = set(self.ctx.hermes_config.get(KEY)) - essential
        before = self._index_tokens(skills, disabled)
        after = self._index_tokens(skills, set(self._target(preset, skills, disabled)) - essential)
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
            raise SignalboxError("n must be from 1 to 200")
        return {"backups": self.ctx.hermes_config.backups(n)}

    def status(self) -> dict[str, Any]:
        try:
            inv = self.inventory()
        except SignalboxError as exc:  # no Hermes config in this host (tests, standalone CLI)
            return {"available": False, "error": str(exc)[:200]}
        return {k: inv[k] for k in ("count", "enabled_tokens", "disabled_tokens", "active")}

    # human-only actions -------------------------------------------------------------------------------

    def preset_add(
        self, name: str, enable: str = "", disable: str = "", description: str = ""
    ) -> dict[str, Any]:
        if not _NAME.match(name):
            raise SignalboxError(f"invalid preset name {name[:64]!r}")
        on, off = _entries(enable), _entries(disable)
        if not on and not off:
            raise SignalboxError("a preset needs at least one entry in enable or disable")
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
            raise SignalboxError(f"ttl_minutes must be from 0 to {MAX_TTL_MINUTES}")
        preset = self._preset(name)
        with self._lock:
            self._expire_locked()  # an expired preset ends before a new one is computed
            skills = self._skills()
            disabled = sorted(self.ctx.hermes_config.get(KEY))
            result = self.ctx.hermes_config.set(
                KEY, self._target(preset, skills, set(disabled)), actor="activation", note=f"preset {name}"
            )
            active = self._active()
            before = active["before"] if active else disabled  # stacked presets keep the first baseline
            first_backup = active["backup"] if active else result["backup"]
            now = self.clock()
            until = now + ttl_minutes * 60 if ttl_minutes else None
            state = json.dumps({"backup": first_backup, "before": before, "applied": result["stored"]})
            sql = f"INSERT OR REPLACE INTO {self._t('active')} VALUES ('skills', ?, ?, ?, ?)"  # nosec B608
            self._q(sql, (name, state, until, now))
        return {
            "preset": name,
            "backup": result["backup"],
            "disabled": len(result["stored"]),
            "refused": result["refused"],
            "until": until,
            "baseline": first_backup,
        }

    def restore(self) -> dict[str, Any]:
        """End the active preset(s): undo exactly what they changed, keeping other edits made since."""
        with self._lock:
            active = self._active()
            if not active:
                raise SignalboxError("no preset is active")
            result = self._undo_preset(active, actor="activation")
        return {"restored": active["preset"], "backup": result["backup"], "disabled": result["stored"]}

    def undo(self, backup: str) -> dict[str, Any]:
        """Restore the value recorded before any single change (itself backed up)."""
        result: dict[str, Any] = self.ctx.hermes_config.revert(backup, actor="activation")
        return result
