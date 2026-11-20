# Module resources

> **Type:** module · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

| | |
|---|---|
| **Does** | Catalog of providers, models, endpoints, agents and tools; pools; consumer bindings; reviewed imports. |
| **Phase / since** | M2 / v0.3.0 |
| **Isolation** | in-process (bundled) |
| **Default activation** | auto |
| **Requests** | [[Capability fs.read]], [[Capability ui.panel]] |
| **Optional** | — |
| **Spec** | [README](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/modules/resources/README.md) |

## What it does

<To write from the module README.>

## Capabilities and why

| Capability | Why it needs it | Without it |
|---|---|---|
| [[Capability fs.read]] | <reason> | <effect> |
| [[Capability ui.panel]] | <reason> | <effect> |

## Turn it on

```bash
switchyard module grant resources --capability fs.read
switchyard module grant resources --capability ui.panel
switchyard module activate resources
```

## Settings (`[modules.resources]`)

<From the README control-surface table.>

## Actions

| Action | Arguments | Model may run | What it does |
|---|---|---|---|
| `list` | <args> | <yes/no> | <effect> |
| `show` | <args> | <yes/no> | <effect> |
| `pools` | <args> | <yes/no> | <effect> |
| `resolve` | <args> | <yes/no> | <effect> |
| `import_preview` | <args> | <yes/no> | <effect> |
| `set_state` | <args> | <yes/no> | <effect> |
| `set_priority` | <args> | <yes/no> | <effect> |
| `tag` | <args> | <yes/no> | <effect> |
| `untag` | <args> | <yes/no> | <effect> |
| `pool_create` | <args> | <yes/no> | <effect> |
| `pool_delete` | <args> | <yes/no> | <effect> |
| `pool_add` | <args> | <yes/no> | <effect> |
| `pool_remove` | <args> | <yes/no> | <effect> |
| `bind` | <args> | <yes/no> | <effect> |
| `unbind` | <args> | <yes/no> | <effect> |
| `import_file` | <args> | <yes/no> | <effect> |
| `import_apply` | <args> | <yes/no> | <effect> |
| `import_discard` | <args> | <yes/no> | <effect> |

## Events and audit records

<From [Reference](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/REFERENCE.md).>

## Security notes

<Summary; link the "Security review" table in the README.>

---
**Sources:** [module README](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/modules/resources/README.md) · [module.toml](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/modules/resources/module.toml)
