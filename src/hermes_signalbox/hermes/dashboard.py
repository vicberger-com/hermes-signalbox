"""Support for the dashboard backend (``dashboard/plugin_api.py``), kept in the package so it is typed and
unit-tested without FastAPI (H4 R1-F10, R1-F11).

The dashboard runs in Hermes's web server process, which has no ``PluginContext``. It finds the agent
plugin's data directory with the same names Hermes uses to build ``ctx.state``
(``hermes_cli.plugins_state.PluginState``, published plugin API) and the same precedence as the adapter's
core (``paths.resolve_data_dir``). Up to v1.0.2 it used ``plugin_data_dir(<plugin name>)`` from
``plugins.plugin_storage``: a different directory than the plugin's
(``plugin-data/agent-plugin-signalbox-<digest>``), and one that the call creates.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hermes_signalbox import labels
from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.legacy import legacy_env
from hermes_signalbox.paths import ENV_VAR, resolve_data_dir

PLUGIN_ID = "signalbox"
HEALTH_MAX = 120  # characters of the Health cell


def configured_data_dir(config: Mapping[str, Any]) -> Path | None:
    """The plugin's ``data_dir`` setting in Hermes's configuration, read the way ``PluginContext.get_config``
    reads it: ``plugins.entries.signalbox.settings.data_dir``, then the legacy ``config`` subtree."""
    plugins = config.get("plugins")
    entries = plugins.get("entries") if isinstance(plugins, Mapping) else None
    entry = entries.get(PLUGIN_ID) if isinstance(entries, Mapping) else None
    if not isinstance(entry, Mapping):
        return None
    for subtree in ("settings", "config"):
        section = entry.get(subtree)
        if isinstance(section, Mapping) and "data_dir" in section:
            value = section["data_dir"]
            return Path(value) if isinstance(value, str) and value else None
    return None


def _hermes_config() -> Mapping[str, Any]:
    """Hermes's configuration, or nothing outside Hermes (then no setting can name a directory)."""
    try:
        import hermes_cli.config as config  # type: ignore[import-not-found,unused-ignore]
    except ImportError:
        return {}
    load = getattr(config, "load_config_readonly", None) or config.load_config
    loaded = load()
    return loaded if isinstance(loaded, Mapping) else {}


def _plugin_state_dir() -> Path:
    from hermes_cli.plugins_state import PluginState  # type: ignore[import-not-found,unused-ignore]

    return Path(PluginState(PLUGIN_ID).data_dir)


def data_dir() -> Path:
    """The data directory the Signalbox plugin uses in this Hermes profile. Creates nothing."""
    configured = configured_data_dir(_hermes_config())
    try:
        needs_plugin_dir = configured is None and not legacy_env(os.environ, "DATA_DIR")[0]
        hermes_dir = _plugin_state_dir() if needs_plugin_dir else None
    except ImportError as exc:
        raise SignalboxError(
            f"this Hermes does not publish the plugin data directory; set {ENV_VAR} for the dashboard"
        ) from exc
    return resolve_data_dir(configured=configured, hermes_dir=hermes_dir)


def health_cell(result: object) -> str:
    """The Health column for one ``module health`` result."""
    if not isinstance(result, Mapping):
        return "unknown"
    if result.get("ok") is True:
        return "ok"
    detail = str(result.get("detail") or "").strip()
    text = f"failing: {detail}" if detail else "failing"
    return text[:HEALTH_MAX]


def rows_with_health(
    rows: Sequence[Mapping[str, Any]], health: Callable[[str], object]
) -> list[dict[str, Any]]:
    """``module list`` rows with a ``health`` cell: the check's result for running modules, empty for the
    others (nothing runs to check). A check that errors shows ``unknown`` and leaves the list intact."""
    out: list[dict[str, Any]] = []
    for row in rows:
        cell = ""
        if row.get("status") == "active":
            try:
                cell = health_cell(health(str(row.get("id", ""))))
            except Exception:  # the list must still render; the cell says the check did not answer
                cell = "unknown"
        out.append({**row, "health": cell})
    return out


_DETAILS = ("summary", "license", "source", "links", "based_on", "update")


def module_rows(
    rows: Sequence[Mapping[str, Any]], show: Callable[[str], object], health: Callable[[str], object]
) -> list[dict[str, Any]]:
    """The rows of the Modules view (H5 WP3; #206, #210): ``module list`` rows with the Health cell, the
    state in plain words, and each module's description, source, links and last known update state from
    ``module show``. A ``show`` call that errors leaves the row in the table without the details."""
    out: list[dict[str, Any]] = []
    for row in rows_with_health(rows, health):
        try:
            shown = show(str(row.get("id", "")))
        except Exception:  # the table must still render
            shown = None
        detail = shown if isinstance(shown, Mapping) else {}
        raw = detail.get("update")
        update: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
        out.append({
            **row,
            "summary": str(detail.get("summary") or ""),
            "license": str(detail.get("license") or ""),
            "source": dict(detail["source"]) if isinstance(detail.get("source"), Mapping) else {},
            "links": dict(detail["links"]) if isinstance(detail.get("links"), Mapping) else {},
            "based_on": [dict(b) for b in detail.get("based_on") or () if isinstance(b, Mapping)],
            "update": dict(update),
            "update_text": labels.update_state(update),
            "state": labels.module_state(row),
        })  # fmt: skip
    return out


# H5 WP4 (#207, #208): the Reports and Inbox views ---------------------------------------------------------

