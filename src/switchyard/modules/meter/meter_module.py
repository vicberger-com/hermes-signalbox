"""M4 metering, quotas and budgets (spec: README.md in this directory).

Every Hermes API response (``post_api_request``, metadata only through the bridge) is counted by UTC day
and hour, provider and model: requests, the token buckets exactly as reported, and an estimated cost from
models.dev prices. Errors (``api_request_error``) and subagent runs (``subagent_stop``) are counted too.
Quotas are opt-in rules with thresholds that fire once per period (``meter.threshold``; ``meter.exhausted``
at 100 %).

Settings, ``[modules.meter]``::

    retention_days = 90
    models_dev_cache = "C:/Users/me/AppData/Local/hermes/models_dev_cache.json"  # default: Hermes home
"""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from switchyard.errors import SwitchyardError
from switchyard.modkit import StateTables, default_models_dev_cache

BUCKETS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens")
_PRICE_KEYS = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_read_tokens": "cache_read",
    "cache_write_tokens": "cache_write",
}
METRICS = ("requests", "tokens", "cost_usd")
PERIODS = ("day", "month")
MAX_FIELD = 1_000_000_000
HOURLY_DAYS = 7
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_SCOPE = re.compile(r"(all|provider:[a-z0-9][a-z0-9._-]{0,63}|[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199})\Z")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}\Z")
_COLS = ("requests", *BUCKETS, "cost_micro", "unpriced", "usage_missing", "errors")


