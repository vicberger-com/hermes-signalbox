# Capability hermes.hooks

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Observe Hermes events (requests, responses, subagents) and register gates and middleware.

**Risk:** high

## How it is enforced

Bridge (ADR-0004, ADR-0006): metadata-only views, time-bounded handlers, failures isolated; gates return codes and the core writes the message.

## Requested by

| Module | Required or optional | Used for |
|---|---|---|
| [[Module router]] | required | <use> |
| [[Module meter]] | required | <use> |
| [[Module activation]] | required | <use> |
| [[Module workers]] | required | <use> |

## Granting advice

<To write.>

## Related

- [[Capabilities]]

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/capabilities.py) · [REFERENCE.md](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md)
