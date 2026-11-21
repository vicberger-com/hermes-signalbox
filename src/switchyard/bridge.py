"""Hermes hook bridge (ADR-0004). Hermes-agnostic: the adapter forwards Hermes hooks and middleware here.

Modules register through ``ctx.hermes_hook`` / ``ctx.hermes_middleware``; registrations are removed when
the module's context closes. Observer hooks get metadata only (no message text); middleware gets a deep copy;
every callback runs on a worker thread
bounded by ``timeout`` (the turn continues without it), and exceptions are caught and audited (class name
only). An ``llm_request`` middleware can only change the request's ``model``: nothing else is adopted.

ADR-0013: an ``llm_request`` middleware may register a ``fallback``, called when the middleware misses the
deadline or fails, and gets a ``claim`` callable in its context. A late result may commit side effects
(charges, records) only if ``claim()`` returns True, which it does only while the bridge still waits.
"""

from __future__ import annotations

import collections
import concurrent.futures
import contextlib
import copy
import hashlib
import re
import threading
import time
import urllib.parse
from collections.abc import Callable, Mapping
from typing import Any

from switchyard.capabilities import CORE_ACTOR, AuditSink
from switchyard.errors import SwitchyardError

OBSERVER_HOOKS = frozenset(
    {
        "pre_llm_call",
        "pre_api_request",
        "post_api_request",
        "api_request_error",
        "post_llm_call",
        "subagent_start",
        "subagent_stop",
    }
)
# Allowlist of metadata keys forwarded to observer modules (ADR-0004 decision 6). Anything else, including
# keys Hermes adds later, is dropped: message text, tokens (``side_question_token``), sender ids, prompts.
_SCALAR_KEYS = frozenset(
    {
        "task_id",
        "turn_id",
        "api_request_id",
        "session_id",
        "parent_session_id",
        "parent_turn_id",
        "child_session_id",
        "platform",
        "model",
        "provider",
        "api_mode",
        "api_call_count",
        "retry_count",
        "max_retries",
        "retryable",
        "status_code",
        "reason",
        "finish_reason",
        "response_model",
        "upstream_provider",
        "api_duration",
        "started_at",
        "ended_at",
        "first_chunk_at",
        "message_count",
        "tool_count",
        "approx_input_tokens",
        "request_char_count",
        "max_tokens",
        "context_length",
        "assistant_content_chars",
        "is_first_turn",
        "child_role",
        "child_status",
        "child_subagent_id",
        "returncode",
        "env_type",
        "tool_name",
        "status",
        "parent_subagent_id",
        "duration_ms",
    }
)
_MAX_STR = 300
_ROLE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_ROUTE_VALUE = re.compile(r"[A-Za-z0-9._:/@+-]{1,200}\Z")
_PROFILE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_DELEGATED_CONSUMER = re.compile(r"subagent:[a-z][a-z0-9_-]{0,31}\Z")
_GATE_CODE = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")


