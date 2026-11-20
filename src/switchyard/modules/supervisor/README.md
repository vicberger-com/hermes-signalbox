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

## Security review (M6 gate)

Reviewed 2026-11-20 by a fresh subagent with the M6 diff, the threat table and the Hermes v0.23.2 sources.

| Finding | Disposition |
|---|---|
| (high) Router gate assumed a `provider` key that Hermes's `pre_llm_call` does not send, so it could block turns of unknown models or other providers | **Fixed.** The gate finds the routed provider whose registry knows the model and blocks only with positive knowledge; tests use Hermes's real keyword arguments |
| (high) Gate blocked when the registry was down | **Fixed.** No registry answer, no block |
| (high) Scheduled jobs ran on the tick under the core lock with no time bound | **Fixed.** Per-module worker, 5 s wait, skip while running, no core lock held |
| (medium) Revoking a capability left hooks, gates and jobs running | **Fixed.** Revoking a required capability deactivates the module |
| (medium) Gate reason text became the stored assistant reply | **Fixed.** Gates return a reason code; the core writes the sentence |
| (medium) One hung module could exhaust the shared hook pool; the router gate held its lock across a cross-module call | **Fixed.** Per-module pools; the gate no longer takes the router lock |
| (medium) `verify_audit` callable in a loop | **Fixed.** Cached for 60 s |
| (low) `ack` with a long key reported success without effect | **Fixed** |
| (low) A failed audit verification was deferred a full day | **Fixed.** Stays due until it succeeds |

Also fixed while here: the control API's handling of a request with `Transfer-Encoding` could reset the
connection on Windows before the client read the `400` reply (the long-standing occasional local test failure).

