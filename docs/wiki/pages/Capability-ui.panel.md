# Capability ui.panel

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Show panels and status in the CLI and the dashboard.

**Risk:** low

## How it is enforced

Panels return plain data; the core renders it.

## Requested by

| Module | Required or optional | Used for |
|---|---|---|
| [[Module secrets]] | required | <use> |
| [[Module resources]] | required | <use> |
| [[Module router]] | required | <use> |
| [[Module meter]] | required | <use> |
| [[Module activation]] | required | <use> |
| [[Module supervisor]] | required | <use> |
| [[Module workers]] | required | <use> |
| [[Module trimmer]] | required | <use> |
| [[Module inbox]] | required | <use> |
| [[Module scanner]] | required | <use> |
| [[Module offload]] | required | <use> |
| [[Module updates]] | required | <use> |

## Granting advice

<To write.>

## Related

- [[Capabilities]]

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/capabilities.py) · [REFERENCE.md](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md)
