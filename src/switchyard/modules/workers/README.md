# Workers (bundled module, M7)

Worker roles and teams for Hermes delegation. Q&A: [docs/qa/08-m7-prework.md](../../../../docs/qa/08-m7-prework.md);
core pieces: [ADR-0007](../../../../docs/adr/0007-delegation-routing.md).

## Turning it on

1. Grant `hermes.hooks`, `hermes.delegation`, `schedule`, `ui.panel` (and `llm.paid` only if roles may use
   paid models) and activate the module.
2. Define roles and, for pool roles, bind a resources pool to the consumer `subagent:<role>`.
3. In Hermes config set `delegation.backend: switchyard`, then start a new Hermes session (the
   `delegate_task` schema is built per session).

## Roles, personas and teams

| Role kind | Set with | What the child gets |
|---|---|---|
| Pool role | `role_set {name, description, tier, max_minutes}` | The router's choice for consumer `subagent:<role>` at the role's tier: free first; paid only by the router's rules and budget **and** this module's `llm.paid` grant |
| Persona | `role_set {name, description, profile, max_minutes}` | Runs as that Hermes profile: its model, skills, SOUL.md and terminal policy |

Teams (`team_set {name, roles: "a,b"}`) group roles; the team names appear next to each role in the
`delegate_task` description. The model picks a role per task through the `worker_role` parameter
(`default_role` applies when it gives none).

Refusals reach the model as a core-written sentence with a code: `worker_role_required`, `unknown_role`,
`repeated_delegation`, `router_unavailable`, `paid_not_granted`, `no_model_available`.

## Ledger, stuck and loop detection

- Each routed task and the subagent it became (linked by a goal digest; the module never sees goal text) is
  recorded, with status, duration and the chosen model or profile. It survives restarts.
- A worker running past its role's `max_minutes` (60 for unrouted children) is marked `stuck`, audited and
  announced once as `workers.stuck`. Hermes gives plugins no handle to stop a `delegate_task` child, so the
  operator stops it.
- The same goal routed `loop_limit` (3) times within `loop_window_minutes` (10) is refused
  (`workers.loop`, audited).
- The router leaves a routed child's model alone (ADR-0007 decision 5).

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `report`, `roles`, `teams`, `ledger {state: running/stuck/done/failed/all, limit}` | yes |
| Action | `role_set`, `role_remove`, `team_set`, `team_remove` | no |
| Panel | `workers.status` | |
| Config | `[modules.workers]` `default_role` (""), `loop_window_minutes` (10, 1-1440), `loop_limit` (3, 2-20), `check_seconds` (60, 10-3600) | |

## State and removal

Tables `roles` (at most 64), `teams` (32), `routes` and `runs` (last 5000 each). Removed with the module unless
`keep_data`.
