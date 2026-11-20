"""M3 router and failover (spec: README.md in this directory).

Hermes ``llm_request`` middleware (through the core bridge, ADR-0004) picks the model for each request from
the consumer's pool in the resource registry (``resources.resolve``), within the active provider. Free and
self-hosted first; a paid resource only with the ``llm.paid`` grant, a rule for the consumer and tier, and
daily budget left. A failed request (``api_request_error``) cools its resource down, and Hermes's next retry
gets the next candidate; after ``max_attempts`` failures in one turn the router stops rewriting.

Settings, ``[modules.router]``::

    consumer = "main"          # registry consumer whose pool is routed
    providers = ["openrouter"] # Hermes provider ids the router acts on
    max_attempts = 3
    cooldown_seconds = 60
"""

from __future__ import annotations

import re
import secrets as _random
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from switchyard.errors import SwitchyardError

from .engine import TIERS, Candidate, Need, candidates_from, need_for, rank, tier_for, unfit

_CONSUMER = re.compile(r"(main|(subagent|function|agent):[A-Za-z0-9._-]{1,64})\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}\Z")
_PROVIDER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
KEEP_DECISIONS = 1000
_TURNS = 1000


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def _check(pattern: re.Pattern[str], value: Any, what: str) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise SwitchyardError(f"invalid {what} {str(value)[:80]!r}")
    return value


