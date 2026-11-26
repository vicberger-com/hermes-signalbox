"""Plain-language labels (H5 WP2; #205, #207, #208): the one source for what capabilities, statuses, modes,
severities, actors and audit actions mean. Chat, CLI text, reports and the dashboard read from here, so a term
is explained the same way everywhere. Static data only: nothing here depends on state or configuration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Label:
    label: str  # a few plain words, shown in place of the id
    meaning: str  # one sentence: what it allows or what it tells the reader


def _table(rows: dict[str, tuple[str, str]]) -> dict[str, Label]:
    return {key: Label(*value) for key, value in rows.items()}


CAPABILITIES = _table({
    "core.read": ("Read Signalbox state", "See the module list, audit records and reports. It cannot change them."),
    "fs.read": ("Read files", "Read the files and folders listed in its manifest, and nothing else."),
    "fs.write": ("Write files", "Create and change files in the folders listed in its manifest."),
    "hermes.config.write": ("Change Hermes settings", "Edit Hermes configuration; each change is audited and can be rolled back."),
    "hermes.delegation": ("Run sub-agents", "Hand tasks to Hermes sub-agents and choose which model they use."),
    "hermes.hooks": ("Watch and steer Hermes requests", "See Hermes events and act before a model call is made."),
    "hermes.output": ("Edit Hermes output", "Shorten or transform tool output before the model sees it."),
    "hermes.tools": ("Add Hermes tools", "Offer its own tools to the model."),
    "llm.free": ("Use free models", "Make model calls on the free pool. No spend."),
    "llm.paid": ("Use paid models", "Make model calls on paid providers. This can cost money."),
    "net.outbound": ("Network access", "Connect to the hosts listed in its manifest, and to no others."),
    "notify": ("Send alerts", "Post notices to the Inbox."),
    "process.spawn": ("Run programs", "Start the programs listed in its manifest."),
    "schedule": ("Run on a timer", "Run its jobs on a schedule while Signalbox is hosted."),
    "secrets.read": ("Use stored secrets", "Use the secrets named in its manifest. Their values are never shown."),
    "ui.panel": ("Show a dashboard panel", "Add its panel to the Signalbox dashboard tab."),
})  # fmt: skip

STATUSES = _table({
    "verified": ("Ready", "Checked and installed, but not started."),
    "active": ("Running", "Started and doing its work."),
    "stopped": ("Stopped", "Was running and has been stopped. Start it again to use it."),
    "failed": ("Error", "Could not start or stopped with an error. The error text says why."),
})  # fmt: skip

MODES = _table({
    "auto": ("Starts with Hermes", "Starts on its own once every permission it needs is granted."),
    "manual": ("Manual start", "Starts only when you start it."),
    "disabled": ("Disabled", "Never starts until you change its mode."),
})  # fmt: skip

SEVERITIES = _table({
    "info": ("Information", "For your records. Nothing to do."),
    "low": ("Low", "Worth a look when convenient."),
    "medium": ("Medium", "Look at it soon: something is not working as intended."),
    "high": ("High", "Act today: a module failed or a limit was reached."),
    "critical": ("Critical", "Act now: security or spending is at risk."),
})  # fmt: skip

ACTORS = _table({
    "cli": ("CLI", "A command typed in a terminal."),
    "api": ("Dashboard", "A click in the Signalbox dashboard tab."),
    "hermes-user": ("You (chat)", "A /signalbox command typed in a Hermes chat."),
    "hermes": ("The model", "The Hermes model, through its Signalbox tools."),
    "core": ("Signalbox", "Signalbox itself, enforcing a rule or running a scheduled step."),
})  # fmt: skip

ACTIONS = _table({
    "api.start_failed": ("Local API did not start", "The local control API could not start; the detail says why."),
    "audit.acknowledged": ("Audit problem acknowledged", "An operator confirmed they looked into an audit-log failure."),
    "audit.verify_failed": ("Audit check failed", "The audit log failed its integrity check. Treat this as tampering until explained."),
    "core.adapter_error": ("Hermes adapter error", "The link to Hermes hit an error and carried on."),
    "core.hosting_acquired": ("Started hosting modules", "This process took over running the modules."),
    "core.migrated": ("Data copied from Switchyard", "A 1.0.x data directory was copied to the new location."),
    "core.not_hosting": ("Not hosting modules", "Another process runs the modules for this data directory."),
    "core.tick_failed": ("Scheduled step failed", "A background step failed; the next run retries it."),
    "core.transform_skipped": ("Output edit skipped", "An output transform was skipped to protect the request."),
    "event.depth_exceeded": ("Event loop stopped", "Modules triggered each other too deeply; the chain was cut."),
    "event.handler_failed": ("Event handler failed", "A module failed while handling an event."),
    "fs.read": ("File read", "A module read a file it is allowed to read."),
    "fs.read_failed": ("File read refused", "A module tried to read a file and was refused or failed."),
    "hermes.config.rollback": ("Hermes setting rolled back", "A change to Hermes settings was undone."),
    "hermes.config.write": ("Hermes setting changed", "A module changed a Hermes setting; a backup was kept."),
    "module.action": ("Module command run", "A module command was run."),
    "module.activated": ("Module started", "A module was started."),
    "module.auto_skipped": ("Auto-start skipped", "A module set to start with Hermes was skipped; it lacks a permission."),
    "module.deactivate_failed": ("Module stop failed", "A module raised an error while stopping."),
    "module.deactivated": ("Module stopped", "A module was stopped."),
    "module.delegation_failed": ("Sub-agent routing failed", "A module failed while routing a sub-agent."),
    "module.delegation_refused": ("Sub-agent routing refused", "A sub-agent request was refused by a rule."),
    "module.failed": ("Module failed", "A module could not start or crashed."),
    "module.gate_blocked": ("Request blocked", "A module blocked a Hermes request by rule."),
    "module.gate_rejected": ("Block ignored", "A module tried to block a request without the right to."),
    "module.hook_failed": ("Hook failed", "A module failed while watching a Hermes event."),
    "module.hook_timeout": ("Hook too slow", "A module took too long on a Hermes event and was skipped."),
    "module.hooks_paused": ("Hooks paused", "A module's hooks were paused after repeated failures."),
    "module.installed": ("Module installed", "A module was installed."),
    "module.job_skipped": ("Scheduled job skipped", "A scheduled job was skipped because the last run was still going."),
    "module.job_timeout": ("Scheduled job too slow", "A scheduled job ran past its time limit."),
    "module.middleware_rejected": ("Request change ignored", "A module's change to a request was rejected."),
    "module.mode_changed": ("Start mode changed", "A module's start mode was changed."),
    "module.notify": ("Alert sent", "A module posted a notice to the Inbox."),
    "module.rejected": ("Module rejected", "A module failed verification and was not loaded."),
    "module.reloaded": ("Module reloaded", "A module's files were read again."),
    "module.removed": ("Module removed", "A module was uninstalled."),
    "module.rolled_back": ("Update rolled back", "A module was restored to its previous version."),
    "module.transform_paused": ("Output edits paused", "A module's output edits were paused after failures."),
    "module.update_check_failed": ("Update check failed", "Checking a module's update source failed."),
    "module.update_previewed": ("Update previewed", "An update was staged for review; nothing was applied."),
    "module.update_rejected": ("Update refused", "An update was refused by a safety check."),
    "module.updated": ("Module updated", "A module was updated to a new version."),
    "module.verified": ("Module verified", "A module passed verification."),
    "net.request": ("Network request", "A module connected to an allowed host."),
    "policy.denied": ("Permission refused", "Something was refused because a permission is missing."),
    "policy.grant_refused": ("Grant refused", "A permission could not be granted; the module does not request it."),
    "policy.granted": ("Permission granted", "A permission was granted to a module."),
    "policy.grants_removed": ("Permissions removed", "All of a module's permissions were removed."),
    "policy.revoked": ("Permission revoked", "A permission was taken away from a module."),
    "process.spawned": ("Program started", "A module started an allowed program."),
    "secret.backend_added": ("Secret store added", "A secret store was connected."),
    "secret.backend_error": ("Secret store error", "A secret store returned an error."),
    "secret.backend_removed": ("Secret store removed", "A secret store was disconnected."),
    "secret.leak_blocked": ("Secret leak blocked", "A secret value was about to appear in output and was removed."),
    "secret.unavailable": ("Secret unavailable", "A module asked for a secret that could not be read."),
    "secret.used": ("Secret used", "A module used a stored secret (name only; the value is never recorded)."),
    "trigger.failed": ("Trigger failed", "A lazy-start trigger failed to start its module."),
})  # fmt: skip

_VERBS = {
    "module.activated": "started {module}",
    "module.deactivated": "stopped {module}",
    "module.removed": "removed {module}",
    "module.reloaded": "reloaded {module}",
    "module.installed": "installed {module}",
    "module.updated": "updated {module}",
    "module.rolled_back": "rolled {module} back to its previous version",
    "policy.grants_removed": "removed every permission from {module}",
}


def capability(name: str) -> str:
    entry = CAPABILITIES.get(name)
    return entry.label if entry else name


def actor(name: str) -> str:
    entry = ACTORS.get(name)
    return entry.label if entry else name


def action(name: str) -> str:
    """The label of an audit action. Module actions (``module.<id>.<name>``) read as "Router: hard stop"."""
    entry = ACTIONS.get(name)
    if entry:
        return entry.label
    parts = name.split(".")
    if len(parts) == 3 and parts[0] == "module":
        return f"{parts[1].capitalize()}: {parts[2].replace('_', ' ')}"
    return name


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def sentence(record: Mapping[str, Any]) -> str:
    """One audit record as a sentence: who did what to which module."""
    name = str(record.get("action", ""))
    module = str(record.get("module") or "Signalbox")
    who = actor(str(record.get("actor", "")))
    detail = record.get("detail") or {}
    cap = str(detail.get("capability", "")) if isinstance(detail, Mapping) else ""
    if name in ("policy.granted", "policy.revoked") and cap:
        means = _lower_first(capability(cap))
        if name == "policy.granted":
            return f"{who} granted {module} the permission to {means}"
        return f"{who} revoked {module}'s permission to {means}"
    if name == "module.mode_changed" and isinstance(detail, Mapping) and detail.get("mode") in MODES:
        return f"{who} set {module} to {_lower_first(MODES[str(detail['mode'])].label)}"
    if name in _VERBS:
        return f"{who} {_VERBS[name].format(module=module)}"
    return f"{action(name)} ({module})" if record.get("module") else action(name)


def module_state(row: Mapping[str, Any]) -> str:
    """A module's state in plain words, from a ``module list`` row."""
    status, mode = row.get("status"), row.get("mode")
    if status == "failed":
        return "Error"
    if status == "active":
        return "Running"
    if mode == "disabled":
        return "Disabled"
    if row.get("missing_grants"):
        return "Ready, needs permissions"
    if status == "stopped":
        return "Stopped"
    if mode == "manual":
        return "Manual start"
    return "Ready, starts with Hermes"


def update_state(update: Mapping[str, Any]) -> str:
    """The update state of a module in plain words, from the ``update`` part of ``module show``."""
    state = update.get("state")
    if state == "bundled":
        return "Updates with Signalbox"
    if state == "not_checked":
        return "Not checked: start the updates module to check"
    minutes = update.get("checked_minutes_ago")
    when = " (checked just now)" if minutes == 0 else f" (checked {minutes} min ago)" if minutes else ""
    if state == "up_to_date":
        return f"Up to date{when}"
    if state == "available":
        old, new = str(update.get("installed") or "?")[:7], str(update.get("available") or "?")[:7]
        return f"Update available: {old} \u2192 {new}{when}"
    if state == "check_failed":
        return f"The last check failed{when}"
    return "Unknown"


def glossary() -> dict[str, dict[str, dict[str, str]]]:
    """Every table as plain data, for the API, the dashboard and the user guide."""
    tables = {
        "capabilities": CAPABILITIES, "statuses": STATUSES, "modes": MODES, "severities": SEVERITIES,
        "actions": ACTIONS, "actors": ACTORS,
    }  # fmt: skip
    return {
        name: {key: {"label": e.label, "meaning": e.meaning} for key, e in sorted(table.items())}
        for name, table in tables.items()
    }
