# Supervisor (bundled module, M6)

Runs deterministic checks on a schedule and keeps a list of findings. Q&A:
[docs/qa/07-m6-prework.md](../../../../docs/qa/07-m6-prework.md); core pieces:
[ADR-0006](../../../../docs/adr/0006-schedules-core-view-gates.md).

## Checks (every `interval_seconds`, default 300)

| Key | Severity | Condition |
|---|---|---|
| `module:<id>:failed` | high | a module is in the `failed` state |
| `audit:chain` | critical | the audit chain does not verify (checked every `audit_check_hours`, default 24; the time survives restarts) |
| `quota:<name>` | medium / high | a meter quota at or above `quota_warn_percent` (80) / exhausted |
| `router:passthrough` | medium | recent router decisions sent a ruled-out model because nothing free was left |
| `supervisor:check:<name>` | low | a check itself failed (each check is isolated) |

Findings are de-duplicated by key, counted, resolved automatically when the condition clears, and re-opened
when they escalate. A new or escalated **high** or **critical** finding raises the event `supervisor.alert` and
the audit record `module.supervisor.alert`. Delivery into Hermes chats comes with the dashboard (M8) and
notifications (M9): injecting alerts as model input would be a prompt-injection channel.

No model is called. Every check is deterministic, so the supervisor makes zero LLM calls; it does not request
`llm.*`, so paid use cannot even be granted.

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `report`, `findings {state: open/acked/resolved/all, limit}` | yes |
| Action | `ack {key}`, `run_now` | no |
| Panel | `supervisor.status` | |
| Config | `[modules.supervisor]` `interval_seconds` (300, 60-3600), `audit_check_hours` (24, 1-168), `quota_warn_percent` (80) | |

Capabilities: `schedule`, `core.read`, `ui.panel`.

## State and removal

Tables `findings` (resolved findings capped at 500), `runs` (last 500), `kv`. Removed with the module unless
`keep_data`.
