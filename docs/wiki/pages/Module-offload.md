# Module offload

> **Type:** module · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

| | |
|---|---|
| **Does** | Sends suitable work to cheaper local resources: JevK5 typed decisions, n8n flows, and (when allowed by name) agent CLIs. Each connector declares license class, hosts and data sent. |
| **Phase / since** | M11 / v0.12.0 |
| **Isolation** | in-process (bundled) |
| **Default activation** | manual |
| **Requests** | [[Capability net.outbound]], [[Capability ui.panel]] |
| **Optional** | [[Capability process.spawn]] |
| **Spec** | [README](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/modules/offload/README.md) |

## What it does

<To write from the module README.>

## Capabilities and why

| Capability | Why it needs it | Without it |
|---|---|---|
| [[Capability net.outbound]] | <reason> | <effect> |
| [[Capability process.spawn]] | <reason> | <effect> |
| [[Capability ui.panel]] | <reason> | <effect> |

## Turn it on

```bash
switchyard module grant offload --capability net.outbound
switchyard module grant offload --capability process.spawn
switchyard module grant offload --capability ui.panel
switchyard module activate offload
```

## Settings (`[modules.offload]`)

<From the README control-surface table.>

## Actions

| Action | Arguments | Model may run | What it does |
|---|---|---|---|
| `connectors` | <args> | <yes/no> | <effect> |
| `run` | <args> | <yes/no> | <effect> |
| `report` | <args> | <yes/no> | <effect> |

## Events and audit records

<From [Reference](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/REFERENCE.md).>

## Security notes

<Summary; link the "Security review" table in the README.>

---
**Sources:** [module README](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/modules/offload/README.md) · [module.toml](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/modules/offload/module.toml)
