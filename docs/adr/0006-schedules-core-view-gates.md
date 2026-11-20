# ADR-0006: Module schedules, core view and turn gates

Status: accepted, 2026-11-20. Phase: M6. Q&A: [07-m6-prework.md](../qa/07-m6-prework.md) question 10.

## Decision

1. **`schedule` (`ctx.schedule`).** `every(name, seconds, fn)` (10 s to 1 day) adds a time trigger
   `<module>.<name>` to the core scheduler, which runs on the host tick, skips a run while the previous one is
   running, counts failures, and removes a module's triggers when it stops. `cancel(name)`, `stats(name)`.
2. **`core.read` (`ctx.core`).** Read-only: `modules()` (id, status, mode, error) and `verify_audit()`
   (ok, records, first bad record, reason). Nothing that changes state.
3. **Turn gates.** A module with `hermes.hooks` and `gate:pre_llm_call` in `contributes.hooks` registers
   `ctx.hermes_gate(fn)`. Before each Hermes turn the adapter runs gates on metadata only (ADR-0004
   decision 6); the first non-empty reason blocks the turn with `[switchyard/<module>] <reason>` (one line,
   at most 300 characters), audited as `module.gate_blocked`. A gate that raises or times out does **not**
   block (fail open, audited), so a bug cannot stop every turn.

## Consequences

- The supervisor and later modules run on Switchyard's own tick instead of Hermes idle tasks (hours apart).
- Hard limits are possible but opt-in per module; the router uses a gate only when `hard_stop = true`.
