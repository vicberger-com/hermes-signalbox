"""The ``notify`` capability (ADR-0009): a module raises an operator notification.

``ctx.notify.send(severity, title, detail="")`` validates and caps the fields, redacts known secret values,
audits ``module.notify`` and publishes the event ``core.notify`` (source ``core``) with the sending module's
id. Delivery is not the sender's business: the bundled ``inbox`` module stores notifications for the
dashboard. Nothing leaves the machine.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from switchyard.capabilities import CORE_ACTOR, AuditSink
from switchyard.errors import SwitchyardError

SEVERITIES = ("info", "low", "medium", "high", "critical")
MAX_TITLE = 120
MAX_DETAIL = 500


def _line(text: object, limit: int) -> str:
    return " ".join(str(text).split())[:limit]


class NotifyBroker:
    def __init__(
        self,
        publish: Callable[[str, str, dict[str, Any]], object],
        audit: AuditSink,
        redact: Callable[[str], str],
    ) -> None:
        self._publish = publish
        self._audit = audit
        self._redact = redact

    def for_module(self, module_id: str) -> ModuleNotify:
        return ModuleNotify(self, module_id)

    def send(self, module_id: str, severity: str, title: str, detail: str = "") -> dict[str, str]:
        if severity not in SEVERITIES:
            raise SwitchyardError(f"severity must be one of {list(SEVERITIES)}")
        if not isinstance(title, str) or not title.strip() or not isinstance(detail, str):
            raise SwitchyardError("title must be non-empty text and detail text")
        # redact before truncating, so a secret cut in half by the cap is still removed (M9 review)
        data = {
            "module": module_id,
            "severity": severity,
            "title": _line(self._redact(title), MAX_TITLE),
            "detail": _line(self._redact(detail), MAX_DETAIL),
        }
        self._audit.append(
            actor=CORE_ACTOR, action="module.notify", module=module_id, detail={"severity": severity}
        )
        self._publish("core", "core.notify", data)
        return data


class ModuleNotify:
    __slots__ = ("_broker", "_module_id")

    def __init__(self, broker: NotifyBroker, module_id: str) -> None:
        self._broker = broker
        self._module_id = module_id

    def send(self, severity: str, title: str, detail: str = "") -> dict[str, str]:
        return self._broker.send(self._module_id, severity, title, detail)
