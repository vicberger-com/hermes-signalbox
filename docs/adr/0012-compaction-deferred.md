# ADR-0012: Compaction engine replacement deferred past 1.0

Status: accepted, 2026-11-20. Phase: R1. Q&A: [14-r1-prework.md](../qa/14-r1-prework.md) question 2.

## Context

M8 (token economy) built deletion-only output trimming (ADR-0008) and deferred replacing Hermes's context
compaction engine. Compaction decides what the model remembers from earlier turns: a replacement that drops the
wrong facts silently changes behaviour, and measuring that needs task-level evaluations this project does not
have yet.

## Decision

Switchyard 1.0 does not replace or hook Hermes compaction. Token savings in 1.0 come from output trimming (M8)
and routing to free or local resources (M3, M7, M11).

## Consequences

- A future ADR may add a compaction module behind its own capability, with an evaluation suite comparing task
  success with and without it before it can be enabled by default.
