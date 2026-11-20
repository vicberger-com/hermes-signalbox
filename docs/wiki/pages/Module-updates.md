# Module updates

> **Type:** module · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

| | |
|---|---|
| **Does** | Checks git-installed modules against the head of their update channel on a schedule and announces available updates. It never applies one: preview and update are operator commands. |
| **Phase / since** | M12 / v0.13.0 |
| **Isolation** | in-process (bundled) |
| **Default activation** | manual |
| **Requests** | [[Capability schedule]], [[Capability core.read]], [[Capability ui.panel]] |
| **Optional** | [[Capability notify]] |
| **Spec** | [README](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/modules/updates/README.md) |

## What it does

<To write from the module README.>

## Capabilities and why

| Capability | Why it needs it | Without it |
|---|---|---|
| [[Capability schedule]] | <reason> | <effect> |
| [[Capability core.read]] | <reason> | <effect> |
| [[Capability notify]] | <reason> | <effect> |
| [[Capability ui.panel]] | <reason> | <effect> |

## Turn it on

```bash
switchyard module grant updates --capability schedule
switchyard module grant updates --capability core.read
switchyard module grant updates --capability notify
switchyard module grant updates --capability ui.panel
switchyard module activate updates
```

## Settings (`[modules.updates]`)

<From the README control-surface table.>

## Actions

| Action | Arguments | Model may run | What it does |
|---|---|---|---|
| `report` | <args> | <yes/no> | <effect> |
| `check_now` | <args> | <yes/no> | <effect> |

## Events and audit records

<From [Reference](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/REFERENCE.md).>

## Security notes

<Summary; link the "Security review" table in the README.>

---
**Sources:** [module README](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/modules/updates/README.md) · [module.toml](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/modules/updates/module.toml)