_FIELD = re.compile(r"([a-z_][a-z0-9_.]*)=(\S.*)\Z")
_ORDER = {"failed": 0, "active": 1}


def _permission(capability: str) -> str:
    names = [c.strip() for c in capability.split(",") if c.strip()]
    return ", ".join(f"{labels.capability(c)} ({c})" for c in names)


def _plain(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list | tuple):
        return ", ".join(_plain(v) for v in value)
    return str(value)


def _lines(data: Mapping[str, Any], prefix: str = "") -> list[str]:
    """``key: value`` lines for a person: words instead of snake_case, nothing for an empty value."""
    out: list[str] = []
    for key, value in data.items():
        name = prefix + str(key).replace("_", " ")
        if value is None or value == "" or value == [] or value == {}:
            continue
        if isinstance(value, Mapping):
            out += _lines(value, f"{name}, ")
        else:
            out.append(f"{name}: {_plain(value)}")
    return out


def _records(value: object) -> list[Mapping[str, Any]]:
    return [r for r in value if isinstance(r, Mapping)] if isinstance(value, list) else []


def report_view(report: object) -> dict[str, Any]:
    """What the Reports view lays out for one ``report show`` result: sentences and labels instead of audit
    records and ids, repeats counted, newest first. Chain hashes and raw records stay in the report itself."""
    if not isinstance(report, Mapping):
        return {}
    kind = report.get("kind")
    if kind == "health":
        rows = sorted(
            _records(report.get("modules")),
            key=lambda m: (_ORDER.get(str(m.get("status")), 2), str(m.get("id"))),
        )
        return {
            "rows": [
                {
                    "id": str(m.get("id", "")),
                    "state": labels.module_state(m),
                    "detail": str(m.get("error") or ""),
                    "needs": [_permission(str(c)) for c in m.get("missing_grants") or ()],
                }
                for m in rows
            ]
        }
    if kind == "usage":
        sections = []
        for name, data in report.items():
            if (
                name in ("kind", "purpose", "summary")
                or not isinstance(data, Mapping)
                or "unavailable" in data
            ):
                continue
            sections.append({"name": str(name), "lines": _lines(data)})
        return {"sections": sections}
    if kind == "security":
        grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
        for r in reversed(_records(report.get("recent_denials"))):  # newest first
            detail = r.get("detail")
            capability = str(detail.get("capability", "")) if isinstance(detail, Mapping) else ""
            what = labels.action(str(r.get("action", "")))
            key = (str(r.get("module", "")), what, capability)
            if key in grouped:
                grouped[key]["count"] += 1
                continue
            grouped[key] = {
                "when": str(r.get("ts", "")),
                "who": labels.actor(str(r.get("actor", ""))),
                "module": key[0],
                "what": what,
                "permission": _permission(capability),
                "count": 1,
            }
        audit = report.get("audit")
        return {
            "audit_ok": bool(isinstance(audit, Mapping) and audit.get("ok")),
            "rows": list(grouped.values()),
        }
    if kind == "changes":
        out: list[dict[str, Any]] = []
        for r in reversed(_records(report.get("changes"))):
            who, what = labels.actor(str(r.get("actor", ""))), labels.sentence(r)
            if out and (out[-1]["who"], out[-1]["what"]) == (who, what):
                out[-1]["count"] += 1  # the same change repeated back to back
                continue
            out.append({"when": str(r.get("ts", "")), "who": who, "what": what, "count": 1})
        return {"rows": out}
    return {}


def _fields(detail: str) -> list[dict[str, str]]:
    """``key=value, key=value`` (how module events are stored) as labelled fields; anything else is text."""
    parts = [part for part in detail.split(", ") if part]
    matches = [_FIELD.match(part) for part in parts]
    if not parts or not all(matches):
        return []
    return [
        {"label": m.group(1).replace("_", " ").replace(".", " ").capitalize(), "value": m.group(2)}
        for m in matches
        if m is not None
    ]


def inbox_view(result: object) -> dict[str, Any]:
    """The Inbox view for one ``inbox list`` result: the items as stored, plus ``groups`` (identical notices
    merged with a count, newest first, severity and detail fields labelled) and the number still open."""
    raw = result.get("items") if isinstance(result, Mapping) else None
    items = [dict(i) for i in raw if isinstance(i, Mapping)] if isinstance(raw, list) else []
    groups: dict[tuple[str, ...], dict[str, Any]] = {}
    for item in items:
        key = tuple(str(item.get(k, "")) for k in ("module", "type", "severity", "title", "detail", "state"))
        at = item.get("at") if isinstance(item.get("at"), int | float) else 0.0
        if key in groups:
            groups[key]["ids"].append(str(item.get("id", "")))
            groups[key]["count"] += 1
            groups[key]["at"] = max(groups[key]["at"], at)
            continue
        severity = labels.SEVERITIES.get(key[2])
        fields = _fields(key[4])
        groups[key] = {
            "ids": [str(item.get("id", ""))],
            "count": 1,
            "at": at,
            "module": key[0],
            "severity": key[2],
            "severity_label": severity.label if severity else key[2],
            "severity_meaning": severity.meaning if severity else "",
            "title": key[3] or key[1],
            "state": key[5],
            "text": "" if fields else key[4],
            "fields": fields,
        }
    ordered = sorted(groups.values(), key=lambda g: -float(g["at"]))
    return {"items": items, "groups": ordered, "open": sum(1 for i in items if i.get("state") == "open")}
