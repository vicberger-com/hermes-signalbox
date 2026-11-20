# Router (bundled module, M3)

Picks the model for each Hermes LLM request from the resource registry (M2), then fails over to the next
candidate when a request fails. Q&A: [docs/qa/04-m3-prework.md](../../../../docs/qa/04-m3-prework.md).
Bridge: [ADR-0004](../../../../docs/adr/0004-hermes-bridge.md).

## How a request is routed

1. Hermes calls the `llm_request` middleware. If the active provider is not in `providers`, or this turn
   already failed `max_attempts` times, the request passes through unchanged.
2. The request is sized (estimated tokens = characters / 4, tools present, image input) and given a tier:
   T1 up to 2 000 tokens, T2 8 000, T3 32 000, T4 128 000, T5 above.
3. Candidates are `resources.resolve {consumer}` rows of the active provider (`<provider>/<model>` ids), in
   pool order. Only `auto` resources are chosen automatically; a `manual` resource is used only when pinned.
4. A candidate is skipped if it is cooling down, lacks the `tools` or `vision` tag the request needs, or its
   context window is smaller than the estimate plus 1 024 tokens.
5. **Paid gating.** A `paid` resource (pinned or not) is used only if all three hold: the module has the
   `llm.paid` grant, a rule for the consumer allows the request's tier (`rule_add {consumer, min_tier}`), and
   fewer paid requests than the daily budget (`budget {paid_requests_per_day}`, default 0) were made today.
   Every paid choice is audited as `module.router.paid_decision`.
6. Free and self-hosted first, then paid; pool order within each class. A pin wins if it is usable.
7. Only the request's `model` changes (the bridge drops any other change). The decision is stored (time,
   consumer, tier, token estimate, chosen id, cost class, reason; never prompt text; last 1 000 kept).

## When nothing fits

If no candidate fits (or the turn's attempts are used up), passing the request through would send Hermes's
configured model. If that model is a **paid** registry resource and paid is not allowed right now, the router
sends it to any free or self-hosted `auto` resource that is not cooling down instead (size and tag checks
ignored). Only if none exists does the paid model go out, and that is audited as
`module.router.paid_passthrough` (once per resource per day) and counted against the day's paid requests,
so `status` can show more than the budget. The budget is therefore a routing limit, not a hard cap: to stop
turns that would go out paid, set `hard_stop = true`. After the turn's attempts are used up the router stays
free-first even when paid is allowed. A configured model the registry does not know is outside the router's
control: register it, or set Hermes's default to a free model.

## Failover

The router remembers which resource it sent for each Hermes request id. `api_request_error` counts the failure
against the turn and, for HTTP 429, 5xx and connection errors, puts that resource on cool-down for
`cooldown_seconds` (ten times longer for 401, 402, 403 and 404). Other 4xx (400, 413, 422) are caused by the
request, so they count as an attempt but cool nothing down. Hermes's retry then gets the next candidate.
The choice and the paid-budget charge happen under one lock, so concurrent requests cannot overspend.
The router cannot change provider, base URL or credentials: cross-provider routing needs a gateway resource.

## Quotas (M4)

When the `meter` module reports `meter.exhausted` for a quota, the router cools the quota's scope down until
the end of the quota period: one resource (`<provider>/<model>`), a whole provider (`provider:<id>`), or
everything (`all`). `cooldown_clear {id}` lifts it early (use the scope as the id).

This is **steering, not a hard stop**: Hermes middleware can change a request's model but cannot refuse the
request. If the configured model is inside an exhausted scope (or paid while paid is not allowed), the router
sends the request to any free or self-hosted resource outside the scope; if there is none, the request goes
out unchanged and `module.router.quota_passthrough` (or `paid_passthrough`) is audited once per resource and
day.

**Hard stop (M6, opt-in).** With `[modules.router] hard_stop = true` the router also registers a turn gate
(ADR-0006): before each Hermes turn, if the registry knows the configured model, no routed choice exists, and
that model is over an exhausted quota or is paid while paid is not allowed, the turn is blocked with a short
core-written message (`quota exhausted` or `paid model not allowed`; `module.router.hard_stop` audited). A
model the registry does not know, or a registry that is not running, never leads to a block.

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `status`, `explain {tokens, tools, vision}` | yes |
| Action | `pin {consumer, id}`, `auto {consumer}`, `rule_add {consumer, min_tier}`, `rule_remove {consumer}`, `budget {paid_requests_per_day}`, `cooldown_clear {id}` | no |
| Panel | `router.status` | |
| Config | `[modules.router]` `consumer` (`main`), `providers` (`["openrouter"]`), `max_attempts` (3, 1-10), `cooldown_seconds` (60, 5-86400), `hard_stop` (false) | |

Capabilities: `hermes.hooks` and `ui.panel` (required to start); `llm.free`, `llm.paid` (optional in the
manifest, so auto-start does not wait for them, and checked on every request: without `llm.free` no free or
self-hosted resource is chosen, without `llm.paid` no paid one). The router needs the `resources` module running; without it every request passes through.

## State and removal

Tables `rules`, `pins`, `cooldowns`, `spend` (paid requests per day), `kv`, `decisions`. Removed with the module
unless `keep_data`.

## Security review (M3 gate)

Reviewed 2026-11-20 by a fresh subagent with the M3 diff and the threat table; findings checked against the
code and the Hermes v0.23.2 sources.

| Finding | Disposition |
|---|---|
| (high) Failover cooled the wrong resource: Hermes's `api_request_error` carries the sent kwargs under `request.body` and the configured model at the top level | **Fixed.** The router maps request id to the resource it sent; `request.body.model` is the fallback. Tests use the real event shape |
| (high) A paid configured model bypassed the paid gate when the router passed a request through | **Fixed.** Falls back to any free or self-hosted resource; a remaining paid pass-through is audited. Unknown models documented as outside the gate |
| (medium) In-place mutation of shared nested objects passed the model-only check | **Fixed.** Modules get deep copies; only `model` is adopted; type-strict comparison (no custom `__eq__`) |
| (medium) No time bound on module callbacks | **Fixed.** Worker threads, 2 s timeout, `module.hook_timeout` audit |
| (medium) Paid budget check and charge were not atomic | **Fixed.** One lock around choice and charge |
| (low) 400/413/422 cooled resources down | **Fixed.** Attempt only |
| (low) `ctx.call` needs no capability | **Accepted, documented** (ADR-0004): read-only actions must return no secret or sensitive data; the existing ones return metadata only |

**Delegated children (M7).** Requests from a subagent started by a worker role (ADR-0007) are routed within
that role's consumer `subagent:<role>`, with paid rules, budget, quotas and failover; `free_only` children never
get a paid model. `explain {consumer}` answers for any consumer, such as `subagent:<role>`.
