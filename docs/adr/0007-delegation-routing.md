# ADR-0007: Delegation routing

Status: accepted, 2026-11-20. Phase: M7. Q&A: [08-m7-prework.md](../qa/08-m7-prework.md) question 10.

## Decision

1. The Hermes adapter registers a delegation backend named `switchyard`. It does nothing unless the operator
   sets `delegation.backend: switchyard` in Hermes config, and then it is available only while a module holds
   the route (otherwise Hermes fails delegation closed).
2. New capability `hermes.delegation`. One module at a time registers `ctx.hermes_delegation(route, roles)`.
   `roles()` feeds a `worker_role` enum (validated names, one-line descriptions) into the `delegate_task` schema.
3. `route(meta)` gets only `worker_role`, `goal_sha` (16 hex characters of SHA-256 over the whitespace-folded
   goal) and `index`. It returns `{"model", "provider"}`, `{"profile"}` or `{"refuse": code}`. Values are
   validated; any other shape, an error or a timeout refuses the task. Refusal messages are written by the core,
   because Hermes shows them to the model.
4. Observer hooks gain `subagent_start`; `metadata_only` adds `goal_sha` for `child_goal` and keeps
   `child_subagent_id`/`parent_subagent_id`; goal, context and summary text never reach modules.
5. A route may also carry `consumer` (`subagent:<role>`) and `free_only`, kept by Switchyard and never sent
   to Hermes. The first child started with that goal consumes the route (pending routes die with their owner);
   until its `subagent_stop`, its requests reach `llm_request` middleware with `delegated`,
   `delegated_consumer` and `delegated_free_only`, so the router routes the child **within the role's consumer**
   with the same paid rules, per-request budget charge, quotas and failover as the main session (M7 review:
   skipping children let paid routes go uncharged).
6. Every role the operator defines is offered to the model; the operator chooses the menu. A persona's profile
   model is declared `paid` by the operator; a paid persona needs the module's `llm.paid` grant, and the router
   still steers its requests.

## Consequences

- Per-role tool sets are only possible through profile routes (Hermes reserves `toolsets`).
- Stuck children are reported, not stopped: Hermes gives plugins no handle for `delegate_task` children.
