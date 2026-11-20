# Deployment profiles

> **Type:** index · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

Ways to run Switchyard. All use the same core and data directory layout; they differ in which process hosts
modules (runs them, their schedules, gates and transforms) and whether the loopback API is on.

| Profile | Fits when |
|---|---|
| [[Deploy Hermes plugin on a workstation]] | One person, Hermes desktop or CLI; modules hosted by the first Hermes session |
| [[Deploy Always-on gateway]] | Hermes gateway runs continuously; it hosts modules, schedules run around the clock |
| [[Deploy Standalone daemon]] | `switchyard api serve` hosts modules and the loopback API without a Hermes session |
| [[Deploy Dashboard enabled]] | Any of the above plus `[api] enabled`; Switchyard tab in the Hermes dashboard |
| [[Deploy Several Hermes processes]] | CLI, desktop and gateway share one data directory; one hosts, the others read and write state |

Capacity defaults come from the host profile (`tiny`, `laptop`, `workstation`, `server`; `[host] profile`).

---
**Sources:** [USER-GUIDE.md](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/USER-GUIDE.md) · [REFERENCE.md](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/REFERENCE.md)
