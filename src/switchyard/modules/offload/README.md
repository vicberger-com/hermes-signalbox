# Offload (bundled module, M11)

Sends work you choose to cheaper resources on this machine. Q&A:
[docs/qa/12-m11-prework.md](../../../../docs/qa/12-m11-prework.md); broker: [ADR-0010](../../../../docs/adr/0010-net-outbound-broker.md).

## Connectors

| Connector | License class | Talks to | Sends only | Default |
|---|---|---|---|---|
| `jevk5` | local | `jevk5_url` (`http://127.0.0.1:8090/v1/systemone`) | `state`, `questions`, `kind` | on |
| `n8n` | source-available | `n8n_webhook` (loopback only) | `task`, `input` | off until allowed |
| `claude-code` | proprietary | `claude -p` (prompt on stdin) | `prompt` | off until allowed |
| `codex` | proprietary | `codex exec -` (prompt on stdin) | `prompt` | off until allowed |

A payload field outside a connector's list is refused before anything is sent. Only loopback hosts are allowed.
The audit log records the connector and field names, never values; the webhook path (a credential) is never
shown.

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `connectors` (declarations, enabled state), `report` (runs and failures) | yes |
| Action | `run {connector, payload: JSON object}` | no |
| Panel | `offload.status` | |
| Config | `[modules.offload]` `allow` ([]), `jevk5_url`, `n8n_webhook`, `timeout_seconds` (60, 5-600) | |

Grant `net.outbound` and `ui.panel` (and `process.spawn` for the agent CLIs), then activate (manual).
