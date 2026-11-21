"""M3 router and failover (spec: README.md in this directory).

Hermes ``llm_request`` middleware (through the core bridge, ADR-0004) picks the model for each request from
the consumer's pool in the resource registry (``resources.resolve``), within the active provider. Free and
self-hosted first; a paid resource only with the ``llm.paid`` grant, a rule for the consumer and tier, and
daily budget left. A failed request (``api_request_error``) cools its resource down, and Hermes's next retry
gets the next candidate; after ``max_attempts`` failures in one turn the router stops rewriting.

A route that misses the bridge deadline fails closed (ADR-0013): ``route_timeout`` sends a free candidate
remembered from an earlier route, or lets the configured model through and charges it if it is paid (with
``hard_stop`` also blocking the next turn). A late route result never charges or records its own choice.

Settings, ``[modules.router]``::

    consumer = "main"          # registry consumer whose pool is routed
    providers = ["openrouter"] # Hermes provider ids the router acts on
    max_attempts = 3
    cooldown_seconds = 60
"""

from __future__ import annotations

import contextlib
import re
import secrets as _random
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from typing import Any

from switchyard.errors import SwitchyardError
from switchyard.modkit import StateTables, int_setting

from .engine import TIERS, Candidate, Need, candidates_from, need_for, rank, tier_for, unfit

_CONSUMER = re.compile(r"(main|(subagent|function|agent):[A-Za-z0-9._-]{1,64})\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}\Z")
_PROVIDER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
KEEP_DECISIONS = 1000
PRUNE_SLACK = 100  # H1 C-14: prune once the log is this many rows over KEEP_DECISIONS, in one statement
_TURNS = 1000
KNOWN_SECONDS = 600.0  # how long remembered candidates may serve the timeout fallback (ADR-0013)
HOT_PATH_WAIT = 1.0  # total state-store wait per routed request; shorter than the bridge deadline (2 s)
_MAX_OWED = 1000


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def _check(pattern: re.Pattern[str], value: Any, what: str) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise SwitchyardError(f"invalid {what} {str(value)[:80]!r}")
    return value


_int_setting = partial(int_setting, "router")


def _unregistered(provider: str, model: str) -> Candidate:
    """A delegated child's model the registry does not know (H1 C-7): treated as paid, so it is gated and
    counted like one. The main session keeps the M6 rule (unknown models are never blocked)."""
    return Candidate(id=f"{provider}/{model}"[:200], model=model, cost_class="paid", state="manual",
                     tags=frozenset(), context=None)  # fmt: skip


