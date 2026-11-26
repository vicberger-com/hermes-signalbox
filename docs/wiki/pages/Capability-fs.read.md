# Capability fs.read

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Read files the operator points it at, as bounded JSON or text, through the file broker.

**Risk:** medium

## How it is enforced

FsBroker: size caps, regular files only, every read audited (`fs.read`).

## Requested by

| Module | Required or optional | Used for |
|---|---|---|
| [[Module resources]] | required | <use> |
| [[Module meter]] | optional | <use> |

## Granting advice

<To write.>

## Related

- [[Capabilities]]

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/capabilities.py) · [REFERENCE.md](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md)
