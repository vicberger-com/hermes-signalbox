# Inbox (bundled module, M9)

Collects operator notifications for the Signalbox dashboard tab. Q&A:
[docs/qa/10-m9-prework.md](../../../../docs/qa/10-m9-prework.md); [ADR-0009](../../../../docs/adr/0009-notifications-dashboard.md).

## Sources

| Event | Severity |
|---|---|
| `core.notify` (any module granted `notify`) | as sent |
| `supervisor.alert` | as raised (high or critical) |
| `meter.exhausted` / `meter.threshold` | high / medium |
| `workers.stuck` / `workers.loop` | medium / low |
| `module.failed` | high |

Notifications below `min_severity` (default `low`) are dropped. Nothing leaves the machine. Grant `core.read`
(needed to receive `core.notify`, which carries every module's notifications) and `ui.panel`, then activate.

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `list {state: open/acked/all, limit}`, `ack {id}`, `ack_all` | no (text is for the operator) |
| Panel | `inbox.status` | |
| Config | `[modules.inbox]` `min_severity` | |

## Dashboard

The control API that Hermes starts for the dashboard serves only a dashboard profile: module list, show, panels,
activate/deactivate, reports, audit reads and the inbox actions. Other module actions run with the model's
rights (read-only only). Grants, modes, installs, updates, removal and config are refused there; use the
command line or `/signalbox` in a Hermes chat (`hermes-signalbox api serve` keeps the full API for them).

Set `[api] enabled = true` in Signalbox's `config.toml` and restart Hermes; the **Signalbox** tab then shows
modules (state, health, activate/deactivate), the inbox and reports. Grants, installs and config changes stay in
the CLI.

## State and removal

Table `items` (last 1000; acknowledged items are removed first). Removed with the module unless `keep_data`.

## Security review (M9 gate)

Reviewed 2026-11-20 by a fresh subagent with the M9 diff, the threat table and the Hermes v0.23.2 sources.

| Finding | Disposition |
|---|---|
| (high) The API Hermes starts accepted every operation for anyone holding its token (for example the model through a terminal tool reading `api.token`), including grants | **Fixed.** Hermes starts it with the dashboard profile: fixed operations, inbox actions, other module actions with model rights; grants and config refused |
| (medium) A flood of low notifications evicted unacknowledged critical ones | **Fixed.** Pruning removes acknowledged, then least severe, then oldest |
| (low) Truncation before redaction could keep part of a secret | **Fixed.** Redact, then cap |
| (low) API error messages were not redacted | **Fixed** |
| (low) A module with id `core` could publish `core.notify` | **Fixed.** Reserved ids (`core`, `hermes`, `api`, `cli`, `signalbox`, `dashboard`); the inbox also checks the source |
| (low) The dashboard backend ignored a `data_dir` in `config.toml` | **Fixed** |
| (low) Windows address reuse could let a second socket bind the API port | **Fixed.** `allow_reuse_address = False` |
| (low) A busy API port stopped the Signalbox tick | **Fixed.** Start failure is audited; Signalbox keeps running |

CSRF on the dashboard backend was checked and is handled by Hermes (session token header; gated mode refuses
cross-site cookie writes).

