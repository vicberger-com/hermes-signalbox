"""Operator reports (M9): health, usage, security, changes. Built from read-only core operations and
read-only module actions; every report is redacted and contains names, counts and times, never secret values.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

KINDS = ("health", "usage", "security", "changes")
_CHANGE_ACTIONS = (
    "policy.granted",
    "policy.revoked",
    "policy.grants_removed",
    "module.activated",
    "module.deactivated",
    "module.removed",
    "module.reloaded",
    "module.mode_changed",
    "module.installed",
    "module.updated",
    "hermes.config",
)


def build(run: Callable[[str, str, dict[str, Any]], Any], kind: str) -> dict[str, Any]:
    """``run(noun, verb, params)`` runs a core operation as the caller."""
    if kind == "health":
        modules = run("module", "list", {})
        return {
            "kind": kind,
            "modules": modules,
            "failed": [m["id"] for m in modules if m.get("status") == "failed"],
        }
    if kind == "usage":
        out: dict[str, Any] = {"kind": kind}
        for module, action in (
            ("meter", "summary"),
            ("router", "status"),
            ("trimmer", "report"),
            ("workers", "report"),
        ):
            try:
                out[module] = run("module", "action", {"id": module, "action": action, "args": {}})
            except Exception as exc:  # module not running: say so, do not fail the report
                out[module] = {"unavailable": type(exc).__name__}
        return out
    if kind == "security":
        tail = run("audit", "tail", {"n": 500})
        words = ("denied", "refused", "rejected")
        denied = [r for r in tail if any(w in str(r.get("action", "")) for w in words)]
        return {"kind": kind, "audit": run("audit", "verify", {}), "recent_denials": denied[-50:]}
    if kind == "changes":
        tail = run("audit", "tail", {"n": 500})
        return {
            "kind": kind,
            "changes": [r for r in tail if str(r.get("action", "")).startswith(_CHANGE_ACTIONS)][-100:],
        }
    raise ValueError(f"report kind must be one of {list(KINDS)}")
