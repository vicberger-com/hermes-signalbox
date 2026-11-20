# Inbox (bundled module, M9)

Collects operator notifications for the Switchyard dashboard tab. Q&A:
[docs/qa/10-m9-prework.md](../../../../docs/qa/10-m9-prework.md); [ADR-0009](../../../../docs/adr/0009-notifications-dashboard.md).

## Sources

| Event | Severity |
|---|---|
| `core.notify` (any module granted `notify`) | as sent |
| `supervisor.alert` | as raised (high or critical) |
| `meter.exhausted` / `meter.threshold` | high / medium |
| `workers.stuck` / `workers.loop` | medium / low |
| `module.failed` | high |

Notifications below `min_severity` (default `low`) are dropped. Nothing leaves the machine.

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `list {state: open/acked/all, limit}`, `ack {id}`, `ack_all` | no (text is for the operator) |
| Panel | `inbox.status` | |
| Config | `[modules.inbox]` `min_severity` | |

## Dashboard

Set `[api] enabled = true` in Switchyard's `config.toml` and restart Hermes; the **Switchyard** tab then shows
modules (state, health, activate/deactivate), the inbox and reports. Grants, installs and config changes stay in
the CLI.

## State and removal

Table `items` (last 1000; acknowledged items are removed first). Removed with the module unless `keep_data`.
