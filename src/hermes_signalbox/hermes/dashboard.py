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
