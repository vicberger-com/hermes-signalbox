# Capability hermes.output

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Shorten terminal and tool output before the model reads it (deletion only).

**Risk:** medium

## How it is enforced

Transforms (ADR-0008): modules return kept line ranges; must-keep lines (errors, exit codes, paths, auth failures) are never dropped; the core adds the omission markers.

## Requested by

| Module | Required or optional | Used for |
|---|---|---|
| [[Module trimmer]] | required | <use> |

## Granting advice

<To write.>

## Related

- [[Capabilities]]

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/capabilities.py) · [REFERENCE.md](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/REFERENCE.md)
