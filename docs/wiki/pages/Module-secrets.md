# Module secrets

> **Type:** module · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

| | |
|---|---|
| **Does** | Secret backends (OS stores, Vaultwarden, development env), age and expiry by name, rotation. |
| **Phase / since** | M1 / v0.2.0 |
| **Isolation** | in-process (bundled) |
| **Default activation** | auto |
| **Requests** | [[Capability secrets.read]], [[Capability process.spawn]], [[Capability ui.panel]] |
| **Optional** | — |
| **Spec** | [README](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/modules/secrets/README.md) |

## What it does

<To write from the module README.>

## Capabilities and why

| Capability | Why it needs it | Without it |
|---|---|---|
| [[Capability secrets.read]] | <reason> | <effect> |
| [[Capability process.spawn]] | <reason> | <effect> |
| [[Capability ui.panel]] | <reason> | <effect> |

## Turn it on

```bash
switchyard module grant secrets --capability secrets.read
switchyard module grant secrets --capability process.spawn
switchyard module grant secrets --capability ui.panel
switchyard module activate secrets
```

## Settings (`[modules.secrets]`)

<From the README control-surface table.>

## Actions

| Action | Arguments | Model may run | What it does |
|---|---|---|---|
| `status` | <args> | <yes/no> | <effect> |
| `rotate` | <args> | <yes/no> | <effect> |
| `expire` | <args> | <yes/no> | <effect> |

## Events and audit records

<From [Reference](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/REFERENCE.md).>

## Security notes

<Summary; link the "Security review" table in the README.>

---
**Sources:** [module README](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/modules/secrets/README.md) · [module.toml](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/modules/secrets/module.toml)
