# ADR-0004: Hermes hook bridge and read-only cross-module calls

Status: accepted, 2026-11-19. Phase: M3. Q&A: [04-m3-prework.md](../qa/04-m3-prework.md) question 10.

## Context

The router (M3), metering (M4) and later modules must observe Hermes LLM traffic and, for routing, change the
model of a request. Hermes plugins register hooks and middleware once, at `register(ctx)`; Switchyard modules
start and stop later and must stay isolated from each other and from Hermes. The router also needs the
registry's candidate list (M2) without reading another module's tables.

## Decision

1. **Bridge.** The core keeps a `HermesBridge` (no Hermes import). A module granted `hermes.hooks` registers
   `ctx.hermes_hook(name, fn)` or `ctx.hermes_middleware(kind, fn)` for names declared in `contributes.hooks`
   (`<hook>` or `middleware:<kind>`). Registrations end when the module stops.
2. **Adapter.** `switchyard.hermes` registers, once, one Hermes callback per supported observer hook
   (`pre_llm_call`, `pre_api_request`, `post_api_request`, `api_request_error`, `post_llm_call`, `subagent_stop`) and the
   `llm_request` middleware, each forwarding to the bridge in the hosting process.
3. **Isolation.** Every module callback gets a deep copy of the hook arguments and runs on a worker thread
   with a 2 s timeout (`module.hook_timeout`); exceptions are caught and audited (`module.hook_failed`, class
   name only); the turn continues either way. Observer return values are ignored.
4. **Middleware limits.** An `llm_request` callback returns `None` (no change) or a new request dict. The
   bridge accepts it only if it differs from the input in the `model` key alone (type-strict comparison) and
   the new model is a non-empty string; anything else is discarded and audited (`module.middleware_rejected`).
   Only the `model` value is adopted into the live request, so base URL, credentials, messages and tools can
   never be changed by a module.
5. **Cross-module calls.** `ctx.call(module_id, action, args)` runs another module's **read-only** action
   through the same validation as `module action`, with actor `module:<caller>`. Writes across modules are not
   possible. No capability is needed, so **read-only actions must return no secret or sensitive data**
   (they are also visible to the Hermes model).

6. **Metadata only** (amended in M4, Q&A 05 question 10). Observer hooks hand modules scalar fields, the
   numeric `usage` buckets and model names from `request`, `response` and `error`; message text, conversation
   history, tool traces and raw SDK objects never reach a module. `subagent_stop` is also forwarded.

## Consequences

- Modules get Hermes traffic without each one registering with Hermes, and a failing module cannot break a turn.
- Routing is limited to choosing among models of the active provider; cross-provider routing would need a
  gateway resource running as its own process.
