"""M2 resource registry, pools and bindings (spec: README.md in this directory).

Resources are catalog entries (models, endpoints, agents, tools) with a state (``manual``, ``auto``,
``disabled``), a cost class, tags, limits and a priority (lower is preferred). Pools group resources with a
per-pool priority; consumers (``main``, ``subagent:<name>``, ``function:<name>``) are bound to one pool.
``resolve`` returns a consumer's usable resources in order.

Imports are reviewed: ``import_preview`` (configured models.dev cache, no path; operator-only because it
replaces the pending import) and ``import_file`` (operator-chosen path, human-only) store a diff; nothing
changes until a human runs ``import_apply``. One pending import per source. New resources arrive
``disabled``; an import replaces only catalog fields and catalog tags (a ``stale`` catalog tag marks rows the
source no longer lists); state, priority and user tags never change.

Settings, ``[modules.resources]``::

    models_dev_cache = "C:/Users/me/AppData/Local/hermes/models_dev_cache.json"  # default: Hermes home
    max_catalog_mb = 16
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets as _random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.modkit import StateTables, default_models_dev_cache

from .catalog import ID, STATES, TAG, diff, from_file, from_models_dev

_POOL = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_CONSUMER = re.compile(r"(main|(subagent|function|agent):[A-Za-z0-9._-]{1,64})\Z")
_IMPORT_ID = re.compile(r"[a-f0-9]{12}\Z")
# ``tags`` are the user's; ``source_tags`` come from the catalog and are replaced by imports.
_COLS = "id, kind, provider, name, state, cost_class, tags, limits, priority, source, updated_at, source_tags"
MAX_PENDING = 5


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check(pattern: re.Pattern[str], value: str, what: str) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise SignalboxError(f"invalid {what} {str(value)[:80]!r}")
    return value


class ResourcesModule(StateTables):
    def __init__(self) -> None:
        self.ctx: Any = None
        self.settings: dict[str, Any] = {}

    # lifecycle ----------------------------------------------------------------------------------------

    def activate(self, ctx: Any) -> None:
        if self.ctx is not None:
            return
        cfg = dict(ctx.config)
        unknown = set(cfg) - {"models_dev_cache", "max_catalog_mb"}
        if unknown:
            raise SignalboxError(f"unknown [modules.resources] setting(s) {sorted(unknown)}")
        cache = cfg.get("models_dev_cache", str(default_models_dev_cache()))
        size = cfg.get("max_catalog_mb", 16)
        if not isinstance(cache, str) or not Path(cache).is_absolute():
            raise SignalboxError("[modules.resources] models_dev_cache must be an absolute path")
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 32:
            raise SignalboxError("[modules.resources] max_catalog_mb must be an integer from 1 to 32")
        self.settings = {"models_dev_cache": cache, "max_bytes": size << 20}
        state = ctx.state
        text, num = "TEXT", "INTEGER"
        state.create_table(
            "resources",
            [
                ("id", text),
                ("kind", text),
                ("provider", text),
                ("name", text),
                ("state", text),
                ("cost_class", text),
                ("tags", text),
                ("limits", text),
                ("priority", num),
                ("source", text),
                ("updated_at", text),
                ("source_tags", text),
            ],
            primary_key=["id"],
        )
        state.create_table("pools", [("name", text), ("description", text)], primary_key=["name"])
        state.create_table(
            "pool_members",
            [("pool", text), ("resource", text), ("priority", num)],
            primary_key=["pool", "resource"],
        )
        state.create_table("bindings", [("consumer", text), ("pool", text)], primary_key=["consumer"])
        state.create_table(
            "imports",
            [("id", text), ("source", text), ("created_at", text), ("diff", text)],
            primary_key=["id"],
        )
        # import_preview replaces the pending import from the same source, so it is not read-only (R1 review)
        read_only = {"list", "show", "pools", "resolve"}
        params: dict[str, dict[str, type]] = {
            "list": {
                "state": str,
                "cost_class": str,
                "tag": str,
                "pool": str,
                "provider": str,
                "query": str,
                "limit": int,
                "offset": int,
            },
            "show": {"id": str},
            "pools": {},
            "resolve": {"consumer": str},
            "import_preview": {"providers": str, "free_only": bool},
            "import_file": {"path": str},
            "set_state": {"id": str, "state": str},
            "set_priority": {"id": str, "priority": int},
            "tag": {"id": str, "tag": str},
            "untag": {"id": str, "tag": str},
            "pool_create": {"name": str, "description": str},
            "pool_delete": {"name": str},
            "pool_add": {"pool": str, "id": str, "priority": int},
            "pool_remove": {"pool": str, "id": str},
            "bind": {"consumer": str, "pool": str},
            "unbind": {"consumer": str},
            "import_apply": {"import_id": str},
            "import_discard": {"import_id": str},
        }
        for name, spec in params.items():
            handler = self.list_resources if name == "list" else getattr(self, name)
            ctx.register_action(name, handler, params=spec, read_only=name in read_only)
        ctx.register_panel("resources.status", self.summary)
        self.ctx = ctx

    def deactivate(self) -> None:
        self.ctx = None

    def health(self) -> tuple[bool, str]:
        if self.ctx is None:
            return False, "stopped"
        s = self.summary()
        return True, f"{s['resources']} resources, {s['enabled']} enabled, {s['pools']} pools"

    # storage helpers ----------------------------------------------------------------------------------

    def _row(self, row: tuple[Any, ...]) -> dict[str, Any]:
        keys = [c.strip() for c in _COLS.split(",")]
        out = dict(zip(keys, row, strict=True))
        out["user_tags"] = json.loads(out["tags"] or "[]")
        out["source_tags"] = json.loads(out["source_tags"] or "[]")
        out["tags"] = sorted({*out["user_tags"], *out["source_tags"]})
        out["limits"] = json.loads(out["limits"] or "{}")
        return out

    def _get(self, rid: str) -> dict[str, Any]:
        rows = self._q(f"SELECT {_COLS} FROM {self._t('resources')} WHERE id = ?", (rid,))  # nosec B608
        if not rows:
            raise SignalboxError(f"unknown resource {rid[:80]!r}")
        return self._row(rows[0])

    def _pool_exists(self, name: str) -> None:
        if not self._q(f"SELECT 1 FROM {self._t('pools')} WHERE name = ?", (name,)):  # nosec B608
            raise SignalboxError(f"unknown pool {name!r}")

    def _record(self, event: str, **detail: str) -> None:
        self.ctx.log("resources", event, **detail)
        self.ctx.audit(event, **detail)

    # read-only actions --------------------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        t = self._t("resources")
        total = self._q(f"SELECT count(*) FROM {t}")[0][0]  # nosec B608
        enabled = self._q(f"SELECT count(*) FROM {t} WHERE state != 'disabled'")[0][0]  # nosec B608
        pools = self._q(f"SELECT count(*) FROM {self._t('pools')}")[0][0]  # nosec B608
        pending = self._q(f"SELECT id, source, created_at FROM {self._t('imports')} ORDER BY created_at")  # nosec B608
        return {
            "resources": total,
            "enabled": enabled,
            "pools": pools,
            "pending_imports": [{"import_id": i, "source": s, "created_at": c} for i, s, c in pending],
        }

    def list_resources(
        self,
        state: str = "",
        cost_class: str = "",
        tag: str = "",
        pool: str = "",
        provider: str = "",
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 1000 or offset < 0:
            raise SignalboxError("limit must be 1..1000 and offset >= 0")
        t = self._t("resources")
        where, args = [], []
        for column, value in (("state", state), ("cost_class", cost_class), ("provider", provider)):
            if value:
                where.append(f"r.{column} = ?")
                args.append(value)
        if query:
            where.append("(r.id LIKE ? ESCAPE '\\' OR r.name LIKE ? ESCAPE '\\')")
            like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            args += [like, like]
        if tag:
            where.append("(r.tags LIKE ? ESCAPE '\\' OR r.source_tags LIKE ? ESCAPE '\\')")
            escaped = _check(TAG, tag, "tag").replace("_", "\\_")
            needle = f'%"{escaped}"%'
            args += [needle, needle]
        join = ""
        if pool:
            join = f" JOIN {self._t('pool_members')} m ON m.resource = r.id AND m.pool = ?"
            args.insert(0, pool)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        cols = ", ".join("r." + c.strip() for c in _COLS.split(","))
        sql = f"SELECT {cols} FROM {t} r{join}{clause} ORDER BY r.priority, r.id LIMIT ? OFFSET ?"  # nosec B608
        rows = [self._row(r) for r in self._q(sql, (*args, limit, offset))]
        return {"resources": rows, "count": len(rows), "offset": offset}

    def show(self, id: str) -> dict[str, Any]:
        row = self._get(id)
        sql = f"SELECT pool, priority FROM {self._t('pool_members')} WHERE resource = ? ORDER BY pool"  # nosec B608
        row["pools"] = [{"pool": p, "priority": n} for p, n in self._q(sql, (id,))]
        return row

    def pools(self) -> dict[str, Any]:
        out = []
        for name, description in self._q(f"SELECT name, description FROM {self._t('pools')} ORDER BY name"):  # nosec B608
            members = self._q(f"SELECT count(*) FROM {self._t('pool_members')} WHERE pool = ?", (name,))[0][0]  # nosec B608
            consumers = [
                c
                for (c,) in self._q(
                    f"SELECT consumer FROM {self._t('bindings')} WHERE pool = ? "  # nosec B608
                    "ORDER BY consumer",
                    (name,),
                )
            ]
            out.append({"name": name, "description": description, "members": members, "consumers": consumers})
        return {"pools": out}

    def resolve(self, consumer: str) -> dict[str, Any]:
        _check(_CONSUMER, consumer, "consumer")
        bound = self._q(f"SELECT pool FROM {self._t('bindings')} WHERE consumer = ?", (consumer,))  # nosec B608
        if not bound:
            return {"consumer": consumer, "pool": None, "resources": []}
        pool = bound[0][0]
        cols = ", ".join("r." + c.strip() for c in _COLS.split(","))
        sql = (
            f"SELECT {cols} FROM {self._t('resources')} r JOIN {self._t('pool_members')} m "  # nosec B608
            "ON m.resource = r.id WHERE m.pool = ? AND r.state != 'disabled' "
            "ORDER BY m.priority, r.priority, r.id LIMIT 1000"
        )
        return {
            "consumer": consumer,
            "pool": pool,
            "resources": [self._row(r) for r in self._q(sql, (pool,))],
        }

    def import_preview(self, providers: str = "", free_only: bool = False) -> dict[str, Any]:
        """Preview an import from the configured models.dev cache (no path). Operator-only: it replaces the
        pending import (H1 C-11)."""
        doc = self.ctx.fs.read_json(self.settings["models_dev_cache"], max_bytes=self.settings["max_bytes"])
        wanted = {p.strip() for p in providers.split(",") if p.strip()}
        return self._stage("models.dev", from_models_dev(doc, providers=wanted, free_only=free_only))

    def import_file(self, path: str) -> dict[str, Any]:
        """Preview an import from a catalog file. Human-only: the path is chosen by the operator."""
        incoming = from_file(self.ctx.fs.read_json(path, max_bytes=self.settings["max_bytes"]))
        digest = hashlib.sha256(str(Path(path).resolve()).encode("utf-8")).hexdigest()[:12]
        return self._stage(f"file:{digest}:{Path(path).name[:60]}", incoming)

    def _stage(self, label: str, incoming: list[dict[str, Any]]) -> dict[str, Any]:
        """Store the diff against rows from the same source. One pending import per source: a new preview
        replaces the previous one, so an old snapshot can never be applied over a newer one."""
        t = self._t("resources")
        existing: dict[str, dict[str, Any]] = {}
        offset = 0
        while True:
            sql = f"SELECT {_COLS} FROM {t} WHERE source = ? ORDER BY id LIMIT ? OFFSET ?"  # nosec B608
            page = self._q(sql, (label, 1000, offset))
            existing.update({r["id"]: {**r, "tags": r["source_tags"]} for r in map(self._row, page)})
            if len(page) < 1000:
                break
            offset += 1000
        changes = diff(existing, incoming)
        imports = self._t("imports")
        self._q(f"DELETE FROM {imports} WHERE source = ?", (label,))  # nosec B608
        if self._q(f"SELECT count(*) FROM {imports}")[0][0] >= MAX_PENDING:  # nosec B608
            raise SignalboxError(f"{MAX_PENDING} imports are pending; apply or discard one first")
        import_id = _random.token_hex(6)
        row = (import_id, label, _now(), json.dumps(changes))
        self._q(f"INSERT INTO {imports} VALUES (?, ?, ?, ?)", row)  # nosec B608
        counts = {k: len(changes[k]) for k in ("added", "changed", "removed")}
        sample = {
            "added": [r["id"] for r in changes["added"][:10]],
            "changed": [c["id"] for c in changes["changed"][:10]],
            "removed": changes["removed"][:10],
        }
        # Cost-class changes decide what is free to route: list every one, and apply them as "manual" so a
        # human re-enables the resource (R1 review).
        cost = [
            {"id": c["id"], "from": c["before"].get("cost_class"), "to": c["after"].get("cost_class")}
            for c in changes["changed"]
            if c["before"].get("cost_class") != c["after"].get("cost_class")
        ]
        return {"import_id": import_id, "source": label, **counts, "sample_ids": sample, "cost_changes": cost}

    # human-only actions -------------------------------------------------------------------------------

    def set_state(self, id: str, state: str) -> dict[str, Any]:
        if state not in STATES:
            raise SignalboxError(f"state must be one of {list(STATES)}")
        self._get(id)
        sql = f"UPDATE {self._t('resources')} SET state = ?, updated_at = ? WHERE id = ?"  # nosec B608
        self._q(sql, (state, _now(), id))
        self._record("state_set", resource=id, state=state)
        return {"id": id, "state": state}

    def set_priority(self, id: str, priority: int) -> dict[str, Any]:
        if not -1_000_000 <= priority <= 1_000_000:
            raise SignalboxError("priority must be between -1000000 and 1000000")
        self._get(id)
        sql = f"UPDATE {self._t('resources')} SET priority = ?, updated_at = ? WHERE id = ?"  # nosec B608
        self._q(sql, (priority, _now(), id))
        self._record("priority_set", resource=id, priority=str(priority))
        return {"id": id, "priority": priority}

    def _set_tags(self, rid: str, tags: list[str]) -> None:
        self._q(
            f"UPDATE {self._t('resources')} SET tags = ?, updated_at = ? WHERE id = ?",  # nosec B608
            (json.dumps(sorted(set(tags))), _now(), rid),
        )

    def tag(self, id: str, tag: str) -> dict[str, Any]:
        row = self._get(id)
        self._set_tags(id, [*row["user_tags"], _check(TAG, tag, "tag")])
        return self._get(id)

    def untag(self, id: str, tag: str) -> dict[str, Any]:
        row = self._get(id)
        self._set_tags(id, [t for t in row["user_tags"] if t != tag])
        return self._get(id)

    def pool_create(self, name: str, description: str = "") -> dict[str, Any]:
        _check(_POOL, name, "pool name")
        if self._q(f"SELECT 1 FROM {self._t('pools')} WHERE name = ?", (name,)):  # nosec B608
            raise SignalboxError(f"pool {name!r} exists")
        self._q(f"INSERT INTO {self._t('pools')} VALUES (?, ?)", (name, description[:200]))  # nosec B608
        self._record("pool_created", pool=name)
        return {"pool": name}

    def pool_delete(self, name: str) -> dict[str, Any]:
        self._pool_exists(name)
        if self._q(f"SELECT 1 FROM {self._t('bindings')} WHERE pool = ?", (name,)):  # nosec B608
            raise SignalboxError(f"pool {name!r} is bound to consumers; unbind them first")
        self._q(f"DELETE FROM {self._t('pool_members')} WHERE pool = ?", (name,))  # nosec B608
        self._q(f"DELETE FROM {self._t('pools')} WHERE name = ?", (name,))  # nosec B608
        self._record("pool_deleted", pool=name)
        return {"pool": name, "deleted": True}

    def pool_add(self, pool: str, id: str, priority: int = 100) -> dict[str, Any]:
        self._pool_exists(pool)
        self._get(id)
        self._q(f"INSERT OR REPLACE INTO {self._t('pool_members')} VALUES (?, ?, ?)", (pool, id, priority))  # nosec B608
        self._record("pool_member_added", pool=pool, resource=id)
        return {"pool": pool, "id": id, "priority": priority}

    def pool_remove(self, pool: str, id: str) -> dict[str, Any]:
        self._q(f"DELETE FROM {self._t('pool_members')} WHERE pool = ? AND resource = ?", (pool, id))  # nosec B608
        self._record("pool_member_removed", pool=pool, resource=id)
        return {"pool": pool, "id": id, "removed": True}

    def bind(self, consumer: str, pool: str) -> dict[str, Any]:
        _check(_CONSUMER, consumer, "consumer")
        self._pool_exists(pool)
        self._q(f"INSERT OR REPLACE INTO {self._t('bindings')} VALUES (?, ?)", (consumer, pool))  # nosec B608
        self._record("bound", consumer=consumer, pool=pool)
        return {"consumer": consumer, "pool": pool}

    def unbind(self, consumer: str) -> dict[str, Any]:
        self._q(f"DELETE FROM {self._t('bindings')} WHERE consumer = ?", (consumer,))  # nosec B608
        self._record("unbound", consumer=consumer)
        return {"consumer": consumer, "pool": None}

    def _pending(self, import_id: str) -> tuple[str, dict[str, Any]]:
        _check(_IMPORT_ID, import_id, "import id")
        rows = self._q(f"SELECT source, diff FROM {self._t('imports')} WHERE id = ?", (import_id,))  # nosec B608
        if not rows:
            raise SignalboxError(f"no pending import {import_id!r}")
        return str(rows[0][0]), json.loads(rows[0][1])

    def import_apply(self, import_id: str) -> dict[str, Any]:
        source, changes = self._pending(import_id)
        t, now = self._t("resources"), _now()
        for r in changes["added"]:
            if self._q(f"SELECT 1 FROM {t} WHERE id = ?", (r["id"],)):  # nosec B608
                continue  # added meanwhile by another source; leave it alone
            self._q(
                f"INSERT INTO {t} VALUES (?, ?, ?, ?, 'disabled', ?, '[]', ?, 100, ?, ?, ?)",  # nosec B608
                (
                    r["id"],
                    r["kind"],
                    r["provider"],
                    r["name"],
                    r["cost_class"],
                    json.dumps(r["limits"]),
                    source,
                    now,
                    json.dumps(r["tags"]),
                ),
            )
        for c in changes["changed"]:
            after = c["after"]
            if c["before"].get("cost_class") != after["cost_class"]:
                sql = f"UPDATE {t} SET state = 'manual' WHERE id = ? AND source = ? AND state = 'auto'"  # nosec B608
                self._q(sql, (c["id"], source))
            self._q(
                f"UPDATE {t} SET kind = ?, provider = ?, name = ?, cost_class = ?, source_tags = ?, "  # nosec B608
                "limits = ?, updated_at = ? WHERE id = ? AND source = ?",
                (
                    after["kind"],
                    after["provider"],
                    after["name"],
                    after["cost_class"],
                    json.dumps(after["tags"]),
                    json.dumps(after["limits"]),
                    now,
                    c["id"],
                    source,
                ),
            )
        for rid in changes["removed"]:  # catalog-side marker; cleared when the source lists the row again
            row = self._q(f"SELECT source_tags FROM {t} WHERE id = ? AND source = ?", (rid, source))  # nosec B608
            if row:
                tags = json.dumps(sorted({*json.loads(row[0][0] or "[]"), "stale"}))
                sql = f"UPDATE {t} SET source_tags = ?, updated_at = ? WHERE id = ?"  # nosec B608
                self._q(sql, (tags, now, rid))
        self._q(f"DELETE FROM {self._t('imports')} WHERE id = ?", (import_id,))  # nosec B608
        counts = {k: len(changes[k]) for k in ("added", "changed", "removed")}
        self._record(
            "import_applied", import_id=import_id, source=source, **{k: str(v) for k, v in counts.items()}
        )
        return {"import_id": import_id, "source": source, **counts}

    def import_discard(self, import_id: str) -> dict[str, Any]:
        self._pending(import_id)
        self._q(f"DELETE FROM {self._t('imports')} WHERE id = ?", (import_id,))  # nosec B608
        return {"import_id": import_id, "discarded": True}


__all__ = ["ID", "ResourcesModule"]
