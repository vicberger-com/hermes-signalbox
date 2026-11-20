# ADR-0006: Module schedules, core view and turn gates

Status: accepted, 2026-11-20. Phase: M6. Q&A: [07-m6-prework.md](../qa/07-m6-prework.md) question 10.

## Decision

1. **`schedule` (`ctx.schedule`).** `every(name, seconds, fn)` (10 s to 1 day) adds a time trigger
   `<module>.<name>` to the core scheduler. Jobs run on the module's own worker thread, at most 5 s are
   waited for (`module.job_timeout`), a job still running is skipped rather than stacked, and the core lock is
   not held while jobs run, so a slow job cannot stall the tick or the control plane. A module's triggers are
   removed when it stops. `cancel(name)`, `stats(name)`.
2. **`core.read` (`ctx.core`).** Read-only: `modules()` (id, status, mode, error class) and `verify_audit()`
   (ok, records, first bad record, reason), cached for 60 s because a full scan holds the audit lock.
3. **Turn gates.** A module with `hermes.hooks` and `gate:pre_llm_call` in `contributes.hooks` registers
   `ctx.hermes_gate(fn)`. Before each Hermes turn the adapter runs gates on metadata only (ADR-0004
   decision 6). A gate returns `None` or a reason **code** (`[a-z][a-z0-9_]{0,39}`); the first code blocks the
   turn with a sentence the core writes (module id and code). Hermes stores the block message as the
   assistant's reply, so module-written text must never reach it (M6 review). A gate that raises, times out
   or returns anything else does **not** block (fail open, audited), so a bug cannot stop every turn.
4. **Isolation.** Each module's hook, middleware and gate calls use that module's own small worker pool, so a
   module whose calls hang starves only itself.
5. **Revocation.** Revoking a required (non-optional) capability from an active module deactivates it, which
   removes its hooks, gates, middleware and jobs. Optional capabilities are checked at run time.

## Consequences

- The supervisor and later modules run on Switchyard's own tick instead of Hermes idle tasks (hours apart).
- Hard limits are possible but opt-in per module; the router uses a gate only when `hard_stop = true`.
