"""Hermes hook bridge (ADR-0004). Hermes-agnostic: the adapter forwards Hermes hooks and middleware here.

Modules register through ``ctx.hermes_hook`` / ``ctx.hermes_middleware``; registrations are removed when
the module's context closes. Every callback gets a shallow copy of the arguments, exceptions are caught and
audited (class name only), and an ``llm_request`` middleware may change nothing but the request's ``model``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import Any

from switchyard.capabilities import CORE_ACTOR, AuditSink

OBSERVER_HOOKS = frozenset(
    {"pre_llm_call", "pre_api_request", "post_api_request", "api_request_error", "post_llm_call"}
)
MIDDLEWARE_KINDS = frozenset({"llm_request"})


class HermesBridge:
    def __init__(self, audit: AuditSink) -> None:
        self._audit = audit
        self._hooks: dict[str, list[tuple[str, Callable[..., Any]]]] = {}
        self._middleware: dict[str, list[tuple[str, Callable[..., Any]]]] = {}
        self._lock = threading.Lock()

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
        self._audit.append(actor=CORE_ACTOR, action="module.hook_failed", module=module_id,
                           detail={"hook": what, "error": type(exc).__name__})  # fmt: skip

    def dispatch_hook(self, name: str, kwargs: Mapping[str, Any]) -> None:
        with self._lock:
            entries = list(self._hooks.get(name, ()))
        for module_id, fn in entries:
            try:
                fn(dict(kwargs))
            except Exception as exc:  # a module must never break a Hermes turn
                self._failed(module_id, name, exc)

    def dispatch_llm_request(
        self, request: Mapping[str, Any], context: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """Run ``llm_request`` middleware in registration order. Returns the new request, or ``None`` if no
        module changed it. Each change must differ from its input in ``model`` only."""
        with self._lock:
            entries = list(self._middleware.get("llm_request", ()))
        current = dict(request)
        changed = False
        for module_id, fn in entries:
            try:
                result = fn(dict(current), dict(context))
            except Exception as exc:
                self._failed(module_id, "middleware:llm_request", exc)
                continue
            if result is None:
                continue
            if not self._model_only(current, result):
                self._audit.append(actor=CORE_ACTOR, action="module.middleware_rejected", module=module_id,
                                   detail={"kind": "llm_request"})  # fmt: skip
                continue
            current = dict(result)
            changed = True
        return current if changed else None

    @staticmethod
    def _model_only(before: Mapping[str, Any], after: Any) -> bool:
        if not isinstance(after, dict) or set(after) != set(before):
            return False
        model = after.get("model")
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            return False
        return all(after[k] is before[k] or after[k] == before[k] for k in before if k != "model")