def _int_setting(cfg: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    value = cfg.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SwitchyardError(f"[modules.router] {key} must be an integer from {low} to {high}")
    return value


class RouterModule:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.ctx: Any = None
        self.clock = clock
        self.settings: dict[str, Any] = {}
        self._failures: OrderedDict[str, int] = OrderedDict()  # turn id -> failed attempts (bounded)
        self._sent: OrderedDict[str, str] = OrderedDict()  # api request id -> resource sent (bounded)
        self._warned: dict[str, str] = {}  # resource -> day a paid pass-through was last audited
        self._lock = threading.Lock()
        self._seq = 0

    # lifecycle ----------------------------------------------------------------------------------------

    def activate(self, ctx: Any) -> None:
        cfg = dict(ctx.config)
        unknown = set(cfg) - {"consumer", "providers", "max_attempts", "cooldown_seconds", "hard_stop"}
        if unknown:
            raise SwitchyardError(f"unknown [modules.router] setting(s) {sorted(unknown)}")
        providers = cfg.get("providers", ["openrouter"])
        if not isinstance(providers, list) or not providers:
            raise SwitchyardError("[modules.router] providers must be a non-empty list")
        self.settings = {
            "consumer": _check(_CONSUMER, cfg.get("consumer", "main"), "consumer"),
            "providers": [_check(_PROVIDER, p, "provider") for p in providers],
            "max_attempts": _int_setting(cfg, "max_attempts", 3, 1, 10),
            "cooldown_seconds": _int_setting(cfg, "cooldown_seconds", 60, 5, 86_400),
            "hard_stop": cfg.get("hard_stop", False),
        }
        if not isinstance(self.settings["hard_stop"], bool):
            raise SwitchyardError("[modules.router] hard_stop must be true or false")
        state, text, num = ctx.state, "TEXT", "INTEGER"
        state.create_table("rules", [("consumer", text), ("min_tier", text)], primary_key=["consumer"])
        state.create_table("pins", [("consumer", text), ("resource", text)], primary_key=["consumer"])
        state.create_table("cooldowns", [("resource", text), ("until", "REAL"), ("reason", text)],
                           primary_key=["resource"])  # fmt: skip
        state.create_table("spend", [("day", text), ("paid", num)], primary_key=["day"])
        state.create_table("kv", [("key", text), ("value", text)], primary_key=["key"])
        state.create_table(
            "decisions",
            [("id", text), ("at", text), ("consumer", text), ("tier", text), ("tokens", num),
             ("chosen", text), ("cost_class", text), ("reason", text)],
            primary_key=["id"],
        )  # fmt: skip
        read_only = {"status", "explain"}
        params: dict[str, dict[str, type]] = {
            "status": {},
            "explain": {"tokens": int, "tools": bool, "vision": bool},
            "pin": {"consumer": str, "id": str},
            "auto": {"consumer": str},
            "rule_add": {"consumer": str, "min_tier": str},
            "rule_remove": {"consumer": str},
            "budget": {"paid_requests_per_day": int},
            "cooldown_clear": {"id": str},
        }
        for name, spec in params.items():
            ctx.register_action(name, getattr(self, name), params=spec, read_only=name in read_only)
        ctx.register_panel("router.status", self.status)
        ctx.hermes_middleware("llm_request", self.route)
        ctx.hermes_hook("api_request_error", self.on_error)
        ctx.subscribe("meter.exhausted", self.on_exhausted)
        if self.settings["hard_stop"]:
            ctx.hermes_gate(self.gate)
        self.ctx = ctx

    def deactivate(self) -> None:
        self.ctx = None

    def health(self) -> tuple[bool, str]:
        if self.ctx is None:
            return False, "stopped"
        return True, f"routing {self.settings['consumer']} on {', '.join(self.settings['providers'])}"

    # storage helpers ----------------------------------------------------------------------------------

    def _q(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = self.ctx.state.execute(sql, params)
        return rows

    def _t(self, name: str) -> str:
        return str(self.ctx.state.table(name))

    def _cooling(self) -> dict[str, str]:
        sql = f"SELECT resource, reason FROM {self._t('cooldowns')} WHERE until > ?"  # nosec B608
        rows = self._q(sql, (self.clock(),))
        return {r[0]: r[1] for r in rows}

    def _budget(self) -> int:
        rows = self._q(f"SELECT value FROM {self._t('kv')} WHERE key = 'paid_requests_per_day'")  # nosec B608
        return int(rows[0][0]) if rows else 0

    def _spent_today(self) -> int:
        rows = self._q(f"SELECT paid FROM {self._t('spend')} WHERE day = ?", (_day(self.clock()),))  # nosec B608
        return int(rows[0][0]) if rows else 0

    def _paid_ok(self, consumer: str, tier: str) -> bool:
        if not self.ctx.has("llm.paid"):
            return False
        rule = self._q(f"SELECT min_tier FROM {self._t('rules')} WHERE consumer = ?", (consumer,))  # nosec B608
        if not rule or TIERS.index(tier) < TIERS.index(rule[0][0]):
            return False
        return self._spent_today() < self._budget()

    def _candidates(self, provider: str) -> list[Candidate]:
        try:
            resolved = self.ctx.call("resources", "resolve", {"consumer": self.settings["consumer"]})
        except SwitchyardError:
            return []  # registry not running: pass requests through unchanged
        found = candidates_from(resolved.get("resources", []), provider)
        if not self.ctx.has("llm.free"):  # free and self-hosted resources need the llm.free grant
            found = [c for c in found if c.cost_class == "paid"]
        return found

    def _effective_cooling(self, provider: str, candidates: list[Candidate]) -> dict[str, str]:
        """Cooling resource ids, with quota scopes (``all``, ``provider:<id>``) applied to every candidate."""
        cooling = self._cooling()
        scope = "all" if "all" in cooling else f"provider:{provider}"
        if scope in cooling:
            cooling.update({c.id: cooling[scope] for c in candidates})
        return cooling

    def _record(self, need: Need, chosen: Candidate | None, reason: str) -> None:
        t = self._t("decisions")
        now = self.clock()
        at = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._seq += 1  # orders decisions made within the same millisecond
        key = f"{int(now * 1000):014d}{self._seq % 1_000_000:06d}{_random.token_hex(3)}"
        chosen_id, cost = (chosen.id, chosen.cost_class) if chosen else ("", "")
        row = (key, at, self.settings["consumer"], need.tier, need.tokens, chosen_id, cost, reason)
        self._q(f"INSERT INTO {t} VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)  # nosec B608
        count = self._q(f"SELECT count(*) FROM {t}")[0][0]  # nosec B608
        if count > KEEP_DECISIONS:
            oldest = self._q(f"SELECT id FROM {t} ORDER BY id LIMIT ?", (count - KEEP_DECISIONS,))  # nosec B608
            for (old,) in oldest:
                self._q(f"DELETE FROM {t} WHERE id = ?", (old,))  # nosec B608

    def _charge_paid(self, need: Need, chosen: Candidate) -> None:
        day = _day(self.clock())
        spend = self._t("spend")
        sql = (f"INSERT INTO {spend} VALUES (?, 1) "  # nosec B608
               "ON CONFLICT(day) DO UPDATE SET paid = paid + 1")  # fmt: skip
        self._q(sql, (day,))
        self.ctx.audit(
            "paid_decision", consumer=self.settings["consumer"], tier=need.tier, resource=chosen.id
        )

    # Hermes callbacks ---------------------------------------------------------------------------------

    def choose(self, need: Need, provider: str) -> tuple[Candidate | None, str, dict[str, str]]:
        consumer = self.settings["consumer"]
        candidates = self._candidates(provider)
        cooling = self._effective_cooling(provider, candidates)
        paid_ok = self._paid_ok(consumer, need.tier)
        pin = self._q(f"SELECT resource FROM {self._t('pins')} WHERE consumer = ?", (consumer,))  # nosec B608
        if pin:
            pinned = next((c for c in candidates if c.id == pin[0][0]), None)
            if pinned is not None and unfit(pinned, need, cooling=cooling, paid_ok=paid_ok) is None:
                return pinned, "pinned", {}  # pins obey paid gating too
        usable, skipped = rank(candidates, need, cooling=cooling, paid_ok=paid_ok)
        if not usable:
            return None, "no candidate", skipped
        return usable[0], "free first" if usable[0].cost_class != "paid" else "paid rule", skipped

    def route(self, request: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
        provider = context.get("provider")
        if self.ctx is None or provider not in self.settings["providers"]:
            return None
        with self._lock:  # choice and paid-budget charge are one step (concurrent Hermes requests)
            chosen, need, reason = self._decide(request, str(provider), str(context.get("turn_id") or ""))
            if chosen is not None and chosen.cost_class == "paid":
                self._charge_paid(need, chosen)
        if chosen is None:
            return None
        self._sent[str(context.get("api_request_id") or "")] = chosen.id
        while len(self._sent) > _TURNS:
            self._sent.popitem(last=False)
        if chosen.model == request.get("model"):
            return None
        self.ctx.log("router", "route", tier=need.tier, chosen=chosen.id, reason=reason)
        return {**request, "model": chosen.model}

    def _decide(
        self, request: dict[str, Any], provider: str, turn: str
    ) -> tuple[Candidate | None, Need, str]:
        need = need_for(request)
        if self._failures.get(turn, 0) >= self.settings["max_attempts"]:
            chosen, reason = None, "attempts exhausted"
        else:
            chosen, reason, _ = self.choose(need, provider)
        if chosen is None:
            chosen, reason = self._guard_paid_default(request, need, provider, reason)
        self._record(need, chosen, reason)
        return chosen, need, reason

    def _guard_paid_default(
        self, request: dict[str, Any], need: Need, provider: str, reason: str
    ) -> tuple[Candidate | None, str]:
        """Nothing fits, so Hermes's configured model would go out unchanged. If that model is a paid resource
        while paid is not allowed, or its quota scope is exhausted, use any free or self-hosted ``auto``
        resource that is not cooling down instead (size and tag checks ignored). Middleware cannot refuse a
        request, so if there is no such resource the configured model is passed through and that is audited
        once per resource and day (``paid_passthrough`` / ``quota_passthrough``)."""
        fallback, why, rid = self._guard_eval(str(request.get("model") or ""), need, provider)
        if not why:
            return None, reason
        if fallback is not None:
            return fallback, f"{reason}; {why}"
        quota_hit = why == "quota exhausted"
        event = "quota_passthrough" if quota_hit else "paid_passthrough"
        day = _day(self.clock())
        if self._warned.get(f"{event}:{rid}") != day:
            self._warned[f"{event}:{rid}"] = day
            self.ctx.audit(event, consumer=self.settings["consumer"], resource=rid[:200])
        return None, f"{reason}; {why}, passed through"

    def _guard_eval(self, model: str, need: Need, provider: str) -> tuple[Candidate | None, str, str]:
        """(fallback, why, resource id) for the configured ``model``: ``why`` is empty when it may go out."""
        candidates = self._candidates(provider)
        cooling = self._effective_cooling(provider, candidates)
        current = next((c for c in candidates if c.model == model), None)
        rid = current.id if current else f"{provider}/{model}"
        raw = self._cooling()
        quota_hit = any(k in raw and raw[k].startswith("quota") for k in ("all", f"provider:{provider}", rid))
        paid_blocked = (
            current is not None
            and current.cost_class == "paid"
            and not self._paid_ok(self.settings["consumer"], need.tier)
        )
        if not (paid_blocked or quota_hit):
            return None, "", rid
        why = "quota exhausted" if quota_hit else "configured model is paid"
        fallback = next((c for c in candidates if c.cost_class != "paid" and c.state == "auto"
                         and c.id not in cooling), None)  # fmt: skip
        return fallback, why, rid

    def gate(self, meta: dict[str, Any]) -> str | None:
        """``hard_stop`` (ADR-0006): block the turn when no routed choice is possible and the configured model
        is over an exhausted quota or is paid while paid is not allowed. Sized as the smallest tier."""
        provider = meta.get("provider") or (
            self.settings["providers"][0] if self.settings["providers"] else ""
        )
        if self.ctx is None or provider not in self.settings["providers"]:
            return None
        need = Need(tokens=1, tools=False, vision=False, tier="T1")
        with self._lock:
            chosen, _, _ = self.choose(need, provider)
            if chosen is not None:
                return None
            fallback, why, rid = self._guard_eval(str(meta.get("model") or ""), need, provider)
        if not why or fallback is not None:
            return None
        self.ctx.audit("hard_stop", consumer=self.settings["consumer"], resource=rid[:200], reason=why)
        return (
            f"Request blocked: {why} for {rid} and no free model is available. "
            "Ask the operator to raise the quota or allow paid use."
        )

    def _sent_model(self, kwargs: dict[str, Any]) -> str | None:
        """The resource a failed request actually used: what ``route`` sent for this request id, else the
        model in Hermes's sanitized payload ``{"method", "body": {...}}``, else the configured model."""
        rid = self._sent.get(str(kwargs.get("api_request_id") or ""))
        if rid is not None:
            return rid
        raw = kwargs.get("request")
        body = raw.get("body") if isinstance(raw, dict) else None
        model = body.get("model") if isinstance(body, dict) else None
        if not isinstance(model, str):
            model = kwargs.get("model")
        return f"{kwargs.get('provider')}/{model}" if isinstance(model, str) else None

    def on_error(self, kwargs: dict[str, Any]) -> None:
        provider = kwargs.get("provider")
        if self.ctx is None or provider not in self.settings["providers"]:
            return
        rid = self._sent_model(kwargs)
        if rid is None or not _ID.match(rid):
            return
        turn = str(kwargs.get("turn_id") or "")
        self._failures[turn] = self._failures.get(turn, 0) + 1
        self._failures.move_to_end(turn)
        while len(self._failures) > _TURNS:
            self._failures.popitem(last=False)
        status = kwargs.get("status_code")
        seconds = self.settings["cooldown_seconds"]
        if isinstance(status, int) and status in (401, 402, 403, 404):
            seconds *= 10  # this resource is not usable with these credentials
        elif isinstance(status, int) and status != 429 and status < 500:
            return  # 400, 413, 422 ...: caused by the request, not the resource; counts as an attempt only
        reason = f"http {status}" if isinstance(status, int) else "error"
        sql = f"INSERT OR REPLACE INTO {self._t('cooldowns')} VALUES (?, ?, ?)"  # nosec B608
        self._q(sql, (rid, self.clock() + seconds, reason))
        self.ctx.log("router", "cooldown", resource=rid, reason=reason, seconds=seconds)

    def on_exhausted(self, event: Any) -> None:
        """``meter.exhausted``: cool the quota's scope down until the end of the quota period."""
        data = getattr(event, "data", {})
        scope, end = data.get("scope"), data.get("period_end")
        if self.ctx is None or not isinstance(scope, str) or not isinstance(end, str):
            return
        if not (scope == "all" or scope.startswith("provider:") or _ID.match(scope)):
            return
        try:
            until = datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
        except ValueError:
            return
        until = min(until, self.clock() + 32 * 86_400)
        sql = f"INSERT OR REPLACE INTO {self._t('cooldowns')} VALUES (?, ?, ?)"  # nosec B608
        self._q(sql, (scope[:200], until, f"quota {str(data.get('quota'))[:64]} exhausted"))
        self.ctx.log("router", "quota_cooldown", scope=scope, until=end)

    # actions ------------------------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        rules = self._q(f"SELECT consumer, min_tier FROM {self._t('rules')} ORDER BY consumer")  # nosec B608
        pins = self._q(f"SELECT consumer, resource FROM {self._t('pins')} ORDER BY consumer")  # nosec B608
        recent = self._q(
            f"SELECT at, consumer, tier, tokens, chosen, cost_class, reason FROM {self._t('decisions')} "  # nosec B608
            "ORDER BY id DESC LIMIT 20"
        )
        keys = ("at", "consumer", "tier", "tokens", "chosen", "cost_class", "reason")
        return {
            **self.settings,
            "rules": dict(rules),
            "pins": dict(pins),
            "paid_requests_per_day": self._budget(),
            "paid_today": self._spent_today(),
            "cooling": self._cooling(),
            "recent": [dict(zip(keys, r, strict=True)) for r in recent],
        }

    def explain(self, tokens: int = 1000, tools: bool = False, vision: bool = False) -> dict[str, Any]:
        if not 1 <= tokens <= 10_000_000:
            raise SwitchyardError("tokens must be from 1 to 10000000")
        need = Need(tokens=tokens, tools=tools, vision=vision, tier=tier_for(tokens))
        out = []
        for provider in self.settings["providers"]:
            chosen, reason, skipped = self.choose(need, provider)
            out.append({"provider": provider, "chosen": chosen.id if chosen else None, "reason": reason,
                        "skipped": skipped})  # fmt: skip
        return {
            "tier": need.tier,
            "paid_allowed": self._paid_ok(self.settings["consumer"], need.tier),
            "providers": out,
        }

    def pin(self, consumer: str, id: str) -> dict[str, Any]:
        _check(_CONSUMER, consumer, "consumer")
        _check(_ID, id, "resource id")
        self._q(f"INSERT OR REPLACE INTO {self._t('pins')} VALUES (?, ?)", (consumer, id))  # nosec B608
        self.ctx.audit("pin", consumer=consumer, resource=id)
        return {"consumer": consumer, "pinned": id}

    def auto(self, consumer: str) -> dict[str, Any]:
        _check(_CONSUMER, consumer, "consumer")
        self._q(f"DELETE FROM {self._t('pins')} WHERE consumer = ?", (consumer,))  # nosec B608
        self.ctx.audit("auto", consumer=consumer)
        return {"consumer": consumer, "pinned": None}

    def rule_add(self, consumer: str, min_tier: str) -> dict[str, Any]:
        _check(_CONSUMER, consumer, "consumer")
        if min_tier not in TIERS:
            raise SwitchyardError(f"min_tier must be one of {list(TIERS)}")
        self._q(f"INSERT OR REPLACE INTO {self._t('rules')} VALUES (?, ?)", (consumer, min_tier))  # nosec B608
        self.ctx.audit("rule_add", consumer=consumer, min_tier=min_tier)
        return {"consumer": consumer, "paid_from_tier": min_tier}

    def rule_remove(self, consumer: str) -> dict[str, Any]:
        _check(_CONSUMER, consumer, "consumer")
        self._q(f"DELETE FROM {self._t('rules')} WHERE consumer = ?", (consumer,))  # nosec B608
        self.ctx.audit("rule_remove", consumer=consumer)
        return {"consumer": consumer, "paid_from_tier": None}

    def budget(self, paid_requests_per_day: int) -> dict[str, Any]:
        if not 0 <= paid_requests_per_day <= 1_000_000:
            raise SwitchyardError("paid_requests_per_day must be from 0 to 1000000")
        sql = f"INSERT OR REPLACE INTO {self._t('kv')} VALUES ('paid_requests_per_day', ?)"  # nosec B608
        self._q(sql, (str(paid_requests_per_day),))
        self.ctx.audit("budget", paid_requests_per_day=str(paid_requests_per_day))
        return {"paid_requests_per_day": paid_requests_per_day}

    def cooldown_clear(self, id: str) -> dict[str, Any]:
        _check(_ID, id, "resource id")
        self._q(f"DELETE FROM {self._t('cooldowns')} WHERE resource = ?", (id,))  # nosec B608
        return {"cleared": id}
