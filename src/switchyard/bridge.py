"""Hermes hook bridge (ADR-0004). Hermes-agnostic: the adapter forwards Hermes hooks and middleware here.

Modules register through ``ctx.hermes_hook`` / ``ctx.hermes_middleware``; registrations are removed when
the module's context closes. Observer hooks get metadata only (no message text); middleware gets a deep copy;
every callback runs on a worker thread
bounded by ``timeout`` (the turn continues without it), and exceptions are caught and audited (class name
only). An ``llm_request`` middleware can only change the request's ``model``: nothing else is adopted.
"""

from __future__ import annotations

import concurrent.futures
import copy
import threading
from collections.abc import Callable, Mapping
from typing import Any

from switchyard.capabilities import CORE_ACTOR, AuditSink

OBSERVER_HOOKS = frozenset(
    {
        "pre_llm_call",
        "pre_api_request",
        "post_api_request",
        "api_request_error",
        "post_llm_call",
        "subagent_stop",
    }
)
_TEXT_KEYS = frozenset(
    {"user_message", "assistant_response", "child_summary", "system_prompt", "final_response"}
)
_MAX_STR = 300


def metadata_only(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce an observer hook payload to metadata (ADR-0004 decision 6): scalar fields, the numeric ``usage``
    buckets, and the model names inside ``request``/``response``/``error``. Message text, conversation
    history, tool traces and raw SDK objects are dropped."""
    out: dict[str, Any] = {}
    for key, value in kwargs.items():
        if not isinstance(key, str) or key in _TEXT_KEYS:
            continue
        if value is None or isinstance(value, bool | int | float):
            out[key] = value
        elif isinstance(value, str):
            out[key] = value[:_MAX_STR]
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
    return out


MIDDLEWARE_KINDS = frozenset({"llm_request"})


class HermesBridge:
    def __init__(self, audit: AuditSink, timeout: float = 2.0) -> None:
        self._audit = audit
        self._hooks: dict[str, list[tuple[str, Callable[..., Any]]]] = {}
        self._middleware: dict[str, list[tuple[str, Callable[..., Any]]]] = {}
        self._lock = threading.Lock()
        self.timeout = timeout
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="switchyard-hook"
        )

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # registration -------------------------------------------------------------------------------------

    def add_hook(self, module_id: str, name: str, fn: Callable[..., Any]) -> None:
        with self._lock:
            self._hooks.setdefault(name, []).append((module_id, fn))

    def add_middleware(self, module_id: str, kind: str, fn: Callable[..., Any]) -> None:
        with self._lock:
            self._middleware.setdefault(kind, []).append((module_id, fn))

    def remove_all(self, module_id: str) -> None:
        with self._lock:
            for table in (self._hooks, self._middleware):
                for key in list(table):
                    table[key] = [(m, f) for m, f in table[key] if m != module_id]

    def registered(self, module_id: str) -> list[str]:
        with self._lock:
            hooks = [n for n, entries in self._hooks.items() if any(m == module_id for m, _ in entries)]
            mids = [
                f"middleware:{k}"
                for k, entries in self._middleware.items()
                if any(m == module_id for m, _ in entries)
            ]
        return sorted(hooks + mids)

    # dispatch -----------------------------------------------------------------------------------------

    def _failed(self, module_id: str, what: str, exc: BaseException) -> None:
        self._audit.append(
            actor=CORE_ACTOR,
            action="module.hook_failed",
            module=module_id,
            detail={"hook": what, "error": type(exc).__name__},
        )

    def _run(self, module_id: str, what: str, fn: Callable[..., Any], *args: Any) -> tuple[bool, Any]:
        """Call ``fn`` on a worker thread, waiting at most ``timeout`` seconds. Returns ``(ok, result)``."""
        try:
            future = self._pool.submit(fn, *args)
            return True, future.result(timeout=self.timeout)
        except concurrent.futures.TimeoutError:
            self._audit.append(
                actor=CORE_ACTOR,
                action="module.hook_timeout",
                module=module_id,
                detail={"hook": what, "seconds": str(self.timeout)},
            )
        except Exception as exc:  # a module must never break a Hermes turn
            self._failed(module_id, what, exc)
        return False, None

    def dispatch_hook(self, name: str, kwargs: Mapping[str, Any]) -> None:
        with self._lock:
            entries = list(self._hooks.get(name, ()))
        for module_id, fn in entries:
            self._run(module_id, name, fn, metadata_only(kwargs))

    def dispatch_llm_request(
        self, request: Mapping[str, Any], context: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """Run ``llm_request`` middleware in registration order. Returns the new request, or ``None`` if no
        module changed it. Modules get deep copies; only the ``model`` they return is ever adopted, and a
        result whose other fields differ from the input is rejected and audited."""
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
        except Exception:
            return None  # not copyable: never hand a module the live request
        for module_id, fn in entries:
            try:
                given = copy.deepcopy(snapshot)
            except Exception:  # pragma: no cover - snapshot was copyable a moment ago
                return None
            given["model"] = model
            ok, result = self._run(module_id, "middleware:llm_request", fn, given, dict(ctx))
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
        if model == request.get("model"):
            return None
        return {**request, "model": model}

    @staticmethod
    def _model_only(before: Mapping[str, Any], after: Any) -> bool:
        if not isinstance(after, dict) or set(after) != set(before):
            return False
        model = after.get("model")
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            return False
        return all(_same(after[k], before[k]) for k in before if k != "model")


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
