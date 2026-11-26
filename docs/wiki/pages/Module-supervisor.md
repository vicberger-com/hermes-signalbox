# Module supervisor

> **Type:** module · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

| | |
|---|---|
| **Does** | Scheduled deterministic checks (failed modules, audit chain, quotas, ruled-out models); de-duplicated findings and alerts; no LLM calls. |
| **Phase / since** | M6 / v0.7.0 |
| **Isolation** | in-process (bundled) |
| **Default activation** | auto |
| **Requests** | [[Capability schedule]], [[Capability core.read]], [[Capability ui.panel]] |
| **Optional** | — |
| **Spec** | [README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/supervisor/README.md) |

## What it does

<To write from the module README.>

## Capabilities and why

| Capability | Why it needs it | Without it |
|---|---|---|
| [[Capability schedule]] | <reason> | <effect> |
| [[Capability core.read]] | <reason> | <effect> |
| [[Capability ui.panel]] | <reason> | <effect> |

## Turn it on

```bash
hermes-signalbox module grant supervisor --capability schedule
hermes-signalbox module grant supervisor --capability core.read
hermes-signalbox module grant supervisor --capability ui.panel
hermes-signalbox module activate supervisor
```

## Settings (`[modules.supervisor]`)

<From the README control-surface table.>

## Actions

| Action | Arguments | Model may run | What it does |
|---|---|---|---|
| `report` | <args> | <yes/no> | <effect> |
| `findings` | <args> | <yes/no> | <effect> |
| `ack` | <args> | <yes/no> | <effect> |
| `run_now` | <args> | <yes/no> | <effect> |

## Events and audit records

<From [Reference](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md).>

## Security notes

<Summary; link the "Security review" table in the README.>

---
**Sources:** [module README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/supervisor/README.md) · [module.toml](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/supervisor/module.toml)
