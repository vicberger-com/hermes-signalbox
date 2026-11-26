# Capability notify

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Send operator notifications (to the inbox and dashboard).

**Risk:** low

## How it is enforced

NotifyBroker (ADR-0009): severity levels, capped and redacted text, audited; nothing leaves the machine.

## Requested by

| Module | Required or optional | Used for |
|---|---|---|
| [[Module scanner]] | optional | <use> |
| [[Module updates]] | optional | <use> |

## Granting advice

<To write.>

## Related

- [[Capabilities]]

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/capabilities.py) · [REFERENCE.md](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md)
