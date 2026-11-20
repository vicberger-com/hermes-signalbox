# Offload (bundled module, M11)

Sends work you choose to cheaper resources on this machine. Q&A:
[docs/qa/12-m11-prework.md](../../../../docs/qa/12-m11-prework.md); broker: [ADR-0010](../../../../docs/adr/0010-net-outbound-broker.md).

## Connectors

| Connector | License class | Talks to | Sends only | Default |
|---|---|---|---|---|
| `jevk5` | local | `jevk5_url` (`http://127.0.0.1:8090/v1/systemone`) | `state`, `questions`, `kind` | on |
| `n8n` | source-available | `n8n_webhook` (loopback only) | `task`, `input` | off until allowed |
| `claude-code` | proprietary | `claude -p --tools ""` (no tools; prompt on stdin; empty working directory) | `prompt` | off until allowed |
| `codex` | proprietary | `codex exec --sandbox read-only -` (prompt on stdin; empty working directory) | `prompt` | off until allowed |

A payload field outside a connector's list is refused before anything is sent. Claude Code runs with all tools
disabled, so it can only see the prompt. **Codex has no no-tools mode:** its read-only sandbox can still read
files your account can read, so treat allowing `codex` as allowing it to read local files. Only loopback hosts are allowed.
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

## Security review (M11 gate)

Reviewed 2026-11-20 by a fresh subagent with the M11 diff and threat table.

| Finding | Disposition |
|---|---|
| (high) Agent CLIs ran with their tools in Switchyard's working directory, so they could read local files beyond the declared `prompt` | **Fixed** for Claude Code (`--tools ""`); Codex runs in its read-only sandbox (still reads files: documented); both run in an empty working directory (broker gains `cwd`) |
| (low) A bare manifest host allows any port | **Accepted**, documented in ADR-0010; offload only uses the URLs you configure |
| (low) Malformed URLs raised raw errors before the policy check | **Fixed** |
| (low) A trickling server could hold a call far past its timeout | **Fixed.** Total deadline |
| (low) A response cut short before its length was returned as success | **Fixed.** Treated as a failure |

