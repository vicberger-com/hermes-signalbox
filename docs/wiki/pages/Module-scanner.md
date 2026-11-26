# Module scanner

> **Type:** module · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

| | |
|---|---|
| **Does** | Runs external security scanners (gitleaks, bandit, pip-audit, osv-scanner, semgrep, trivy) on a schedule; findings to the store, dashboard and alerts; failures are findings too. |
| **Phase / since** | M10 / v0.11.0 |
| **Isolation** | in-process (bundled) |
| **Default activation** | manual |
| **Requests** | [[Capability process.spawn]], [[Capability schedule]], [[Capability ui.panel]] |
| **Optional** | [[Capability notify]] |
| **Spec** | [README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/scanner/README.md) |

## What it does

<To write from the module README.>

## Capabilities and why

| Capability | Why it needs it | Without it |
|---|---|---|
| [[Capability process.spawn]] | <reason> | <effect> |
| [[Capability schedule]] | <reason> | <effect> |
| [[Capability notify]] | <reason> | <effect> |
| [[Capability ui.panel]] | <reason> | <effect> |

## Turn it on

```bash
hermes-signalbox module grant scanner --capability process.spawn
hermes-signalbox module grant scanner --capability schedule
hermes-signalbox module grant scanner --capability notify
hermes-signalbox module grant scanner --capability ui.panel
hermes-signalbox module activate scanner
```

## Settings (`[modules.scanner]`)

<From the README control-surface table.>

## Actions

| Action | Arguments | Model may run | What it does |
|---|---|---|---|
| `report` | <args> | <yes/no> | <effect> |
| `findings` | <args> | <yes/no> | <effect> |
| `run_now` | <args> | <yes/no> | <effect> |

## Events and audit records

<From [Reference](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md).>

## Security notes

<Summary; link the "Security review" table in the README.>

---
**Sources:** [module README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/scanner/README.md) · [module.toml](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/scanner/module.toml)
