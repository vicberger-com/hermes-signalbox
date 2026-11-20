# Pre-work Q&A: M7 workers, personas and teams

Date: 2026-11-20. Previous phase: M6, tag v0.7.0.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| M6 retro | Read each hook's real keyword arguments; block or refuse only on positive knowledge; modules return codes, the core writes text the model sees | Delegation routes use codes and core-written refusals; tests use Hermes's real shapes |
| M6 retro | Revoking a required capability stops the module | `hermes.delegation` is required: revoking it removes the route |
| M3 | Router middleware runs on every Hermes request, children included | Subagents routed by a role are marked so the router keeps the role's model |

## 2. Research record

| Topic | Source (Hermes v0.23.2, 2026-11-20) | Finding |
|---|---|---|
| Choosing a child's model | `agent/delegation_provider.py`, `plugins_registrars.py` 87 | A plugin `DelegationProvider` answers `route_task(task)` with `model`/`provider` or a Hermes `profile`; selected by `delegation.backend`; may add per-task schema parameters (an `enum` is enforced by core); `is_available() == False` fails delegation closed |
| Refusing a task | `DelegationRouteError` | The message becomes the tool error **the model reads** |
| Personas | route key `profile` | A profile carries its own model, skills, SOUL.md and terminal policy: a role bound to a profile is a persona |
| Tool sets per role | `RESERVED_TASK_PARAMETERS` includes `toolsets` | A provider cannot set a child's tool sets; profile routes are the way to give a role its own tool policy |
| Ledger | `tools/delegate_tool.py` 380 `subagent_start`, `delegate_tool_results.py` 382 `subagent_stop` | Both carry `child_session_id`; start carries `child_goal` (text), stop carries `child_status`, `duration_ms`, `child_summary` (text) |
| Stopping a child | `agent/subagent_lifecycle.py` | Cancel needs the handle from a lifecycle `launch`; `delegate_task` children give plugins no handle. Stuck workers are reported, not killed |
| Request middleware on children | `agent/turn_api_request.py` 161 | `llm_request` middleware runs for children too, with their `session_id` |
| References | BkashJEE/hermes-bot-forge, UmLyrithyreach/orchestrator, mattpocock/skills, kerpopule/hermes-jev-skills | Role/team vocabulary only; nothing copied |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Smallest scope? | | Roles (pool via router, or Hermes profile), teams (groups of roles), a Switchyard delegation backend, a ledger, stuck and loop detection | default accepted |
| 2 | Capabilities | | New `hermes.delegation` (human grant, one module at a time); `hermes.hooks` for the ledger; `schedule`; `ui.panel`; `llm.paid` optional and needed before a role may route to a paid model | default accepted |
| 3 | Reuse, adapt or write? | | Write | default accepted |
| 4 | New dependencies? | | None | default accepted |
| 5 | Security | | Threat table below | default accepted |
| 6 | State; uninstall | | Tables `roles` (64 max), `teams` (32 max), `routes` and `runs` (5000 each). Removed with the module unless `keep_data` | default accepted |
| 7 | Control surface | | Read-only `report`, `roles`, `teams`, `ledger`; human-only `role_set`, `role_remove`, `team_set`, `team_remove`. Config `default_role`, `loop_window_minutes` (10), `loop_limit` (3), `check_seconds` (60) | default accepted |
| 8 | What the module sees | | Role, a 16-hex digest of the goal, the task index. Never goal, context or summary text | default accepted |
| 9 | Failure mode | (a) fail closed; (b) fall back to Hermes's default route | (a). The operator selected this backend; a silent fallback could pick a paid route the role forbids | default accepted |
| 10 | Core contract change? | | ADR-0007 | default accepted |
| 11 | Stopping stuck workers | (a) report; (b) cancel via lifecycle API | (a): Hermes gives no handle for `delegate_task` children. Event `workers.stuck` + audit | default accepted |
| 12 | Operator input? | | One opt-in step: `delegation.backend: switchyard` in Hermes config (documented, not written by Switchyard) | default accepted |

### Threats and tests (question 5)

| Threat | Control | Test |
|---|---|---|
| Module text injected into the model through a refusal | Refusals are codes; the core writes the sentence | `test_module_sees_no_text_and_bad_answers_fail_closed` |
| Module reads delegated goals, context or summaries | Module gets role, goal digest, index only; observers metadata only | same |
| Route smuggles credentials or endpoints (`api_key`, `base_url`) | Only `{model, provider}` or `{profile}` accepted, validated | same |
| Paid subagents without consent | Router paid rules and budget **and** the workers `llm.paid` grant | `test_paid_needs_the_workers_grant` |
| Router overrides a role's model on the child's requests | Children started from a routed task are routed within their role's consumer (paid rules, budget, quotas apply) | `test_per_role_model_binding_is_honoured` |
| Runaway re-delegation | Same goal routed `loop_limit` times in the window is refused | `test_loop_detection_refuses_repeated_delegation` |
| Model edits roles to escalate | Role and team changes are human-only | `test_router_down_and_actions` |

## 4. Acceptance tests (written before code)

- [x] Per-role model binding honoured (`test_per_role_model_binding_is_honoured`).
- [x] Ledger survives restart (`test_ledger_links_routes_and_survives_restart`).
- [x] Loop detection (`test_loop_detection_refuses_repeated_delegation`).

## 5. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
| Leaving a child alone keeps the role's choice | It also skipped paid charging and quotas; route the child within its role's consumer instead | Router, any per-request policy |
| An operator-named persona is safe to run | Its profile's model can be paid; the operator declares cost and the router still steers | Workers, future profile routes |
| A digest is a good link key | Without consumption it links many children; consume once and scope to the owner | Bridge child tracking |