def _host_only(url: str) -> str:
    """``scheme://host[:port]`` of a URL: no user info, path, query or fragment (they can carry keys)."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}"[:_MAX_STR] if parts.scheme and host else ""


def goal_sha(goal: object) -> str:
    """A short digest of a delegated task's goal (ADR-0007): links a route decision to the subagent it became
    and spots repeated delegation, without any module seeing the goal text."""
    if not isinstance(goal, str):
        return ""
    folded = " ".join(re.sub(r"[^\w\s]", " ", goal.casefold()).split())
    return hashlib.sha256(folded.encode("utf-8")).hexdigest()[:16]


def _valid_route(answer: Mapping[str, Any], label: str) -> dict[str, str] | None:
    """The route Hermes gets: ``{model, provider}`` or ``{profile}`` plus our label; extra keys a module
    may add for Switchyard (``consumer``, ``free_only``) are never forwarded."""
    keys = set(answer) - {"consumer", "free_only"}
    profile, model, provider = answer.get("profile"), answer.get("model"), answer.get("provider")
    if keys == {"profile"} and isinstance(profile, str) and _PROFILE.match(profile):
        return {"profile": profile, "label": label}
    if (
        keys == {"model", "provider"}
        and isinstance(model, str)
        and isinstance(provider, str)
        and _ROUTE_VALUE.match(model)
        and _ROUTE_VALUE.match(provider)
    ):
        return {"model": model, "provider": provider, "label": label}
    return None


def metadata_only(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce an observer hook payload to metadata (ADR-0004 decision 6): allow-listed scalar fields, the
    numeric ``usage`` buckets, ``base_url`` as scheme and host, and model names inside
    ``request``/``response``/``error``. Everything else is dropped."""
    out: dict[str, Any] = {}
    for key in _SCALAR_KEYS & set(kwargs):
        value = kwargs[key]
        if value is None or isinstance(value, bool | int | float):
            out[key] = value
        elif isinstance(value, str):
            out[key] = value[:_MAX_STR]
    base_url = kwargs.get("base_url")
    if isinstance(base_url, str):
        with contextlib.suppress(ValueError):  # unparseable URL: leave it out
            out["base_url"] = _host_only(base_url)
    usage = kwargs.get("usage")
    if isinstance(usage, Mapping):
        out["usage"] = {k: v for k, v in usage.items() if isinstance(k, str) and isinstance(v, int | float)}
    request = kwargs.get("request")
    body = request.get("body") if isinstance(request, Mapping) else None
    if isinstance(body, Mapping) and isinstance(body.get("model"), str):
        out["request"] = {"body": {"model": body["model"][:_MAX_STR]}}
    response = kwargs.get("response")
    if isinstance(response, Mapping):
        out["response"] = {
            k: str(response[k])[:_MAX_STR]
            for k in ("model", "upstream_provider", "finish_reason")
            if isinstance(response.get(k), str)
        }
    error = kwargs.get("error")
    if isinstance(error, Mapping) and isinstance(error.get("type"), str):
        out["error"] = {"type": error["type"][:_MAX_STR]}
    if "child_goal" in kwargs:
        out["goal_sha"] = goal_sha(kwargs.get("child_goal"))
    return out


MIDDLEWARE_KINDS = frozenset({"llm_request"})


MAX_INFLIGHT = 4  # calls per module pool still running; more are skipped, not queued (H1 C-2)
BREAKER_TIMEOUTS = 3  # timeouts in a row that pause a module's bridge calls (H1 C-2)
BREAKER_PAUSE_S = 60.0
TRANSFORM_SCAN_BUDGET_S = 0.5  # core-side normalise and must-keep scan per step (H1 C-3)
_SENT_HOOKS = frozenset({"post_api_request", "api_request_error"})


