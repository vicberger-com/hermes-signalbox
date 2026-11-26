# Capability llm.paid

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Let the router or a worker role use paid models, subject to rules and a daily budget.

**Risk:** high

## How it is enforced

Router paid gating: grant + consumer rule + budget; every paid choice audited; optional hard stop.

## Requested by

| Module | Required or optional | Used for |
|---|---|---|
| [[Module router]] | optional | <use> |
| [[Module workers]] | optional | <use> |

## Granting advice

<To write.>

## Related

- [[Capabilities]]

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/capabilities.py) · [REFERENCE.md](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md)
