# Module <id>

> **Type:** module · **Applies to:** v<X.Y.Z> · **Last checked:** <YYYY-MM-DD> · **Status:** draft

| | |
|---|---|
| **Does** | <one line> |
| **Phase / since** | M<n> / v<X.Y.Z> |
| **Isolation** | in-process (bundled) |
| **Default activation** | auto / manual |
| **Requests** | [[Capability <name>]], … |
| **Optional** | [[Capability <name>]] (works without it) |
| **Spec** | [README](https://github.com/vicberger-com/hermes-switchyard/blob/v<X.Y.Z>/src/switchyard/modules/<id>/README.md) |

## What it does

<Three to six sentences on behaviour, from the operator's point of view.>

## Capabilities and why

| Capability | Why it needs it | Without it |
|---|---|---|
| [[Capability <name>]] | <reason> | <effect> |

## Turn it on

```bash
switchyard module grant <id> --capability <name>
switchyard module activate <id>
```

## Settings (`[modules.<id>]`)

| Key | Default | Meaning |
|---|---|---|
| `<key>` | `<default>` | <meaning> |

## Actions

| Action | Arguments | Model may run | What it does |
|---|---|---|---|
| `<name>` | `<args>` | yes / no | <effect> |

## Events and audit records

| Kind | Name | When |
|---|---|---|
| event | `<type>` | <trigger> |
| audit | `module.<id>.<name>` | <trigger> |

## Security notes

<What could go wrong, what limits it, what the operator should watch. Link the module's security review table.>

## Related

- [[<Page>]]

---
**Sources:** [<document>](https://github.com/vicberger-com/hermes-switchyard/blob/v<X.Y.Z>/<path>) · [<document>](<link>)
