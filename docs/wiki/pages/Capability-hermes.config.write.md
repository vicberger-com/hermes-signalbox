# Capability hermes.config.write

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Change allow-listed Hermes config keys (skills.disabled).

**Risk:** high

## How it is enforced

ConfigWriter (ADR-0005): allow-listed keys only, backup before every write, audited, rolled back on failure.

## Requested by

| Module | Required or optional | Used for |
|---|---|---|
| [[Module activation]] | required | <use> |

## Granting advice

<To write.>

## Related

- [[Capabilities]]

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/capabilities.py) · [REFERENCE.md](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md)
