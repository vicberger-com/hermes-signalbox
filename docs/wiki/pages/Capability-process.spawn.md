# Capability process.spawn

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Run external programs with a fixed argument list.

**Risk:** high

## How it is enforced

ProcessBroker: no shell, scrubbed environment, output to files with a cap, whole process tree killed on timeout, audited.

## Requested by

| Module | Required or optional | Used for |
|---|---|---|
| [[Module secrets]] | required | <use> |
| [[Module scanner]] | required | <use> |
| [[Module offload]] | optional | <use> |

## Granting advice

<To write.>

## Related

- [[Capabilities]]

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/capabilities.py) · [REFERENCE.md](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/REFERENCE.md)
