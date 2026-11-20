# Capability schedule

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Run jobs on a timer.

**Risk:** low

## How it is enforced

ScheduleBroker: 10 s to 24 h intervals, one worker per module, time-bounded, skipped runs audited.

## Requested by

| Module | Required or optional | Used for |
|---|---|---|
| [[Module supervisor]] | required | <use> |
| [[Module workers]] | required | <use> |
| [[Module scanner]] | required | <use> |
| [[Module updates]] | required | <use> |

## Granting advice

<To write.>

## Related

- [[Capabilities]]

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/capabilities.py) · [REFERENCE.md](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/REFERENCE.md)