def _count(value: Any) -> tuple[int, bool]:
    """A reported token count: a non-negative number up to MAX_FIELD, floats rounded (H1 C-10). Anything else
    is 0 and flagged."""
    if isinstance(value, float) and math.isfinite(value):
        value = round(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_FIELD:
        return 0, value is not None
    return value, False


def _price(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 10_000:
        return None
    return float(value)


def parse_prices(doc: Any) -> dict[str, dict[str, float]]:
    """``provider/model`` -> USD per million tokens by bucket, from the models.dev registry."""
    out: dict[str, dict[str, float]] = {}
    if not isinstance(doc, dict):
        return out
    for pid, provider in doc.items():
        models = provider.get("models") if isinstance(provider, dict) else None
        if not isinstance(pid, str) or not isinstance(models, dict):
            continue
        for mid, model in models.items():
            cost = model.get("cost") if isinstance(model, dict) else None
            if not isinstance(mid, str) or not isinstance(cost, dict):
                continue
            entry = {k: p for k, src in _PRICE_KEYS.items() if (p := _price(cost.get(src))) is not None}
            if "input_tokens" in entry and "output_tokens" in entry and _KEY.match(f"{pid}/{mid}"):
                out[f"{pid}/{mid}"] = entry
    return out


class MeterModule(StateTables):
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.ctx: Any = None
        self.clock = clock
        self.settings: dict[str, Any] = {}
        self.prices: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()
        self._pruned_hour = ""

    # lifecycle ----------------------------------------------------------------------------------------

    def activate(self, ctx: Any) -> None:
        cfg = dict(ctx.config)
        unknown = set(cfg) - {"retention_days", "models_dev_cache"}
        if unknown:
            raise SwitchyardError(f"unknown [modules.meter] setting(s) {sorted(unknown)}")
        days = cfg.get("retention_days", 90)
        if isinstance(days, bool) or not isinstance(days, int) or not 7 <= days <= 3650:
            raise SwitchyardError("[modules.meter] retention_days must be an integer from 7 to 3650")
        cache = cfg.get("models_dev_cache", str(default_models_dev_cache()))
        if not isinstance(cache, str) or not Path(cache).is_absolute():
            raise SwitchyardError("[modules.meter] models_dev_cache must be an absolute path")
        self.settings = {"retention_days": days, "models_dev_cache": cache}
        state, text, num = ctx.state, "TEXT", "INTEGER"
        counters = [(c, num) for c in _COLS]
        state.create_table(
            "daily",
            [("day", text), ("provider", text), ("model", text), *counters],
            primary_key=["day", "provider", "model"],
        )
        state.create_table(
            "hourly",
            [("hour", text), ("provider", text), ("model", text), *counters],
            primary_key=["hour", "provider", "model"],
        )
        state.create_table(
            "subagents",
            [("day", text), ("role", text), ("status", text), ("runs", num), ("duration_ms", num)],
            primary_key=["day", "role", "status"],
        )
        state.create_table(
            "quotas",
            [
                ("name", text),
                ("scope", text),
                ("metric", text),
                ("period", text),
                ("limit_value", "REAL"),
                ("thresholds", text),
            ],
            primary_key=["name"],
        )
        state.create_table(
            "fired",
            [("name", text), ("period_key", text), ("percent", num), ("at", text)],
            primary_key=["name", "period_key", "percent"],
        )
        read_only = {"summary", "usage", "quotas", "forecast"}
        params: dict[str, dict[str, type]] = {
            "summary": {"days": int},
            "usage": {"day": str, "provider": str},
            "quotas": {},
            "forecast": {"name": str},
            "quota_add": {
                "name": str,
                "scope": str,
                "metric": str,
                "period": str,
                "limit": str,
                "thresholds": str,
            },
            "quota_remove": {"name": str},
            "prices_reload": {},
        }
        for name, spec in params.items():
            ctx.register_action(name, getattr(self, name), params=spec, read_only=name in read_only)
        ctx.register_panel("meter.status", self.status)
        ctx.hermes_hook("post_api_request", self.on_response)
        ctx.hermes_hook("api_request_error", self.on_error)
        ctx.hermes_hook("subagent_stop", self.on_subagent)
        self.ctx = ctx
        self._load_prices()

    def deactivate(self) -> None:
        self.ctx = None

    def health(self) -> tuple[bool, str]:
        if self.ctx is None:
            return False, "stopped"
        return True, f"{len(self.prices)} model prices, {len(self._quota_rows())} quotas"

    # helpers ------------------------------------------------------------------------------------------

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self.clock(), UTC)

    def _load_prices(self) -> int:
        if not self.ctx.has("fs.read"):
            self.prices = {}
            return 0
        try:
            doc = self.ctx.fs.read_json(self.settings["models_dev_cache"], max_bytes=32 << 20)
        except SwitchyardError as exc:
            self.ctx.log("meter", "prices_unavailable", error=type(exc).__name__)
            self.prices = {}
            return 0
        self.prices = parse_prices(doc)
        return len(self.prices)

    def _add(
        self, table: str, key_cols: tuple[str, str, str], key: tuple[str, str, str], values: Mapping[str, int]
    ) -> None:
        cols = ", ".join((*key_cols, *_COLS))
        marks = ", ".join("?" for _ in (*key_cols, *_COLS))
        updates = ", ".join(f"{c} = {c} + excluded.{c}" for c in _COLS)
        sql = (
            f"INSERT INTO {self._t(table)} ({cols}) VALUES ({marks}) "  # nosec B608
            f"ON CONFLICT({', '.join(key_cols)}) DO UPDATE SET {updates}"
        )
        self._q(sql, (*key, *(int(values.get(c, 0)) for c in _COLS)))

    def _record(self, provider: str, model: str, values: Mapping[str, int]) -> None:
        now = self._now()
        day, hour = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%dT%H")
        with self._lock:
            self._add("daily", ("day", "provider", "model"), (day, provider, model), values)
            self._add("hourly", ("hour", "provider", "model"), (hour, provider, model), values)
            if hour != self._pruned_hour:
                self._pruned_hour = hour
                self._prune(now)
            self._check_quotas(now)

    def _prune(self, now: datetime) -> None:
        keep_day = (now - timedelta(days=self.settings["retention_days"])).strftime("%Y-%m-%d")
        keep_hour = (now - timedelta(days=HOURLY_DAYS)).strftime("%Y-%m-%dT%H")
        self._q(f"DELETE FROM {self._t('daily')} WHERE day < ?", (keep_day,))  # nosec B608
        self._q(f"DELETE FROM {self._t('subagents')} WHERE day < ?", (keep_day,))  # nosec B608
        self._q(f"DELETE FROM {self._t('hourly')} WHERE hour < ?", (keep_hour,))  # nosec B608

    @staticmethod
    def _model_key(provider: Any, model: Any) -> tuple[str, str] | None:
        if not isinstance(provider, str) or not isinstance(model, str):
            return None
        provider, model = provider[:64], model[:200]
        if not _KEY.match(provider) or not _KEY.match(f"{provider}/{model}"):
            return None
        return provider, model

    # Hermes hooks (metadata only, ADR-0004) -----------------------------------------------------------

    def on_response(self, kw: dict[str, Any]) -> None:
        if self.ctx is None:
            return
        served = kw.get("response_model") or (kw.get("response") or {}).get("model")
        # H1 C-5: the bridge adds the model the request actually went out with (after routing)
        sent = kw.get("sent_model") or (kw.get("request") or {}).get("body", {}).get("model")
        key = self._model_key(kw.get("provider"), sent or served or kw.get("model"))
        if key is None:
            return
        usage = kw.get("usage")
        values: dict[str, int] = {"requests": 1}
        if not isinstance(usage, dict):
            values["usage_missing"] = 1
        else:
            flagged = False
            for bucket in BUCKETS:
                values[bucket], bad = _count(usage.get(bucket))
                flagged = flagged or bad
            if flagged:
                values["usage_missing"] = 1
                self.ctx.log("meter", "bad_usage", provider=key[0], model=key[1])
        price = self.prices.get(f"{key[0]}/{key[1]}")
        if price is None:
            values["unpriced"] = 1
        else:  # USD per million tokens x tokens = micro-USD
            values["cost_micro"] = round(
                sum(values.get(b, 0) * price.get(b, price["input_tokens"]) for b in _PRICE_KEYS)
            )
        self._record(*key, values)

    def on_error(self, kw: dict[str, Any]) -> None:
        if self.ctx is None:
            return
        sent = kw.get("sent_model") or (kw.get("request") or {}).get("body", {}).get("model")
        key = self._model_key(kw.get("provider"), sent or kw.get("model"))
        if key is not None:
            self._record(*key, {"errors": 1})

    def on_subagent(self, kw: dict[str, Any]) -> None:
        if self.ctx is None:
            return
        role = str(kw.get("child_role") or "unknown")[:64]
        status = str(kw.get("child_status") or "unknown")[:32]
        duration, _ = _count(kw.get("duration_ms"))
        day = self._now().strftime("%Y-%m-%d")
        sql = (
            f"INSERT INTO {self._t('subagents')} VALUES (?, ?, ?, 1, ?) "  # nosec B608
            "ON CONFLICT(day, role, status) DO UPDATE SET runs = runs + 1, "
            "duration_ms = duration_ms + excluded.duration_ms"
        )
        self._q(sql, (day, role, status, duration))

    # quotas -------------------------------------------------------------------------------------------

    def _quota_rows(self) -> list[dict[str, Any]]:
        rows = self._q(
            f"SELECT name, scope, metric, period, limit_value, thresholds FROM {self._t('quotas')} "  # nosec B608
            "ORDER BY name"
        )
        keys = ("name", "scope", "metric", "period", "limit", "thresholds")
        out = [dict(zip(keys, r, strict=True)) for r in rows]
        for q in out:
            q["thresholds"] = [int(t) for t in q["thresholds"].split(",")]
        return out

    @staticmethod
    def _period_bounds(period: str, now: datetime) -> tuple[str, datetime, datetime]:
        if period == "day":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start.strftime("%Y-%m-%d"), start, start + timedelta(days=1)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=32)).replace(day=1)
        return start.strftime("%Y-%m"), start, end

    def _used(self, quota: Mapping[str, Any], now: datetime) -> float:
        key, _, _ = self._period_bounds(quota["period"], now)
        where, args = ["day LIKE ?"], [key + "%"]
        scope = quota["scope"]
        if scope.startswith("provider:"):
            where.append("provider = ?")
            args.append(scope.split(":", 1)[1])
        elif scope != "all":
            provider, _, model = scope.partition("/")
            where += ["provider = ?", "model = ?"]
            args += [provider, model]
        metric = {
            "requests": "sum(requests)",
            "cost_usd": "sum(cost_micro) / 1000000.0",
            "tokens": " + ".join(f"sum({b})" for b in BUCKETS if b != "reasoning_tokens"),
        }[quota["metric"]]
        sql = f"SELECT {metric} FROM {self._t('daily')} WHERE {' AND '.join(where)}"  # nosec B608
        value = self._q(sql, tuple(args))[0][0]
        return float(value or 0)

    def _check_quotas(self, now: datetime) -> None:
        for quota in self._quota_rows():
            used = self._used(quota, now)
            key, _, end = self._period_bounds(quota["period"], now)
            for percent in quota["thresholds"]:
                if used < quota["limit"] * percent / 100:
                    continue
                fired = self._t("fired")
                exists = self._q(
                    f"SELECT 1 FROM {fired} WHERE name = ? AND period_key = ? AND percent = ?",  # nosec B608
                    (quota["name"], key, percent),
                )
                if exists:
                    continue
                self._q(
                    f"INSERT INTO {fired} VALUES (?, ?, ?, ?)",  # nosec B608
                    (quota["name"], key, percent, now.strftime("%Y-%m-%dT%H:%M:%SZ")),
                )
                data = {
                    "quota": quota["name"],
                    "scope": quota["scope"],
                    "metric": quota["metric"],
                    "percent": percent,
                    "used": round(used, 6),
                    "limit": quota["limit"],
                    "period": key,
                    "period_end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                self.ctx.audit("threshold", quota=quota["name"], percent=str(percent), period=key)
                self.ctx.emit("meter.threshold", data)
                if percent >= 100:
                    self.ctx.emit("meter.exhausted", data)

    # actions ------------------------------------------------------------------------------------------

    def summary(self, days: int = 7) -> dict[str, Any]:
        if not 1 <= days <= 366:
            raise SwitchyardError("days must be from 1 to 366")
        since = (self._now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        cols = ", ".join(f"sum({c})" for c in _COLS)
        sql = (
            f"SELECT provider, model, {cols} FROM {self._t('daily')} WHERE day >= ? GROUP BY provider, model "  # nosec B608
        )
        rows = self._q(sql + "ORDER BY sum(cost_micro) DESC, sum(requests) DESC LIMIT 201", (since,))
        models = [self._usage_row(r[0], r[1], r[2:]) for r in rows[:200]]
        whole = self._q(f"SELECT {cols} FROM {self._t('daily')} WHERE day >= ?", (since,))[0]  # nosec B608
        all_rows = self._usage_row("", "", whole)
        totals = {c: all_rows[c] for c in ("requests", "tokens", "errors", "cost_usd")}
        return {
            "since": since,
            "totals": totals,
            "models": models,
            "truncated": len(rows) > 200,
            "cost_note": "estimate from models.dev prices; 'unpriced' responses add no cost",
        }

    @staticmethod
    def _usage_row(provider: str, model: str, values: tuple[Any, ...]) -> dict[str, Any]:
        v = dict(zip(_COLS, (int(x or 0) for x in values), strict=True))
        tokens = sum(v[b] for b in BUCKETS if b != "reasoning_tokens")
        return {
            "provider": provider,
            "model": model,
            "requests": v["requests"],
            "tokens": tokens,
            **{b: v[b] for b in BUCKETS},
            "cost_usd": v["cost_micro"] / 1_000_000,
            "unpriced": v["unpriced"],
            "usage_missing": v["usage_missing"],
            "errors": v["errors"],
        }

    def usage(self, day: str = "", provider: str = "") -> dict[str, Any]:
        day = day or self._now().strftime("%Y-%m-%d")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise SwitchyardError("day must look like YYYY-MM-DD")
        where, args = "day = ?", [day]
        if provider:
            where += " AND provider = ?"
            args.append(provider)
        cols = ", ".join(_COLS)
        sql = f"SELECT provider, model, {cols} FROM {self._t('daily')} WHERE {where} "  # nosec B608
        sql += "ORDER BY provider, model LIMIT 1000"
        rows = self._q(sql, tuple(args))
        sub_sql = (f"SELECT role, status, runs, duration_ms FROM {self._t('subagents')} WHERE day = ? "  # nosec B608
                   "ORDER BY runs DESC LIMIT 200")  # fmt: skip
        subs = self._q(sub_sql, (day,))
        return {
            "day": day,
            "models": [self._usage_row(r[0], r[1], r[2:]) for r in rows],
            "subagents": [{"role": r[0], "status": r[1], "runs": r[2], "duration_ms": r[3]} for r in subs],
        }

    def quotas(self) -> dict[str, Any]:
        now = self._now()
        out = []
        for q in self._quota_rows():
            used = self._used(q, now)
            out.append(
                {
                    **q,
                    "used": round(used, 6),
                    "percent": round(100 * used / q["limit"], 1) if q["limit"] else 0,
                }
            )
        return {"quotas": out}

    def forecast(self, name: str) -> dict[str, Any]:
        quota = next((q for q in self._quota_rows() if q["name"] == name), None)
        if quota is None:
            raise SwitchyardError(f"no quota {name!r}")
        now = self._now()
        _, start, end = self._period_bounds(quota["period"], now)
        used = self._used(quota, now)
        window_start = max(start, now - timedelta(hours=24))
        hours = max((now - window_start).total_seconds() / 3600, 1 / 60)
        recent = self._recent(quota, window_start)
        rate = recent / hours
        remaining = max(quota["limit"] - used, 0.0)
        left_h = (end - now).total_seconds() / 3600
        exhausted_at = None
        if remaining == 0:
            exhausted_at = now
        elif rate > 0 and remaining / rate < left_h:
            exhausted_at = now + timedelta(hours=remaining / rate)
        return {
            "quota": name,
            "used": round(used, 6),
            "limit": quota["limit"],
            "rate_per_hour": round(rate, 6),
            "projected_period_total": round(used + rate * left_h, 6),
            "exhausted_at": exhausted_at.strftime("%Y-%m-%dT%H:%M:%SZ") if exhausted_at else None,
            "period_end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "method": "average rate over the last 24 hours (or since the period start)",
        }

    def _recent(self, quota: Mapping[str, Any], since: datetime) -> float:
        where, args = ["hour >= ?"], [since.strftime("%Y-%m-%dT%H")]
        scope = quota["scope"]
        if scope.startswith("provider:"):
            where.append("provider = ?")
            args.append(scope.split(":", 1)[1])
        elif scope != "all":
            provider, _, model = scope.partition("/")
            where += ["provider = ?", "model = ?"]
            args += [provider, model]
        metric = {
            "requests": "sum(requests)",
            "cost_usd": "sum(cost_micro) / 1000000.0",
            "tokens": " + ".join(f"sum({b})" for b in BUCKETS if b != "reasoning_tokens"),
        }[quota["metric"]]
        sql = f"SELECT {metric} FROM {self._t('hourly')} WHERE {' AND '.join(where)}"  # nosec B608
        return float(self._q(sql, tuple(args))[0][0] or 0)

    def quota_add(
        self, name: str, scope: str, metric: str, period: str, limit: str, thresholds: str = "80,100"
    ) -> dict[str, Any]:
        """``limit`` is a decimal string: requests, tokens or USD depending on ``metric``."""
        if not _NAME.match(name):
            raise SwitchyardError(f"invalid quota name {name[:64]!r}")
        if scope.startswith("provider:"):  # provider ids are stored lower-case; model ids keep their case
            scope = scope.lower()
        elif "/" in scope:
            head, _, tail = scope.partition("/")
            scope = f"{head.lower()}/{tail}"
        if not _SCOPE.match(scope):
            raise SwitchyardError(
                "scope must be 'all', 'provider:<id>' or a resource id '<provider>/<model>'"
            )
        if metric not in METRICS or period not in PERIODS:
            raise SwitchyardError(f"metric must be one of {list(METRICS)}, period one of {list(PERIODS)}")
        try:
            value = float(limit)
        except ValueError:
            raise SwitchyardError("limit must be a positive number") from None
        if not 0 < value <= 1e12:  # also rejects nan and inf
            raise SwitchyardError("limit must be a positive number")
        try:
            marks = sorted({int(t) for t in thresholds.split(",")})
        except ValueError:
            raise SwitchyardError("thresholds must be comma-separated percentages") from None
        if not marks or len(marks) > 10 or not all(1 <= t <= 100 for t in marks):
            raise SwitchyardError("thresholds must be 1 to 10 percentages from 1 to 100")
        # 100 always fires meter.exhausted: without it the router never cools the scope (R1 review)
        marks = sorted({*marks, 100})
        if metric == "cost_usd" and not self.prices:
            raise SwitchyardError(
                "no model prices are loaded, so a cost quota would never move; run prices_reload"
            )
        sql = f"INSERT OR REPLACE INTO {self._t('quotas')} VALUES (?, ?, ?, ?, ?, ?)"  # nosec B608
        with self._lock:  # never interleave with a threshold check (_record)
            self._q(sql, (name, scope, metric, period, value, ",".join(map(str, marks))))
        self.ctx.audit("quota_add", quota=name, scope=scope, metric=metric, period=period, limit=str(value))
        return {
            "quota": name,
            "scope": scope,
            "metric": metric,
            "period": period,
            "limit": value,
            "thresholds": marks,
        }

    def quota_remove(self, name: str) -> dict[str, Any]:
        if not _NAME.match(name):
            raise SwitchyardError(f"invalid quota name {name[:64]!r}")
        with self._lock:
            self._q(f"DELETE FROM {self._t('quotas')} WHERE name = ?", (name,))  # nosec B608
            self._q(f"DELETE FROM {self._t('fired')} WHERE name = ?", (name,))  # nosec B608
        self.ctx.audit("quota_remove", quota=name)
        return {"removed": name}

    def prices_reload(self) -> dict[str, Any]:
        return {"prices": self._load_prices()}

    def status(self) -> dict[str, Any]:
        today = self.summary(days=1)["totals"]
        return {"today": today, "prices": len(self.prices), "quotas": self.quotas()["quotas"]}
