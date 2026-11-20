# Hermes Switchyard

> **Type:** home · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** current

A security-first control plane for [Hermes Agent](https://github.com/NousResearch/hermes-agent). A small core and
twelve snap-on modules decide which skills, plugins, models, agents and tools are active, what they may do, what
they cost, and what happens when they fail. Nothing a module does is allowed until you grant it, and every change
is written to a hash-chained audit log. Hermes can operate all of it; so can a person.

## Start here

| If you want to | Go to |
|---|---|
| Install and run it | [[Getting started]] |
| Understand what it does | [[Overview]] |
| Judge whether it is safe enough | [[Security model]] |
| Pick how to run it | [[Deployment profiles]] |
| See every module | [[Module catalog]] |
| Know what a grant allows | [[Capabilities]] |
| Fix a problem | [[Troubleshooting]] |
| Write a module | [[Building a module]] |

## Objectives, in priority order

1. Security · 2. Utility · 3. Open source · 4. Speed and capacity · 5. Size and clarity. Every tie is broken in
this order.

## Status

**v1.0.0** (2026-11-20): [[Release 1.0.0]] · [Backlog board](https://github.com/orgs/vicberger-com/projects/1) ·
[Report a vulnerability](https://github.com/vicberger-com/hermes-switchyard/security/advisories/new)

---
**Sources:** [README](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/README.md) · [DESIGN.md](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/DESIGN.md)
