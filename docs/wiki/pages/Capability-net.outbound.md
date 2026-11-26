# Capability net.outbound

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Make HTTP(S) requests to hosts listed in the module's manifest `net_hosts`.

**Risk:** high

## How it is enforced

NetBroker (ADR-0010): manifest host list, no redirects, no proxies, 1 MB out / 4 MB in, total deadline, audited by host and status only.

## Requested by

| Module | Required or optional | Used for |
|---|---|---|
| [[Module offload]] | required | <use> |

## Granting advice

<To write.>

## Related

- [[Capabilities]]

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/capabilities.py) · [REFERENCE.md](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md)
