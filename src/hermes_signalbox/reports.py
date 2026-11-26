"""Operator reports (M9): health, usage, security, changes. Built from read-only core operations and
read-only module actions; every report is redacted and contains names, counts and times, never secret values.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from hermes_signalbox import labels

KINDS = ("health", "usage", "security", "changes")
# H5 WP2 (#207): who reads each report and which question it answers. Shown above the report on every surface.
PURPOSES = {
    "health": "Is everything working, and what needs your attention?",
    "usage": "What did Hermes route and use, and what did it cost?",
    "security": "Has the audit log been tampered with, and what was refused?",
    "changes": "Who changed what, and when?",
}
_USAGE_SOURCES = (("meter", "summary"), ("router", "status"), ("trimmer", "report"), ("workers", "report"))
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
        failed = [m["id"] for m in modules if m.get("status") == "failed"]
        return _finish({"kind": kind, "modules": modules, "failed": failed})
    if kind == "usage":
        out: dict[str, Any] = {"kind": kind}
        modules = run("module", "list", {})
        status = {m["id"]: m.get("status") for m in modules}
        for module, action in _USAGE_SOURCES:
            # H4 R1-F12: say why a section is missing, in words, instead of an exception class name
            if module not in status:
                out[module] = {"unavailable": "not installed"}
            elif status[module] != "active":
                out[module] = {"unavailable": "not active"}
            else:
                try:
                    out[module] = run("module", "action", {"id": module, "action": action, "args": {}})
                except Exception:  # stopped meanwhile, or the action failed: do not fail the report
                    out[module] = {"unavailable": "action failed"}
        return _finish(out, modules)
    if kind == "security":
        tail = run("audit", "tail", {"n": 500})
        words = ("denied", "refused", "rejected")
        denied = [r for r in tail if any(w in str(r.get("action", "")) for w in words)]
        return _finish({"kind": kind, "audit": run("audit", "verify", {}), "recent_denials": denied[-50:]})
    if kind == "changes":
        tail = run("audit", "tail", {"n": 500})
        changes = [r for r in tail if str(r.get("action", "")).startswith(_CHANGE_ACTIONS)][-100:]
        return _finish({"kind": kind, "changes": changes})
    raise ValueError(f"report kind must be one of {list(KINDS)}")


def _finish(payload: dict[str, Any], modules: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload["purpose"] = PURPOSES[payload["kind"]]
    payload["summary"] = summarize(payload, modules=modules)
    return payload


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _and(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def summarize(payload: dict[str, Any], *, modules: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The deterministic summary of a report (H5 WP2, #207): a headline, the counts behind it and the lines
    that need attention. It reads only the report payload (plus the module rows for ``usage``), never a clock,
    so the same input always gives the same text."""
    kind = payload["kind"]
    if kind == "health":
        return _health(payload["modules"])
    if kind == "usage":
        return _usage(payload, {m["id"]: m for m in modules or ()})
    if kind == "security":
        return _security(payload["audit"], payload["recent_denials"])
    if kind == "changes":
        changes = payload["changes"]
        lines = [labels.sentence(r) for r in reversed(changes[-5:])]
        if not changes:
            return {"headline": "No changes in the recent records", "counts": {"changes": 0}, "lines": []}
        headline = f"{_plural(len(changes), 'change')} recorded; latest: {lines[0]}"
        return {"headline": headline, "counts": {"changes": len(changes)}, "lines": lines}
    raise ValueError(f"report kind must be one of {list(KINDS)}")


def _health(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    failed = [m for m in rows if m.get("status") == "failed"]
    running = [m for m in rows if m.get("status") == "active"]
    waiting = [m for m in rows if m.get("status") not in ("failed", "active") and m.get("missing_grants")]
    lines = [f"{m['id']} failed: {m.get('error') or 'no error text recorded'}" for m in failed]
    for m in waiting:
        missing = [str(c) for c in m["missing_grants"]]
        lines.append(f"{m['id']} is waiting for {_plural(len(missing), 'permission')}: {', '.join(missing)}")
    counts = {
        "total": len(rows),
        "running": len(running),
        "failed": len(failed),
        "waiting_for_permissions": len(waiting),
    }
    headline = (
        f"{len(running)} of {len(rows)} modules running · {len(failed)} failed · "
        f"{len(waiting)} waiting for permissions"
    )
    return {"headline": headline, "counts": counts, "lines": lines}


def _usage(payload: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    lines: list[str] = []
    reporting = 0
    for module, _action in _USAGE_SOURCES:
        data = payload.get(module)
        reason = data.get("unavailable") if isinstance(data, dict) else None
        if reason is None:
            reporting += 1
        elif reason == "not installed":
            lines.append(f"{module} isn't installed")
        elif reason == "not active":
            missing = [str(c) for c in by_id.get(module, {}).get("missing_grants") or ()]
            if missing:
                lines.append(f"{module} isn't running: grant {_and(missing)} to collect its data")
            else:
                lines.append(f"{module} isn't running: start it with 'module activate {module}'")
        else:
            lines.append(f"{module} is running but its report failed: run 'module health {module}'")
    counts = {"sources": len(_USAGE_SOURCES), "reporting": reporting}
    headline = f"{reporting} of {len(_USAGE_SOURCES)} usage sources reporting"
    return {"headline": headline, "counts": counts, "lines": lines}


def _security(audit: dict[str, Any], denials: Sequence[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], int] = {}  # repeats of the same refusal are counted, not listed
    for r in denials:
        detail = r.get("detail") or {}
        what = labels.action(str(r.get("action", "")))
        key = (str(r.get("module", "")), what, str(detail.get("capability", "")))
        groups[key] = groups.get(key, 0) + 1
    lines = []
    for (module, what, cap), n in groups.items():
        text = f"{module}: {what}" if module else what
        lines.append(text + (f" ({cap})" if cap else "") + (f", {n} times" if n > 1 else ""))
    refusals = _plural(len(denials), "recent refusal") if denials else "no recent refusals"
    if audit.get("ok"):
        state = f"Audit log intact: {audit.get('records')} records, chain verified"
    else:
        state = (
            f"AUDIT LOG PROBLEM: the chain breaks at record {audit.get('first_bad_seq')} "
            f"({audit.get('reason') or 'no reason recorded'})"
        )
    counts = {"records": audit.get("records"), "refusals": len(denials), "audit_ok": bool(audit.get("ok"))}
    return {"headline": f"{state} · {refusals}", "counts": counts, "lines": lines}
