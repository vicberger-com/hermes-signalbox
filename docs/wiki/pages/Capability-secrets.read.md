# Capability secrets.read

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Use named secrets the manifest declares, by reference; values are resolved at the point of use.

**Risk:** high

## How it is enforced

SecretsBroker: declared names only, values registered with the redactor, results checked by a leak tripwire, every use audited by name.

## Requested by

| Module | Required or optional | Used for |
|---|---|---|
| [[Module secrets]] | required | <use> |

## Granting advice

<To write.>

## Related

- [[Capabilities]]

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/capabilities.py) · [REFERENCE.md](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md)