class HermesBridge:
    def __init__(self, audit: AuditSink, timeout: float = 2.0) -> None:
        self._audit = audit
        self._hooks: dict[str, list[tuple[str, Callable[..., Any]]]] = {}
        self._middleware: dict[str, list[tuple[str, Callable[..., Any]]]] = {}
        self._lock = threading.Lock()
        self.timeout = timeout
        self._pools: dict[str, concurrent.futures.ThreadPoolExecutor] = {}
        self._closed = False
        self._fallbacks: dict[tuple[str, str], Callable[..., Any]] = {}
        self._delegation: tuple[str, Callable[..., Any], Callable[[], Any]] | None = None
        self._failures: dict[str, int] = {}
        self._paused: dict[str, float] = {}
        self._inflight: dict[str, int] = {}
        self._timeouts: dict[str, int] = {}
        self._hooks_paused: dict[str, float] = {}
        # api request id -> the model the request went out with (H1 C-5), handed to post_api_request observers
        self._sent_models: collections.OrderedDict[str, str] = collections.OrderedDict()
        # goal digest -> list of pending (consumer, free_only) routes; child session -> (consumer, free_only)
        self._routed_goals: collections.OrderedDict[str, list[tuple[str, bool]]] = collections.OrderedDict()
        self._delegated: collections.OrderedDict[str, tuple[str, bool]] = collections.OrderedDict()

    def _pool(self, module_id: str) -> concurrent.futures.ThreadPoolExecutor:
        """One small pool per module, so a module whose calls hang only starves itself (M6 review)."""
        with self._lock:
            if self._closed:
                raise RuntimeError("bridge closed")
            pool = self._pools.get(module_id)
            if pool is None:
                pool = concurrent.futures.ThreadPoolExecutor(
                    max_workers=2, thread_name_prefix=f"sy-{module_id}"
                )
                self._pools[module_id] = pool
            return pool

    def close(self) -> None:
        with self._lock:
            self._closed = True
            pools, self._pools = list(self._pools.values()), {}
        for pool in pools:
            pool.shutdown(wait=False, cancel_futures=True)

    # registration -------------------------------------------------------------------------------------

    def add_hook(self, module_id: str, name: str, fn: Callable[..., Any]) -> None:
        with self._lock:
            self._hooks.setdefault(name, []).append((module_id, fn))

    def add_middleware(
        self, module_id: str, kind: str, fn: Callable[..., Any], fallback: Callable[..., Any] | None = None
    ) -> None:
        with self._lock:
            self._middleware.setdefault(kind, []).append((module_id, fn))
            if fallback is not None:
                self._fallbacks[(module_id, kind)] = fallback

    def add_gate(self, module_id: str, fn: Callable[..., Any]) -> None:
        with self._lock:
            self._middleware.setdefault("gate:pre_llm_call", []).append((module_id, fn))

    def set_delegation(self, module_id: str, route: Callable[..., Any], roles: Callable[[], Any]) -> None:
        """One module at a time routes Hermes delegation (ADR-0007)."""
        with self._lock:
            holder = self._delegation[0] if self._delegation else None
            if holder is not None and holder != module_id:
                raise SwitchyardError(f"delegation routing is already provided by {holder!r}")
            self._delegation = (module_id, route, roles)

    def delegation_active(self) -> bool:
        with self._lock:
            return self._delegation is not None

    def remove_all(self, module_id: str) -> None:
        with self._lock:
            if self._delegation and self._delegation[0] == module_id:
                self._delegation = None
                self._routed_goals.clear()  # pending routes die with their owner (M7 review)
            for table in (self._hooks, self._middleware):
                for key in list(table):
                    table[key] = [(m, f) for m, f in table[key] if m != module_id]
            for owner in [k for k in self._fallbacks if k[0] == module_id]:
                del self._fallbacks[owner]

    def registered(self, module_id: str) -> list[str]:
        with self._lock:
            hooks = [n for n, entries in self._hooks.items() if any(m == module_id for m, _ in entries)]
            mids = [
                k if k.startswith(("gate:", "transform:")) else f"middleware:{k}"
                for k, entries in self._middleware.items()
                if any(m == module_id for m, _ in entries)
            ]
            if self._delegation and self._delegation[0] == module_id:
                mids.append("delegation")
        return sorted(hooks + mids)

    # dispatch -----------------------------------------------------------------------------------------

    def _failed(self, module_id: str, what: str, exc: BaseException) -> None:
        self._audit.append(
            actor=CORE_ACTOR,
            action="module.hook_failed",
            module=module_id,
            detail={"hook": what, "error": type(exc).__name__},
        )

    def inflight(self, module_id: str) -> int:
        """Calls of ``module_id`` still running on its pool (bounded by ``MAX_INFLIGHT``)."""
        with self._lock:
            return self._inflight.get(module_id, 0)

    def _hooks_paused_now(self, module_id: str) -> bool:
        with self._lock:
            return time.monotonic() < self._hooks_paused.get(module_id, 0.0)

    def _submit(
        self,
        module_id: str,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        *,
        pool: str | None,
        breaker: bool,
    ) -> concurrent.futures.Future[Any] | None:
        """Start a call, or ``None`` when the module is paused or its pool is saturated (H1 C-2): a hung
        module costs nothing per call once paused, and never builds an unbounded queue."""
        key = pool or module_id
        if breaker and self._hooks_paused_now(module_id):
            return None
        with self._lock:
            if self._inflight.get(key, 0) >= MAX_INFLIGHT:
                saturated = True
            else:
                saturated = False
                self._inflight[key] = self._inflight.get(key, 0) + 1
        if saturated:
            if breaker:
                self._note_timeout(module_id)
            return None
        try:
            future = self._pool(key).submit(fn, *args)
        except BaseException:
            self._done(key)
            raise
        future.add_done_callback(lambda _f: self._done(key))
        return future

    def _done(self, key: str) -> None:
        with self._lock:
            left = self._inflight.get(key, 0) - 1
            if left > 0:
                self._inflight[key] = left
            else:
                self._inflight.pop(key, None)

    def _note_timeout(self, module_id: str) -> None:
        """``BREAKER_TIMEOUTS`` timeouts in a row pause the module's bridge calls for ``BREAKER_PAUSE_S``
        (audited once per pause)."""
        with self._lock:
            count = self._timeouts.get(module_id, 0) + 1
            self._timeouts[module_id] = count
            if count < BREAKER_TIMEOUTS:
                return
            self._timeouts.pop(module_id, None)
            self._hooks_paused[module_id] = time.monotonic() + BREAKER_PAUSE_S
        self._audit.append(actor=CORE_ACTOR, action="module.hooks_paused", module=module_id,
                           detail={"seconds": str(int(BREAKER_PAUSE_S))})  # fmt: skip

    def _collect(
        self,
        module_id: str,
        what: str,
        future: concurrent.futures.Future[Any] | None,
        timeout: float,
        *,
        claim: _Claim | None = None,
        breaker: bool = True,
    ) -> tuple[bool, Any]:
        """Wait for a started call. With ``claim``: at the deadline the call is abandoned unless it has
        already claimed its result, in which case the bridge waits one more ``timeout`` for it (the module
        is committing)."""
        if future is None:
            return False, None
        try:
            try:
                result = future.result(timeout=max(timeout, 0.0))
            except concurrent.futures.TimeoutError:
                if claim is None or claim.abandon():
                    raise
                result = future.result(timeout=self.timeout)
        except concurrent.futures.TimeoutError:
            self._audit.append(
                actor=CORE_ACTOR,
                action="module.hook_timeout",
                module=module_id,
                detail={"hook": what, "seconds": str(self.timeout)},
            )
            if breaker:
                self._note_timeout(module_id)
            return False, None
        except Exception as exc:  # a module must never break a Hermes turn
            self._failed(module_id, what, exc)
            return False, None
        if breaker:
            with self._lock:
                self._timeouts.pop(module_id, None)
        return True, result

    def _run(
        self,
        module_id: str,
        what: str,
        fn: Callable[..., Any],
        *args: Any,
        claim: _Claim | None = None,
        pool: str | None = None,
        breaker: bool = True,
    ) -> tuple[bool, Any]:
        """Call ``fn`` on a worker thread, waiting at most ``timeout`` seconds. Returns ``(ok, result)``."""
        try:
            future = self._submit(module_id, fn, args, pool=pool, breaker=breaker)
        except Exception as exc:  # bridge closed
            self._failed(module_id, what, exc)
            return False, None
        return self._collect(module_id, what, future, self.timeout, claim=claim, breaker=breaker)

    def delegation_roles(self) -> list[tuple[str, str]]:
        """Worker roles for the ``delegate_task`` schema: sorted, validated names, one-line descriptions."""
        with self._lock:
            entry = self._delegation
        if entry is None:
            return []
        ok, roles = self._run(entry[0], "delegation:roles", entry[2])
        out: dict[str, str] = {}
        if ok and isinstance(roles, list):
            for item in roles[:64]:
                if (
                    isinstance(item, tuple | list)
                    and len(item) == 2
                    and isinstance(item[0], str)
                    and _ROLE.match(item[0])
                    and isinstance(item[1], str)
                ):
                    out[item[0]] = " ".join(item[1].split())[:200]
        return sorted(out.items())

    def dispatch_delegation(self, task: Mapping[str, Any]) -> tuple[dict[str, str] | None, str]:
        """Route one ``delegate_task`` task (ADR-0007). Returns ``(route, "")`` or ``(None, message)``.

        The module sees the role, the goal digest and the task index, never the goal or context text. It
        returns ``{"model", "provider"}``, ``{"profile"}`` or ``{"refuse": code}``; anything else, an error or
        a timeout refuses the task (fail closed: the operator chose this backend, so no silent fallback to
        another route). Messages are written here, because Hermes shows them to the model."""
        with self._lock:
            entry = self._delegation
        if entry is None:
            return None, "[switchyard] No Switchyard module routes delegation right now. Ask the operator."
        module_id, route_fn, _ = entry
        role = task.get("worker_role")
        meta: dict[str, Any] = {
            "worker_role": role if isinstance(role, str) and _ROLE.match(role) else "",
            "goal_sha": goal_sha(task.get("goal")),
            "index": task.get("index") if isinstance(task.get("index"), int) else 0,
        }
        ok, answer = self._run(module_id, "delegation:route", route_fn, meta)
        if ok and isinstance(answer, Mapping):
            label = meta["worker_role"] or module_id
            code = answer.get("refuse")
            if isinstance(code, str) and _GATE_CODE.match(code):
                self._audit.append(
                    actor=CORE_ACTOR,
                    action="module.delegation_refused",
                    module=module_id,
                    detail={"role": label, "code": code},
                )
                words = code.replace("_", " ")
                return None, (
                    f"[switchyard] The {module_id} module refused this task ({words}). "
                    "Do not delegate the same task again; do it differently or ask the user."
                )
            route = _valid_route(answer, label)
            if route is not None:
                consumer = answer.get("consumer")
                mark = (
                    consumer if isinstance(consumer, str) and _DELEGATED_CONSUMER.match(consumer) else "",
                    answer.get("free_only") is not False,
                )
                with self._lock:  # consumed by the first matching subagent_start (M7 review)
                    pending = self._routed_goals.setdefault(meta["goal_sha"], [])
                    pending.append(mark)
                    del pending[:-16]
                    self._routed_goals.move_to_end(meta["goal_sha"])
                    while len(self._routed_goals) > 2000:
                        self._routed_goals.popitem(last=False)
                return route, ""
        self._audit.append(
            actor=CORE_ACTOR,
            action="module.delegation_failed",
            module=module_id,
            detail={"role": meta["worker_role"]},
        )
        return (
            None,
            "[switchyard] Delegation routing failed for this task. Ask the operator to check Switchyard.",
        )

    def _track_children(self, name: str, kwargs: Mapping[str, Any]) -> None:
        """ADR-0007: link a started child to the pending route of its goal (consumed once) and forget it when
        it stops, so the marker neither spreads to other children nor ages out while the child runs."""
        child = str(kwargs.get("child_session_id") or "")
        if not child:
            return
        with self._lock:
            if name == "subagent_stop":
                self._delegated.pop(child, None)
                return
            pending = self._routed_goals.get(goal_sha(kwargs.get("child_goal")))
            if pending:
                self._delegated[child] = pending.pop(0)
                while len(self._delegated) > 20_000:  # backstop only: entries leave on subagent_stop
                    self._delegated.popitem(last=False)

    def dispatch_hook(self, name: str, kwargs: Mapping[str, Any]) -> None:
        if name in ("subagent_start", "subagent_stop"):
            self._track_children(name, kwargs)
        with self._lock:
            entries = list(self._hooks.get(name, ()))
            sent = (
                self._sent_models.pop(str(kwargs.get("api_request_id") or ""), None)
                if name in _SENT_HOOKS
                else None
            )
        meta = metadata_only(kwargs)
        if sent is not None:
            meta["sent_model"] = sent  # written by the core, from the request it saw go out (H1 C-5)
        # H1 C-2: observers run side by side against one shared deadline, not one timeout each in a row
        deadline = time.monotonic() + self.timeout
        started = []
        for module_id, fn in entries:
            try:
                started.append(
                    (module_id, self._submit(module_id, fn, (dict(meta),), pool=None, breaker=True))
                )
            except Exception as exc:  # bridge closed
                self._failed(module_id, name, exc)
        for module_id, future in started:
            self._collect(module_id, name, future, deadline - time.monotonic())

    def add_transform(self, module_id: str, kind: str, fn: Callable[..., Any]) -> None:
        with self._lock:
            self._middleware.setdefault(f"transform:{kind}", []).append((module_id, fn))

    def dispatch_transform(self, kind: str, text: object, meta: Mapping[str, Any]) -> str | None:
        """Shorten tool or terminal output (ADR-0008). Each module returns kept line ranges for the current
        text; ``trim.rebuild`` applies them, adds must-keep lines and writes the omission markers. Returns
        the new text, or ``None`` when nothing changed (Hermes keeps the original). Fails open."""
        from switchyard import trim

        with self._lock:
            entries = list(self._middleware.get(f"transform:{kind}", ()))
        if not entries or not isinstance(text, str) or len(text) > trim.MAX_INPUT_CHARS:
            return None
        info = metadata_only(meta)
        try:
            current = trim.normalise(text, deadline=time.monotonic() + TRANSFORM_SCAN_BUDGET_S)
        except trim.BudgetExceeded:
            self._scan_skipped(kind)
            return None
        trimmed = False
        for module_id, fn in entries:
            if self._transform_paused(module_id):
                continue
            lines = current.split("\n")
            ok, ranges = self._run(module_id, f"transform:{kind}", fn, tuple(lines), dict(info))
            self._transform_result(module_id, ok)
            if not ok or ranges is None or not isinstance(ranges, list | tuple):
                continue
            try:
                rebuilt = trim.rebuild(lines, ranges, deadline=time.monotonic() + TRANSFORM_SCAN_BUDGET_S)
            except trim.BudgetExceeded:  # H1 C-3: hostile text must not stall the turn; keep it as it is
                self._scan_skipped(kind)
                return None
            if rebuilt is None:
                continue
            current, trimmed = rebuilt, True
        # normalisation alone is not a reason to change output (M8 review)
        return current if trimmed and current != text else None

    def _scan_skipped(self, kind: str) -> None:
        self._audit.append(actor=CORE_ACTOR, action="core.transform_skipped", module="",
                           detail={"kind": kind, "reason": "scan budget"})  # fmt: skip

    def _transform_paused(self, module_id: str) -> bool:
        with self._lock:
            until = self._paused.get(module_id, 0.0)
        return time.monotonic() < until

    def _transform_result(self, module_id: str, ok: bool) -> None:
        """Three failed or timed-out transform calls in a row pause that module's transforms for five minutes
        (audited), so a hung module costs at most a few timeouts, not one per tool call (M8 review)."""
        with self._lock:
            if ok:
                self._failures.pop(module_id, None)
                return
            count = self._failures.get(module_id, 0) + 1
            self._failures[module_id] = count
            if count < 3:
                return
            self._failures.pop(module_id, None)
            self._paused[module_id] = time.monotonic() + 300.0
        self._audit.append(
            actor=CORE_ACTOR, action="module.transform_paused", module=module_id, detail={"seconds": "300"}
        )

    def dispatch_gate(self, kwargs: Mapping[str, Any]) -> str | None:
        """Run ``pre_llm_call`` gates (ADR-0006) on metadata. A gate returns ``None`` or a reason **code**
        (``[a-z][a-z0-9_]{0,39}``); the first code blocks the turn with a core-written sentence naming the
        module and the code. Hermes stores the block message as the assistant's reply, so module-written
        text never reaches it (M6 review). A gate that fails, times out or returns anything else does not
        block (fail open, audited): a bug must not stop every turn."""
        with self._lock:
            entries = list(self._middleware.get("gate:pre_llm_call", ()))
        for module_id, fn in entries:
            ok, code = self._run(module_id, "gate:pre_llm_call", fn, metadata_only(kwargs))
            if not ok or code is None:
                continue
            if not isinstance(code, str) or not _GATE_CODE.match(code):
                self._audit.append(
                    actor=CORE_ACTOR,
                    action="module.gate_rejected",
                    module=module_id,
                    detail={"turn": str(kwargs.get("turn_id", ""))[:64]},
                )
                continue
            self._audit.append(
                actor=CORE_ACTOR,
                action="module.gate_blocked",
                module=module_id,
                detail={"turn": str(kwargs.get("turn_id", ""))[:64], "code": code},
            )
            words = code.replace("_", " ")
            return (
                f"[switchyard] This request was stopped by the {module_id} module ({words}). "
                "Ask the operator to check Switchyard."
            )
        return None

    def dispatch_llm_request(
        self, request: Mapping[str, Any], context: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """Run ``llm_request`` middleware in registration order. Returns the new request, or ``None`` if no
        module changed it. Modules get deep copies; only the ``model`` they return is ever adopted, and a
        result whose other fields differ from the input is rejected and audited."""
        request_id = str(context.get("api_request_id") or "")
        self._remember_sent(request_id, request.get("model"))
        with self._lock:
            entries = list(self._middleware.get("llm_request", ()))
        if not entries:
            return None
        model = request.get("model")
        try:
            snapshot = copy.deepcopy(dict(request))
            ctx = copy.deepcopy(
                {k: v for k, v in context.items() if k not in {"request", "original_request"}}
            )
            # ADR-0007: a subagent whose model a delegation route chose is marked, so request middleware
            # (the router) leaves that choice alone.
            with self._lock:
                mark = self._delegated.get(str(context.get("session_id") or ""))
            ctx["delegated"] = mark is not None
            if mark is not None:
                ctx["delegated_consumer"], ctx["delegated_free_only"] = mark
        except Exception:
            return None  # not copyable: never hand a module the live request
        for module_id, fn in entries:
            try:
                given = copy.deepcopy(snapshot)
            except Exception:  # pragma: no cover - snapshot was copyable a moment ago
                return None
            given["model"] = model
            claim = _Claim()
            fallback_given = copy.deepcopy(given)
            ok, result = self._run(
                module_id, "middleware:llm_request", fn, given, {**ctx, "claim": claim.claim}, claim=claim
            )
            if not ok:
                claim.abandon()
                with self._lock:
                    fallback = self._fallbacks.get((module_id, "llm_request"))
                if fallback is None:
                    continue
                # ADR-0013: the module's own answer for a missed deadline, on a separate pool so a stuck
                # route cannot starve it. Same rules as the middleware result.
                ok, result = self._run(
                    module_id, "middleware:llm_request:fallback", fallback, fallback_given, dict(ctx),
                    pool=f"{module_id}#fallback", breaker=False,
                )  # fmt: skip
            if not ok or result is None:
                continue
            if not self._model_only(snapshot, result):
                self._audit.append(
                    actor=CORE_ACTOR,
                    action="module.middleware_rejected",
                    module=module_id,
                    detail={"kind": "llm_request"},
                )
                continue
            model = result["model"]
        self._remember_sent(request_id, model)
        if model == request.get("model"):
            return None
        return {**request, "model": model}

    def _remember_sent(self, request_id: str, model: object) -> None:
        if not request_id or not isinstance(model, str):
            return
        with self._lock:
            self._sent_models[request_id] = model[:200]
            self._sent_models.move_to_end(request_id)
            while len(self._sent_models) > 2_000:  # backstop: entries leave on post_api_request
                self._sent_models.popitem(last=False)

    @staticmethod
    def _model_only(before: Mapping[str, Any], after: Any) -> bool:
        if not isinstance(after, dict) or set(after) != set(before):
            return False
        model = after.get("model")
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            return False
        return all(_same(after[k], before[k]) for k in before if k != "model")


class _Claim:
    """One middleware call's commit point (ADR-0013): the module claims before any side effect; the bridge
    abandons at its deadline. Whichever comes first wins."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = 0  # 0 open, 1 claimed by the module, 2 abandoned by the bridge

    def claim(self) -> bool:
        with self._lock:
            if self._state == 0:
                self._state = 1
            return self._state == 1

    def abandon(self) -> bool:
        """True if the call is now abandoned; False if the module claimed first."""
        with self._lock:
            if self._state == 0:
                self._state = 2
            return self._state == 2


def _same(a: Any, b: Any) -> bool:
    """Structural equality that does not trust custom ``__eq__``: same type all the way down."""
    if type(a) is not type(b):
        return False
    if isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in b)
    if isinstance(b, list | tuple):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(b, str | int | float | bool | bytes | type(None)):
        return bool(a == b)
    return a is b
