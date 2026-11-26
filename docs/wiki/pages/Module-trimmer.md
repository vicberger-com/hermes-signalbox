# Module trimmer

> **Type:** module · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

| | |
|---|---|
| **Does** | Shortens long terminal and tool output before it reaches the model: repeated lines, noisy middles; errors, exit codes and paths are always kept. |
| **Phase / since** | M8 / v0.9.0 |
| **Isolation** | in-process (bundled) |
| **Default activation** | manual |
| **Requests** | [[Capability hermes.output]], [[Capability ui.panel]] |
| **Optional** | — |
| **Spec** | [README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/trimmer/README.md) |

## What it does

<To write from the module README.>

## Capabilities and why

| Capability | Why it needs it | Without it |
|---|---|---|
| [[Capability hermes.output]] | <reason> | <effect> |
| [[Capability ui.panel]] | <reason> | <effect> |

## Turn it on

```bash
hermes-signalbox module grant trimmer --capability hermes.output
hermes-signalbox module grant trimmer --capability ui.panel
hermes-signalbox module activate trimmer
```

## Settings (`[modules.trimmer]`)

<From the README control-surface table.>

## Actions

| Action | Arguments | Model may run | What it does |
|---|---|---|---|
| `report` | <args> | <yes/no> | <effect> |
| `preview` | <args> | <yes/no> | <effect> |

## Events and audit records

<From [Reference](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md).>

## Security notes

<Summary; link the "Security review" table in the README.>

---
**Sources:** [module README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/trimmer/README.md) · [module.toml](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/trimmer/module.toml)
