# ADR-0013: Router deadline fails closed

Status: accepted, 2026-11-20. Phase: H1. Q&A: [15-h1-prework.md](../qa/15-h1-prework.md) question 3.
Amends [ADR-0004](0004-hermes-bridge.md) (bridge) and the M3 router.

## Context

Hermes runs `llm_request` middleware synchronously before each provider request. Read in the installed
v0.23.2 source (`hermes_cli/middleware.py`, `agent/turn_api_request.py`): middleware can replace the request
but cannot refuse it; if middleware raises, Hermes logs a warning and sends the request unmodified. The
bridge (ADR-0004) bounds every module callback by a 2 s deadline, so a route that is not ready in time leaves
the configured model in place, and the route kept running in the background with nothing to stop its side
effects. The state store waits up to 5 s for a SQLite lock, longer than the bridge deadline.

## Decision

1. **Bridge: fallback and claim.** `ctx.hermes_middleware(kind, fn, fallback=None)`. When `fn` misses the
   deadline or raises, the bridge calls `fallback(request, context)` on a separate per-module pool, with the
   same deadline and the same model-only rule. `fn` receives `context["claim"]`, a callable: it returns True
   (and the bridge then waits one more deadline for the result) only if the bridge has not yet given up. A
   middleware must claim before any side effect; a late call gets False and must not commit.
2. **State store: wait budgets.** `StateStore.deadline(seconds)` / `ModuleState.deadline(seconds)` bounds the
   total time a thread waits, inside the block, for the store lock and for SQLite locks held by other
   processes; a statement that would wait longer raises `StateError` ("busy"). The store-wide busy wait (5 s)
   is unchanged for every other caller. The router routes inside a 1 s budget.
3. **Router: fail closed.** `route_timeout` is the router's fallback. It uses memory only (no store, no
   audit write; its records are written by the next route) and the candidates remembered from the last
   successful registry answer for the consumer (kept 10 minutes, replaced on every answer, cool-downs
   applied). In order:
   1. The configured model is a known paid resource and a free or self-hosted `auto` candidate is known: send
      that (`module.router.timeout_fallback`, names only). Paid is not considered at all on this path.
   2. Otherwise the configured model goes out. If it is a known paid resource it is charged at once as a paid
      pass-through (`module.router.timeout_passthrough`); with `hard_stop` on, the turn gate also blocks the
      next turn (code `route_timeout`).
   3. If nothing was known yet, the model is settled by the next route: charged then if the registry says it is
      paid (`module.router.timeout_charged`).
4. **Late results.** A route that is too late (claim refused) writes no spend row and no request-to-resource
   entry for its own choice; it only settles what the fallback left. A route that runs past its own budget
   while the bridge still waits raises, so the fallback answers at once.
5. **Cool-downs (H1 C-4).** A cool-down write never shortens an existing one; an error cool-down never
   replaces an active quota reason.
6. **Sizing (H1 C-8).** The router sizes every text-bearing request key (`messages`, `input`, `system`,
   `instructions`, `prompt`, `contents`); a request with none of them is an unknown shape and gets tier T5.

## Consequences

- A paid configured model is never both sent and uncharged, whatever the route's speed.
- The fallback can send a free model whose fit was checked against remembered data, up to 10 minutes old.
- Hard stop blocks one turn after a slow route let a paid model through; the request itself could not be
  stopped (point 1 of the context).
- Not changed here: audit writes on the Hermes thread still anchor in `state.db` with the store-wide wait (H1
  WP8, finding C-2 area). Hermes also has `llm_execution` middleware, which wraps the provider call and could
  refuse it; using it would be a new feature and is out of H1 scope.
