"""M1 secrets module (spec: docs/modules/m1-secrets.md).

Provides the configured secret backends to the core broker, keeps metadata per secret name (backend, created,
rotated, expires; never a value) and offers three actions: ``status`` (read-only), ``rotate`` (write a fresh
random value to a writable backend, never shown) and ``expire`` (record an expiry date).

Settings, ``[modules.secrets]`` in the core ``config.toml``::

    backends = ["wincred", "bw"]   # lookup order; default: the OS store for this platform
    allow_env_backend = false      # the env backend is for development only
    bw_session_env = "BW_SESSION"  # where the operator exported the unlocked bw session
    rotation_length = 32           # bytes of randomness for rotate (token_urlsafe)
    expiry_warning_days = 14
"""

from __future__ import annotations

import re
import secrets as _random
from datetime import UTC, date, datetime, timedelta
from typing import Any

from switchyard.errors import SwitchyardError

from .backends import build, check_name, default_order

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
# SQL below interpolates only this constant and the module's own table name from ctx.state.table().
_COLUMNS = "name, backend, created_at, rotated_at, expires_at"
date_cls = date


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class SecretsModule:
    def __init__(self) -> None:
        self.ctx: Any = None
        self.backends: list[Any] = []
        self.settings: dict[str, Any] = {}

    # lifecycle ----------------------------------------------------------------------------------------

    def activate(self, ctx: Any) -> None:
        if self.ctx is not None:
            return
        cfg = dict(ctx.config)
        unknown = set(cfg) - {"backends", "allow_env_backend", "bw_session_env", "rotation_length",
                              "expiry_warning_days"}  # fmt: skip
        if unknown:
            raise SwitchyardError(f"unknown [modules.secrets] setting(s) {sorted(unknown)}")
        names = cfg.get("backends", default_order())
        length = cfg.get("rotation_length", 32)
        warn = cfg.get("expiry_warning_days", 14)
        if not (isinstance(names, list) and all(isinstance(n, str) for n in names)):
            raise SwitchyardError("[modules.secrets] backends must be a list of names")
        if isinstance(length, bool) or not isinstance(length, int) or not 16 <= length <= 256:
            raise SwitchyardError("[modules.secrets] rotation_length must be an integer from 16 to 256")
        if isinstance(warn, bool) or not isinstance(warn, int) or not 0 <= warn <= 3650:
            raise SwitchyardError("[modules.secrets] expiry_warning_days must be an integer from 0 to 3650")
        self.settings = {"rotation_length": length, "expiry_warning_days": warn}
        self.backends = build(names, ctx.spawn.run, session_env=str(cfg.get("bw_session_env", "BW_SESSION")),
                              allow_env=cfg.get("allow_env_backend", False) is True)  # fmt: skip
        ctx.state.create_table("meta", [("name", "TEXT"), ("backend", "TEXT"), ("created_at", "TEXT"),
                                        ("rotated_at", "TEXT"), ("expires_at", "TEXT")],
                               primary_key=["name"])  # fmt: skip
        for backend in self.backends:
            ctx.provide_secret_backend(backend)
            if backend.name == "env":
                ctx.log("secrets", "env backend enabled (development only)")
        ctx.register_action("status", self.status, read_only=True)
        ctx.register_action("rotate", self.rotate, params={"name": str, "backend": str})
        ctx.register_action("expire", self.expire, params={"name": str, "date": str})
        ctx.register_panel("secrets.status", self.status)
        self.ctx = ctx

    def deactivate(self) -> None:
        self.ctx = None
        self.backends = []

    def health(self) -> tuple[bool, str]:
        if self.ctx is None:
            return False, "stopped"
        available = [b.name for b in self.backends if b.available()]
        if not available:
            return False, "no configured backend is available"
        expiring = [row["name"] for row in self.status()["secrets"] if row["expiring"]]
        detail = f"backends: {', '.join(available)}"
        if expiring:
            detail += f"; expiring soon: {', '.join(expiring)}"
        return True, detail

    # metadata -----------------------------------------------------------------------------------------

    def _table(self) -> str:
        return str(self.ctx.state.table("meta"))

    def _row(self, name: str) -> tuple[Any, ...] | None:
        sql = f"SELECT {_COLUMNS} FROM {self._table()} WHERE name = ?"  # nosec B608
        rows = self.ctx.state.execute(sql, (name,))
        return rows[0] if rows else None

    def _upsert(self, name: str, **fields: str | None) -> None:
        row = self._row(name)
        current = dict(zip(("name", "backend", "created_at", "rotated_at", "expires_at"),
                           row or (name, None, None, None, None), strict=True))  # fmt: skip
        current.update(fields)
        sql = f"INSERT OR REPLACE INTO {self._table()} VALUES (?, ?, ?, ?, ?)"
        self.ctx.state.execute(sql, tuple(current[k] for k in ("name", "backend", "created_at", "rotated_at",
                                                               "expires_at")))  # fmt: skip

    # actions ------------------------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Backends and per-name metadata. Never values."""
        today = datetime.now(UTC).date()
        warn = timedelta(days=int(self.settings.get("expiry_warning_days", 14)))
        sql = f"SELECT {_COLUMNS} FROM {self._table()} ORDER BY name"  # nosec B608
        rows = self.ctx.state.execute(sql)
        secrets = []
        for name, backend, created, rotated, expires in rows:
            last = rotated or created
            age_days = (today - date.fromisoformat(last[:10])).days if last else None
            expiring = bool(expires) and date.fromisoformat(expires) - today <= warn
            secrets.append({"name": name, "backend": backend, "created_at": created, "rotated_at": rotated,
                            "expires_at": expires, "age_days": age_days, "expiring": expiring})  # fmt: skip
        return {
            "backends": [
                {"name": b.name, "available": bool(b.available()), "writable": hasattr(b, "set")}
                for b in self.backends
            ],
            "secrets": secrets,
        }

    def rotate(self, name: str, backend: str = "") -> dict[str, Any]:
        """Write a fresh random value for ``name``; it is generated here and never returned or logged."""
        check_name(name)
        writable = [b for b in self.backends if hasattr(b, "set") and b.available()]
        row = self._row(name)
        recorded = row[1] if row and row[1] else ""
        wanted = backend or recorded
        if wanted:
            writable = [b for b in writable if b.name == wanted]
            if not writable and recorded and not backend:
                raise SwitchyardError(
                    f"recorded backend {recorded!r} for {name!r} is not available or writable"
                )
        if not writable:
            raise SwitchyardError("no writable, available backend for rotation")
        target = writable[0]
        self._check_not_shadowed(name, target)
        value = _random.token_urlsafe(int(self.settings["rotation_length"]))
        target.set(name, value)
        del value
        stamp = _now()
        row = self._row(name)
        self._upsert(
            name, backend=target.name, created_at=(row[2] if row and row[2] else stamp), rotated_at=stamp
        )
        self.ctx.log("secrets", "rotated", secret=name, backend=target.name)
        self.ctx.audit("rotated", secret=name, backend=target.name)
        return {"name": name, "backend": target.name, "rotated_at": stamp}

    def _check_not_shadowed(self, name: str, target: Any) -> None:
        """Lookups use the first backend that holds a name. Writing to a later one would leave the old value
        in service, so every available backend before ``target`` must not hold ``name``."""
        for earlier in self.backends:
            if earlier is target:
                return
            if not earlier.available():
                continue
            try:
                earlier.get(name)
            except KeyError:
                continue
            except Exception:
                raise SwitchyardError(
                    f"cannot check {earlier.name!r} for {name!r}; rotation refused"
                ) from None
            raise SwitchyardError(
                f"{name!r} is served by {earlier.name!r}, which comes first; rotate it there"
            )

    def expire(self, name: str, date: str) -> dict[str, Any]:
        check_name(name)
        if not _DATE.match(date):
            raise SwitchyardError("date must be YYYY-MM-DD")
        try:
            date_cls.fromisoformat(date)
        except ValueError:
            raise SwitchyardError("date must be a real calendar date") from None
        self._upsert(name, expires_at=date)
        self.ctx.log("secrets", "expiry set", secret=name, expires=date)
        self.ctx.audit("expiry_set", secret=name, expires=date)
        return {"name": name, "expires_at": date}
