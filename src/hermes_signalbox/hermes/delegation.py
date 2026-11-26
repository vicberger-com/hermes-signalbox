"""Hermes delegation backend ``signalbox`` (ADR-0007). Active only when the operator sets
``delegation.backend: signalbox`` in Hermes config; it then asks the core bridge for each ``delegate_task``
task's route. Imports Hermes lazily: the core never imports Hermes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from hermes_signalbox.bridge import HermesBridge

NAME = "signalbox"


def make_provider(bridge: HermesBridge, hosting: Callable[[], bool]) -> Any:
    """Build the provider object; raises ``ImportError`` outside Hermes. ``hosting`` is asked on every call:
    a process can start hosting after the plugin loaded (ADR-0014)."""
    from agent.delegation_provider import (  # type: ignore[import-not-found,unused-ignore]
        DelegationProvider,
        DelegationRouteError,
    )

    class SignalboxDelegation(DelegationProvider):  # type: ignore[misc]
        @property
        def name(self) -> str:
            return NAME

        @property
        def summary(self) -> str:
            return "Signalbox worker roles: each role routes to its own model pool or Hermes profile."

        def is_available(self) -> bool:
            # False fails delegation closed in Hermes: no silent fallback to another route.
            return hosting() and bridge.delegation_active()

        def task_parameters(self, config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
            roles = bridge.delegation_roles()
            if not roles:
                return {}
            return {
                "worker_role": {
                    "type": "string",
                    "enum": [name for name, _ in roles],
                    "description": "Signalbox worker role for this task; it decides the model.",
                }
            }

        def description(self, config: Mapping[str, Any]) -> str:
            roles = bridge.delegation_roles()
            if not roles:
                return ""
            lines = [f"- {name}: {text}" if text else f"- {name}" for name, text in roles]
            return "Worker roles (set worker_role per task):\n" + "\n".join(lines)

        def route_task(self, task: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
            route, message = bridge.dispatch_delegation(task)
            if route is None:
                raise DelegationRouteError(message)
            return route

    return SignalboxDelegation()
