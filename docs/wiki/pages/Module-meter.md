# Module meter

> **Type:** module · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

| | |
|---|---|
| **Does** | Counts every Hermes API response by day, provider and model; quotas with once-per-period thresholds; burn-rate forecast. |
| **Phase / since** | M4 / v0.5.0 |
| **Isolation** | in-process (bundled) |
| **Default activation** | auto |
| **Requests** | [[Capability hermes.hooks]], [[Capability ui.panel]] |
| **Optional** | [[Capability fs.read]] |
| **Spec** | [README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/meter/README.md) |

## What it does

<To write from the module README.>

## Capabilities and why

| Capability | Why it needs it | Without it |
|---|---|---|
| [[Capability hermes.hooks]] | <reason> | <effect> |
| [[Capability ui.panel]] | <reason> | <effect> |
| [[Capability fs.read]] | <reason> | <effect> |

## Turn it on

```bash
hermes-signalbox module grant meter --capability hermes.hooks
hermes-signalbox module grant meter --capability ui.panel
hermes-signalbox module grant meter --capability fs.read
hermes-signalbox module activate meter
```

## Settings (`[modules.meter]`)

<From the README control-surface table.>

## Actions

| Action | Arguments | Model may run | What it does |
|---|---|---|---|
| `summary` | <args> | <yes/no> | <effect> |
| `usage` | <args> | <yes/no> | <effect> |
| `quotas` | <args> | <yes/no> | <effect> |
| `forecast` | <args> | <yes/no> | <effect> |
| `quota_add` | <args> | <yes/no> | <effect> |
| `quota_remove` | <args> | <yes/no> | <effect> |
| `prices_reload` | <args> | <yes/no> | <effect> |

## Events and audit records

<From [Reference](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md).>

## Security notes

<Summary; link the "Security review" table in the README.>

---
**Sources:** [module README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/meter/README.md) · [module.toml](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/meter/module.toml)
