# Pre-work Q&A: M6 supervisor

Date: 2026-11-20. Previous phase: M5, tag v0.6.0.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| M4 | Quota and paid limits only steer: middleware cannot refuse a request | `pre_llm_call` can block a turn (research); used for an opt-in hard stop |
| M5 retro | Live state must not depend on files that retention can delete | Supervisor keeps its own tables; the audit-check time survives restarts |
| M0 | Core `Scheduler` (time triggers, skip while running, `remove_owner` on stop) exists but modules had no access | `schedule` capability (question 10) |

## 2. Research record

| Topic | Source (Hermes v0.23.2, 2026-11-20) | Finding |
|---|---|---|
| Blocking a turn | `agent/turn_context.py` 905-960 | A `pre_llm_call` result `{"action": "block", "message": ...}` vetoes the turn with that message; other plugins' context still collected |
| Background work | `hermes_cli/plugins_idle_tasks.py` 377-390 | `register_idle_task` runs only after hours idle (min 1 h interval): not suitable for minutes-scale supervision. Switchyard's own host tick already runs every few seconds |
| Operator alerts | `hermes_cli/plugins_context.py` 397-420 | `inject_message` needs a session key or an origin chat and queues text **as a message to the model**; `post_message` needs a bound session call. Neither is a safe out-of-band alert channel for a background job |
| References | 42-evey/hermes-plugins; JerryLiu369/hermes-proactive-agent (moved; not resolved) | Ideas for proactive checks only; nothing copied |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Smallest scope? | | Scheduled deterministic checks (failed modules, audit chain, quotas, router pass-throughs) producing de-duplicated findings with automatic resolution; alerts as events and audit records; reading via actions and a panel. Plus the opt-in router hard stop | default accepted |
| 2 | Capabilities | | New `core.read` (module states, audit verification) and `schedule`; `ui.panel`. No `llm.*`: v1 needs no model judgement, so zero LLM calls by construction, and `llm.paid` cannot be granted because it is not requested | default accepted |
| 3 | Reuse, adapt or write? | | Write | default accepted |
| 4 | New dependencies? | | None | default accepted |
| 5 | Security | | Threat table below | default accepted |
| 6 | State; uninstall | | Tables `findings` (resolved ones capped at 500), `runs` (last 500), `kv`. Removed with the module unless `keep_data` | default accepted |
| 7 | Control surface | | Read-only `report`, `findings {state, limit}`; human-only `ack {key}`, `run_now`. Panel `supervisor.status`. Config `[modules.supervisor]` `interval_seconds` (300), `audit_check_hours` (24), `quota_warn_percent` (80) | default accepted |
| 8 | Alerts | (a) events + audit now, Hermes delivery later; (b) `inject_message` | (a). Injecting alerts as model input is a prompt-injection channel and needs a target session; the M8 dashboard and M9 notifications deliver them | default accepted |
| 9 | Update and rollback | | Bundled | default accepted |
| 10 | Core contract change? | | ADR-0006: `schedule` broker over the core scheduler; `core.read` view; `pre_llm_call` gates in the bridge (first non-empty reason blocks; a failing gate does not block) | default accepted |
| 11 | Hard stop | (a) opt-in `[modules.router] hard_stop`; (b) always | (a). Blocking a turn is disruptive; the operator chooses. When on, the router blocks only when no routed choice exists and the configured model is over an exhausted quota or paid while paid is not allowed | default accepted |
| 12 | Operator input? | | None | default accepted |

### Threats and tests (question 5)

| Threat | Control | Test |
|---|---|---|
| Supervisor spends money | No `llm.*` requested; `llm.paid` grant refused | `test_model_is_read_only_and_settings` |
| Unbounded growth during long runs | Runs and resolved findings capped; findings de-duplicated by key | `test_soak_stays_bounded_and_survives_restart` |
| State lost on restart | Tables plus persisted audit-check time | same |
| A broken check stops supervision | Each check isolated; a failure becomes a finding | `test_failed_modules_audit_chain_and_isolated_checks` |
| A buggy gate blocks every turn | Gates fail open (audited); time-bounded | `test_gates_block_with_a_prefixed_reason_and_fail_open` |
| A gate leaks prompt text into the block message | Gates get metadata only; reason is prefixed and capped | same |
| Model acknowledges or silences findings | `ack` and `run_now` are human-only | `test_model_is_read_only_and_settings` |

## 4. Acceptance tests (written before code)

- [x] Runs for a soak period within a fixed resource budget (bounded tables; run duration recorded).
- [x] Zero paid calls (no LLM calls at all; `llm.paid` cannot be granted).
- [x] Recovers after restart (state and audit-check schedule restored).

## 5. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