class RouterModule(StateTables):
    RESOLVE_TTL_SECONDS = 5.0  # H1 C-14: how long one resources.resolve answer is reused

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.ctx: Any = None
        self.clock = clock
        self.settings: dict[str, Any] = {}
        self._failures: OrderedDict[str, int] = OrderedDict()  # turn id -> failed attempts (bounded)
        self._sent: OrderedDict[str, str] = OrderedDict()  # api request id -> resource sent (bounded)
        self._warned: dict[str, str] = {}  # resource -> day a paid pass-through was last audited
        self._lock = threading.Lock()
        self._seq = 0
        # ADR-0013: memory-only state for ``route_timeout``. ``_fast`` is never held across I/O, so the
        # fallback answers while a slow route still holds ``_lock``.
        self._fast = threading.Lock()
        self._known: dict[tuple[str, str], tuple[float, tuple[Candidate, ...]]] = {}
        self._decisions: int | None = None  # running row count of the decision log (H1 C-14)
        self._resolved: dict[str, tuple[float, list[Any]]] = {}  # consumer -> (time, resources.resolve rows)
        self._cool_mem: dict[str, tuple[float, str]] = {}  # resource or scope -> (until, reason)
        self._owed: list[tuple[str, str]] = []  # (day, resource): paid pass-throughs not yet written
        self._unsettled: list[tuple[str, str, str]] = []  # (provider, consumer, model) sent, cost unknown
        self._halt = False  # hard_stop: block the next turn after a slow route let a paid model through
        self._notes: list[tuple[str, dict[str, str]]] = []  # audit records queued by route_timeout

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
            "explain": {"tokens": int, "tools": bool, "vision": bool, "consumer": str},
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
        ctx.hermes_middleware("llm_request", self.route, fallback=self.route_timeout)
        ctx.hermes_hook("api_request_error", self.on_error)
        ctx.subscribe("meter.exhausted", self.on_exhausted)
        if self.settings["hard_stop"]:
            ctx.hermes_gate(self.gate)
        self.ctx = ctx

    def deactivate(self) -> None:
        self.ctx = None
        with self._fast:
            self._known.clear()
            self._resolved.clear()
            self._halt = False
        self._decisions = None

    def health(self) -> tuple[bool, str]:
        if self.ctx is None:
            return False, "stopped"
        return True, f"routing {self.settings['consumer']} on {', '.join(self.settings['providers'])}"

    # storage helpers ----------------------------------------------------------------------------------

    def _cooling(self) -> dict[str, str]:
        sql = f"SELECT resource, until, reason FROM {self._t('cooldowns')} WHERE until > ?"  # nosec B608
        rows = self._q(sql, (self.clock(),))
        with self._fast:
            self._cool_mem = {r[0]: (float(r[1]), str(r[2])) for r in rows}
        return {r[0]: r[2] for r in rows}

    def _budget(self) -> int:
        rows = self._q(f"SELECT value FROM {self._t('kv')} WHERE key = 'paid_requests_per_day'")  # nosec B608
        return int(rows[0][0]) if rows else 0

    def _spent_today(self) -> int:
        day = _day(self.clock())
        rows = self._q(f"SELECT paid FROM {self._t('spend')} WHERE day = ?", (day,))  # nosec B608
        with self._fast:
            owed = sum(1 for d, _ in self._owed if d == day)
        return (int(rows[0][0]) if rows else 0) + owed

    def _paid_ok(self, consumer: str, tier: str) -> bool:
        if not self.ctx.has("llm.paid"):
            return False
        rule = self._q(f"SELECT min_tier FROM {self._t('rules')} WHERE consumer = ?", (consumer,))  # nosec B608
        if not rule or TIERS.index(tier) < TIERS.index(rule[0][0]):
            return False
        return self._spent_today() < self._budget()

    def _candidates(
        self, provider: str, consumer: str | None = None, strict: bool = False, fresh: bool = False
    ) -> list[Candidate]:
        key = consumer or self.settings["consumer"]
        now = self.clock()
        with self._fast:
            cached = self._resolved.get(key)
        reuse = (
            not (strict or fresh) and cached is not None and 0 <= now - cached[0] < self.RESOLVE_TTL_SECONDS
        )
        if reuse and cached is not None:
            resources = cached[1]  # H1 C-14: one resolve serves every request for a few seconds
        else:
            try:
                resolved = self.ctx.call("resources", "resolve", {"consumer": key})
            except SwitchyardError:
                if strict:
                    raise
                return []  # registry not running: pass requests through unchanged
            resources = list(resolved.get("resources", []))
            with self._fast:
                self._resolved[key] = (now, resources)
        found = candidates_from(resources, provider)  # grants are applied on every call, never cached
        if not self.ctx.has("llm.free"):  # free and self-hosted resources need the llm.free grant
            found = [c for c in found if c.cost_class == "paid"]
        with self._fast:  # remembered for route_timeout (ADR-0013); every resolve replaces it
            self._known[(provider, key)] = (self.clock(), tuple(found))
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
        # H1 C-14: count once, then keep a running estimate; prune in one statement when PRUNE_SLACK over.
        # Other processes may add rows too, so a prune recounts.
        if self._decisions is None:
            self._decisions = int(self._q(f"SELECT count(*) FROM {t}")[0][0])  # nosec B608
        else:
            self._decisions += 1
        if self._decisions > KEEP_DECISIONS + PRUNE_SLACK:
            count = int(self._q(f"SELECT count(*) FROM {t}")[0][0])  # nosec B608
            if count > KEEP_DECISIONS:
                self._q(
                    f"DELETE FROM {t} WHERE id IN (SELECT id FROM {t} ORDER BY id LIMIT ?)",  # nosec B608
                    (count - KEEP_DECISIONS,),
                )
            self._decisions = min(count, KEEP_DECISIONS)

    def _write_spend(self, day: str) -> None:
        spend = self._t("spend")
        sql = (f"INSERT INTO {spend} VALUES (?, 1) "  # nosec B608
               "ON CONFLICT(day) DO UPDATE SET paid = paid + 1")  # fmt: skip
        self._q(sql, (day,))

    def _charge_paid(self, need: Need, chosen: Candidate) -> None:
        self._write_spend(_day(self.clock()))
        self.ctx.audit(
            "paid_decision", consumer=self.settings["consumer"], tier=need.tier, resource=chosen.id
        )

    def _settle(self) -> None:
        """Write what ``route_timeout`` left behind (ADR-0013), under ``_lock``: its audit records, owed paid
        pass-throughs, and configured models sent while nothing was known about them (charged now if the
        registry says paid). Runs before every routing decision, so the budget always includes them. What
        cannot be written now stays queued (bounded) for the next call."""
        with self._fast:
            notes, self._notes = self._notes, []
            owed, self._owed = self._owed, []
            unsettled, self._unsettled = self._unsettled, []
        try:
            # registry or store unavailable: retried on the next call; the budget still counts ``_owed``
            with contextlib.suppress(SwitchyardError):
                while notes:
                    self.ctx.audit(notes[0][0], **notes[0][1])
                    notes.pop(0)
                while unsettled:
                    provider, consumer, model = unsettled[0]
                    found = self._candidates(provider, consumer, strict=True)
                    current = next((c for c in found if c.model == model), None)
                    if current is not None and current.cost_class == "paid":
                        owed.append((_day(self.clock()), current.id))
                        self.ctx.audit("timeout_charged", consumer=consumer, resource=current.id[:200])
                    unsettled.pop(0)
                while owed:
                    self._write_spend(owed[0][0])
                    owed.pop(0)
        finally:
            with self._fast:
                self._notes = (notes + self._notes)[-_MAX_OWED:]
                self._owed = (owed + self._owed)[-_MAX_OWED:]
                self._unsettled = (unsettled + self._unsettled)[-_MAX_OWED:]

    # Hermes callbacks ---------------------------------------------------------------------------------

    def choose(
        self, need: Need, provider: str, consumer: str | None = None, free_only: bool = False
    ) -> tuple[Candidate | None, str, dict[str, str]]:
        consumer = consumer or self.settings["consumer"]
        candidates = self._candidates(provider, consumer)
        cooling = self._effective_cooling(provider, candidates)
        paid_ok = not free_only and self._paid_ok(consumer, need.tier)
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
        # ADR-0007 (M7 review): a subagent routed by a worker role is routed within that role's consumer, with
        # the same paid rules, budget charge, quotas and failover as the main session.
        consumer = str(context.get("delegated_consumer") or "") or None
        free_only = bool(context.get("delegated_free_only"))
        claim = context.get("claim")
        with self._lock:  # choice and paid-budget charge are one step (concurrent Hermes requests)
            try:
                with self.ctx.state.deadline(HOT_PATH_WAIT) as limit:  # ADR-0013: below the bridge deadline
                    self._settle()
                    chosen, need, reason = self._decide(
                        request, str(provider), str(context.get("turn_id") or ""), consumer, free_only
                    )
                    paying = chosen if chosen is not None and chosen.cost_class == "paid" else None
                    if chosen is None:
                        # The configured model goes out unchanged. If it is a known paid resource, count it:
                        # the budget shows real paid use even when nothing free could take it (R1 review).
                        current = next((c for c in self._candidates(str(provider), consumer)
                                        if c.model == request.get("model")), None)  # fmt: skip
                        if current is None and consumer:  # H1 C-7: unregistered persona model, counted
                            current = _unregistered(str(provider), str(request.get("model") or ""))
                        if current is not None and current.cost_class == "paid":
                            paying = current
                    # ADR-0013: commit only while the bridge still waits for this answer. Too late, the
                    # request already went out as route_timeout decided: never charge or record this choice.
                    claimed = claim() if callable(claim) else True
                    on_time = claimed and not limit.expired()
                    if on_time and paying is not None:
                        self._charge_paid(need, paying)
            except SwitchyardError:
                if callable(claim) and not claim():
                    self._settle()  # the bridge gave up already: settle what route_timeout left behind
                raise
            if not on_time:
                if claimed:  # the bridge still waits: fail now, so it uses route_timeout at once
                    raise SwitchyardError("route exceeded its state wait budget")
                self._settle()  # off the hot path now: write what route_timeout left behind
                return None
        if chosen is None:
            return None
        self._remember_sent(str(context.get("api_request_id") or ""), chosen.id)
        if chosen.model == request.get("model"):
            return None
        self.ctx.log("router", "route", tier=need.tier, chosen=chosen.id, reason=reason)
        return {**request, "model": chosen.model}

    def _remember_sent(self, request_id: str, resource: str) -> None:
        with self._fast:
            self._sent[request_id] = resource
            while len(self._sent) > _TURNS:
                self._sent.popitem(last=False)

    def route_timeout(self, request: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
        """Bridge fallback when ``route`` missed its deadline or failed (ADR-0013). Memory only: no state
        store, no audit write (both may be what is slow); its records are written by the next ``_settle``.

        1. The configured model is a known paid resource and a free candidate is remembered for this
           consumer: send that (``timeout_fallback``).
        2. Otherwise the configured model goes out. A known paid one is charged as paid pass-through
           (``timeout_passthrough``); with ``hard_stop`` the next turn is also blocked. A model the router
           knew nothing about is settled by the next route: charged then if the registry says paid.
        """
        provider = context.get("provider")
        if self.ctx is None or provider not in self.settings["providers"]:
            return None
        provider = str(provider)
        consumer = str(context.get("delegated_consumer") or "") or self.settings["consumer"]
        model = str(request.get("model") or "")
        now = self.clock()
        with self._fast:
            entry = self._known.get((provider, consumer))
            known = entry[1] if entry is not None and now - entry[0] <= KNOWN_SECONDS else None
            cooling = {k for k, (until, _) in self._cool_mem.items() if until > now}
        current = next((c for c in known or () if c.model == model), None)
        if current is None and known is not None and context.get("delegated_consumer"):
            current = _unregistered(provider, model)  # H1 C-7, same rule on the timeout path
        if known is None or current is None or current.cost_class != "paid":
            # Nothing known: settled by the next route. Free, self-hosted or unregistered: nothing to charge
            # (unregistered models are never blocked, M6 review).
            with self._fast:
                if known is None:
                    self._unsettled = [*self._unsettled, (provider, consumer, model)][-_MAX_OWED:]
            unknown = known is None
            self._note("timeout_passthrough", consumer=consumer, resource=f"{provider}/{model}"[:200],
                       known="no" if unknown else "yes", charged="later" if unknown else "no")  # fmt: skip
            return None
        usable: list[Candidate] = []
        if "all" not in cooling and f"provider:{provider}" not in cooling:
            usable = [
                c for c in known if c.cost_class != "paid" and c.state == "auto" and c.id not in cooling
            ]
        need = need_for(request)
        fit = [c for c in usable if unfit(c, need, cooling={}, paid_ok=False) is None]
        if fit or usable:
            fallback = (fit or usable)[0]
            self._remember_sent(str(context.get("api_request_id") or ""), fallback.id)
            self._note("timeout_fallback", consumer=consumer, configured=current.id[:200],
                       resource=fallback.id[:200])  # fmt: skip
            return {**request, "model": fallback.model}
        halt = bool(self.settings["hard_stop"])
        with self._fast:
            self._owed = [*self._owed, (_day(now), current.id)][-_MAX_OWED:]
            self._halt = self._halt or halt
        self._note("timeout_passthrough", consumer=consumer, resource=current.id[:200], known="yes",
                   charged="yes", hard_stop="next turn" if halt else "off")  # fmt: skip
        return None

    def _note(self, event: str, **detail: str) -> None:
        """Queue an audit record for ``_settle`` (route_timeout must not wait on the audit log)."""
        with self._fast:
            self._notes = [*self._notes, (event, detail)][-_MAX_OWED:]

    def _decide(
        self,
        request: dict[str, Any],
        provider: str,
        turn: str,
        consumer: str | None = None,
        free_only: bool = False,
    ) -> tuple[Candidate | None, Need, str]:
        need = need_for(request)
        exhausted = self._failures.get(turn, 0) >= self.settings["max_attempts"]
        if exhausted:
            chosen, reason = None, "attempts exhausted"
        else:
            chosen, reason, _ = self.choose(need, provider, consumer, free_only)
        if chosen is None:
            # After repeated failures stay free-first (R1 review): a paid configured model that is allowed
            # must not take over while a free resource is still available.
            chosen, reason = self._guard_paid_default(
                request, need, provider, reason, consumer, free_only or exhausted
            )
        self._record(need, chosen, reason)
        return chosen, need, reason

    def _guard_paid_default(
        self,
        request: dict[str, Any],
        need: Need,
        provider: str,
        reason: str,
        consumer: str | None = None,
        free_only: bool = False,
    ) -> tuple[Candidate | None, str]:
        """Nothing fits, so Hermes's configured model would go out unchanged. If that model is a paid resource
        while paid is not allowed, or its quota scope is exhausted, use any free or self-hosted ``auto``
        resource that is not cooling down instead (size and tag checks ignored). Middleware cannot refuse a
        request, so if there is no such resource the configured model is passed through and that is audited
        once per resource and day (``paid_passthrough`` / ``quota_passthrough``)."""
        fallback, why, rid = self._guard_eval(
            str(request.get("model") or ""), need, provider, consumer, free_only
        )
        if not why:
            return None, reason
        if fallback is not None:
            return fallback, f"{reason}; {why}"
        quota_hit = why == "quota exhausted"
        event = "quota_passthrough" if quota_hit else "paid_passthrough"
        day = _day(self.clock())
        if self._warned.get(f"{event}:{rid}") != day:
            self._warned[f"{event}:{rid}"] = day
            self.ctx.audit(event, consumer=consumer or self.settings["consumer"], resource=rid[:200])
        return None, f"{reason}; {why}, passed through"

    def _guard_eval(
        self, model: str, need: Need, provider: str, consumer: str | None = None, free_only: bool = False
    ) -> tuple[Candidate | None, str, str]:
        """(fallback, why, resource id) for the configured ``model``: ``why`` is empty when it may go out."""
        candidates = self._candidates(provider, consumer)
        if consumer and not any(c.model == model for c in candidates):
            # a delegated child's model may be outside its role's pool (a persona's own model): judge it, and
            # find a free fallback, with the main registry view too, so a paid model is still recognised
            seen = {c.id for c in candidates}
            candidates = [*candidates, *(c for c in self._candidates(provider) if c.id not in seen)]
        cooling = self._effective_cooling(provider, candidates)
        current = next((c for c in candidates if c.model == model), None)
        if current is None and consumer:
            current = _unregistered(
                provider, model
            )  # H1 C-7: a delegated child's unknown model counts as paid
        rid = current.id if current else f"{provider}/{model}"
        raw = self._cooling()
        quota_hit = any(k in raw and raw[k].startswith("quota") for k in ("all", f"provider:{provider}", rid))
        paid_blocked = (
            current is not None
            and current.cost_class == "paid"
            and (free_only or not self._paid_ok(consumer or self.settings["consumer"], need.tier))
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
        if self.ctx is None:
            return None
        with self._fast:
            halt, self._halt = self._halt, False
        if halt:  # ADR-0013: a slow route let a paid model through without a free fallback
            self.ctx.audit("hard_stop", consumer=self.settings["consumer"], reason="route timeout")
            return "route_timeout"
        model = str(meta.get("model") or "")
        need = Need(tokens=1, tools=False, vision=False, tier="T1")
        # Hermes's pre_llm_call carries no provider: find the routed provider whose registry knows the
        # configured model. Block only with positive knowledge (M6 review): the registry answers, the model is
        # a known resource, nothing routable is left, and the model itself is ruled out.
        for provider in self.settings["providers"]:
            # a block needs current knowledge: a stopped registry must mean no block (H1 C-14 keeps this)
            candidates = self._candidates(provider, fresh=True)
            if not any(c.model == model for c in candidates):
                # Unknown model: never blocked. It may be a free local model, and blocking needs positive
                # knowledge (M6 review; the R1 change that blocked it was reverted in the follow-up review).
                continue
            chosen, _, _ = self.choose(need, provider)
            if chosen is not None:
                return None
            fallback, why, rid = self._guard_eval(model, need, provider)
            if not why or fallback is not None:
                return None
            self.ctx.audit("hard_stop", consumer=self.settings["consumer"], resource=rid[:200], reason=why)
            return "quota_exhausted" if why == "quota exhausted" else "paid_model_not_allowed"
        return None

    def _sent_model(self, kwargs: dict[str, Any]) -> str | None:
        """The resource a failed request actually used: what ``route`` sent for this request id, else the
        model in Hermes's sanitized payload ``{"method", "body": {...}}``, else the configured model."""
        with self._fast:
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
        if not turn:  # requests without a turn id would share one bucket that never resets (R1 follow-up)
            return
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
        # H1 C-4: an error cooldown never shortens a longer one, and never replaces an active quota reason
        sql = (f"INSERT INTO {self._t('cooldowns')} VALUES (?, ?, ?) "  # nosec B608
               "ON CONFLICT(resource) DO UPDATE SET reason = CASE WHEN until >= excluded.until "
               "THEN reason ELSE excluded.reason END, until = MAX(until, excluded.until)")  # fmt: skip
        self._q(sql, (rid, self.clock() + seconds, reason))
        self._cool_note(rid, self.clock() + seconds, reason)
        self.ctx.log("router", "cooldown", resource=rid, reason=reason, seconds=seconds)

    def _cool_note(self, key: str, until: float, reason: str) -> None:
        with self._fast:
            old = self._cool_mem.get(key)
            if old is None or old[0] < until:
                self._cool_mem[key] = (until, reason)

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
        reason = f"quota {str(data.get('quota'))[:64]} exhausted"
        # H1 C-4: the quota reason wins; the cooldown keeps the later of the two ends
        sql = (f"INSERT INTO {self._t('cooldowns')} VALUES (?, ?, ?) "  # nosec B608
               "ON CONFLICT(resource) DO UPDATE SET reason = excluded.reason, "
               "until = MAX(until, excluded.until)")  # fmt: skip
        self._q(sql, (scope[:200], until, reason))
        self._cool_note(scope[:200], until, reason)
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

    def explain(
        self, tokens: int = 1000, tools: bool = False, vision: bool = False, consumer: str = ""
    ) -> dict[str, Any]:
        """Read-only: what the router would choose now. ``consumer`` (default: the configured one) lets the
        workers module ask for a role's own pool (ADR-0007)."""
        if not 1 <= tokens <= 10_000_000:
            raise SwitchyardError("tokens must be from 1 to 10000000")
        if consumer:
            _check(_CONSUMER, consumer, "consumer")
        consumer = consumer or self.settings["consumer"]
        need = Need(tokens=tokens, tools=tools, vision=vision, tier=tier_for(tokens))
        out = []
        for provider in self.settings["providers"]:
            chosen, reason, skipped = self.choose(need, provider, consumer)
            out.append(
                {
                    "provider": provider,
                    "chosen": chosen.id if chosen else None,
                    "model": chosen.model if chosen else None,
                    "cost_class": chosen.cost_class if chosen else None,
                    "reason": reason,
                    "skipped": skipped,
                }
            )
        return {
            "consumer": consumer,
            "tier": need.tier,
            "paid_allowed": self._paid_ok(consumer, need.tier),
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
        with self._fast:
            self._cool_mem.pop(id, None)
        return {"cleared": id}
