# Module workers

> **Type:** module · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

| | |
|---|---|
| **Does** | Worker roles and teams for Hermes delegation: each role routes to its own model pool or Hermes profile; a ledger of spawned work, stuck and loop detection. |
| **Phase / since** | M7 / v0.8.0 |
| **Isolation** | in-process (bundled) |
| **Default activation** | auto |
| **Requests** | [[Capability hermes.hooks]], [[Capability hermes.delegation]], [[Capability schedule]], [[Capability ui.panel]] |
| **Optional** | [[Capability llm.paid]] |
| **Spec** | [README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/workers/README.md) |

## What it does

<To write from the module README.>

## Capabilities and why

| Capability | Why it needs it | Without it |
|---|---|---|
| [[Capability hermes.hooks]] | <reason> | <effect> |
| [[Capability hermes.delegation]] | <reason> | <effect> |
| [[Capability schedule]] | <reason> | <effect> |
| [[Capability ui.panel]] | <reason> | <effect> |
| [[Capability llm.paid]] | <reason> | <effect> |

## Turn it on

```bash
hermes-signalbox module grant workers --capability hermes.hooks
hermes-signalbox module grant workers --capability hermes.delegation
hermes-signalbox module grant workers --capability schedule
hermes-signalbox module grant workers --capability ui.panel
hermes-signalbox module grant workers --capability llm.paid
hermes-signalbox module activate workers
```

## Settings (`[modules.workers]`)

<From the README control-surface table.>

## Actions

| Action | Arguments | Model may run | What it does |
|---|---|---|---|
| `report` | <args> | <yes/no> | <effect> |
| `roles` | <args> | <yes/no> | <effect> |
| `teams` | <args> | <yes/no> | <effect> |
| `ledger` | <args> | <yes/no> | <effect> |
| `role_set` | <args> | <yes/no> | <effect> |
| `role_remove` | <args> | <yes/no> | <effect> |
| `team_set` | <args> | <yes/no> | <effect> |
| `team_remove` | <args> | <yes/no> | <effect> |

## Events and audit records

<From [Reference](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md).>

## Security notes

<Summary; link the "Security review" table in the README.>

---
**Sources:** [module README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/workers/README.md) · [module.toml](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/workers/module.toml)
