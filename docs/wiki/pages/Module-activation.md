# Module activation

> **Type:** module · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

| | |
|---|---|
| **Does** | Skill inventory with prompt cost, presets, index-size benchmark, timed presets; every config change backed up and reversible. |
| **Phase / since** | M5 / v0.6.0 |
| **Isolation** | in-process (bundled) |
| **Default activation** | auto |
| **Requests** | [[Capability hermes.config.write]], [[Capability hermes.hooks]], [[Capability ui.panel]] |
| **Optional** | — |
| **Spec** | [README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/activation/README.md) |

## What it does

<To write from the module README.>

## Capabilities and why

| Capability | Why it needs it | Without it |
|---|---|---|
| [[Capability hermes.config.write]] | <reason> | <effect> |
| [[Capability hermes.hooks]] | <reason> | <effect> |
| [[Capability ui.panel]] | <reason> | <effect> |

## Turn it on

```bash
hermes-signalbox module grant activation --capability hermes.config.write
hermes-signalbox module grant activation --capability hermes.hooks
hermes-signalbox module grant activation --capability ui.panel
hermes-signalbox module activate activation
```

## Settings (`[modules.activation]`)

<From the README control-surface table.>

## Actions

| Action | Arguments | Model may run | What it does |
|---|---|---|---|
| `inventory` | <args> | <yes/no> | <effect> |
| `presets` | <args> | <yes/no> | <effect> |
| `benchmark` | <args> | <yes/no> | <effect> |
| `history` | <args> | <yes/no> | <effect> |
| `preset_add` | <args> | <yes/no> | <effect> |
| `preset_remove` | <args> | <yes/no> | <effect> |
| `apply` | <args> | <yes/no> | <effect> |
| `restore` | <args> | <yes/no> | <effect> |
| `undo` | <args> | <yes/no> | <effect> |

## Events and audit records

<From [Reference](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md).>

## Security notes

<Summary; link the "Security review" table in the README.>

---
**Sources:** [module README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/activation/README.md) · [module.toml](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/activation/module.toml)
