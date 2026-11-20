# Capability core.read

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Read module states, verify the audit chain, read update checks, and subscribe to core events.

**Risk:** medium

## How it is enforced

CoreView (ADR-0006): read-only, cached, update checks single-flight and cached.

## Requested by

| Module | Required or optional | Used for |
|---|---|---|
| [[Module supervisor]] | required | <use> |
| [[Module inbox]] | required | <use> |
| [[Module updates]] | required | <use> |

## Granting advice

<To write.>

## Related

- [[Capabilities]]

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/capabilities.py) · [REFERENCE.md](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/REFERENCE.md)
