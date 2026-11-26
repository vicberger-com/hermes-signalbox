# Module inbox

> **Type:** module · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

| | |
|---|---|
| **Does** | Collects operator notifications and alerts (supervisor, meter, workers, failed modules) for the dashboard; nothing leaves the machine. |
| **Phase / since** | M9 / v0.10.0 |
| **Isolation** | in-process (bundled) |
| **Default activation** | auto |
| **Requests** | [[Capability core.read]], [[Capability ui.panel]] |
| **Optional** | — |
| **Spec** | [README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/inbox/README.md) |

## What it does

<To write from the module README.>

## Capabilities and why

| Capability | Why it needs it | Without it |
|---|---|---|
| [[Capability core.read]] | <reason> | <effect> |
| [[Capability ui.panel]] | <reason> | <effect> |

## Turn it on

```bash
hermes-signalbox module grant inbox --capability core.read
hermes-signalbox module grant inbox --capability ui.panel
hermes-signalbox module activate inbox
```

## Settings (`[modules.inbox]`)

<From the README control-surface table.>

## Actions

| Action | Arguments | Model may run | What it does |
|---|---|---|---|
| `list` | <args> | <yes/no> | <effect> |
| `ack` | <args> | <yes/no> | <effect> |
| `ack_all` | <args> | <yes/no> | <effect> |

## Events and audit records

<From [Reference](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md).>

## Security notes

<Summary; link the "Security review" table in the README.>

---
**Sources:** [module README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/inbox/README.md) · [module.toml](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/inbox/module.toml)
