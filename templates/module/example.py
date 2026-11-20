"""Template module. Copy the directory, rename, and replace the bodies.

The core passes a ``switchyard.context.ModuleContext`` to ``activate``. It exposes only the brokers for
capabilities this module was granted; anything else raises ``CapabilityDenied``. The context is typed here as
a Protocol with the two members the template uses, so the module imports nothing from Switchyard and its unit
tests run on their own. ``tests/test_contract.py`` also runs it through a real core (``switchyard.contract``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ModuleContext(Protocol):
    """Subset of the core context used by this template."""

    def log(self, stream: str, event: str, **fields: Any) -> None: ...

    def register_panel(self, panel_id: str, render: Any) -> None: ...


@dataclass(frozen=True)
class Health:
    """Result of a health check. ``detail`` must never contain secret values."""

    ok: bool
    detail: str = ""


class ExampleModule:
    """Lifecycle: activate -> (health)* -> deactivate. Both ends must be idempotent."""

    def __init__(self) -> None:
        self._ctx: ModuleContext | None = None

    def activate(self, ctx: ModuleContext) -> None:
        if self._ctx is not None:
            return
        self._ctx = ctx
        ctx.register_panel("example.status", self.render_status)
        ctx.log("example", "activated")

    def deactivate(self) -> None:
        if self._ctx is None:
            return
        self._ctx.log("example", "deactivated")
        self._ctx = None

    def health(self) -> Health:
        return Health(ok=self._ctx is not None, detail="active" if self._ctx else "stopped")

    def render_status(self) -> dict[str, Any]:
        """Panel data. Plain data only; the dashboard renders it."""
        return {"title": "Example", "state": self.health().detail}
