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

## Failover

`api_request_error` puts the failed resource on cool-down for `cooldown_seconds` (ten times longer for HTTP
401, 402, 403 and 404) and counts the failure against the turn. Hermes's retry then gets the next candidate.
The router cannot change provider, base URL or credentials: cross-provider routing needs a gateway resource.

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `status`, `explain {tokens, tools, vision}` | yes |
| Action | `pin {consumer, id}`, `auto {consumer}`, `rule_add {consumer, min_tier}`, `rule_remove {consumer}`, `budget {paid_requests_per_day}`, `cooldown_clear {id}` | no |
| Panel | `router.status` | |
| Config | `[modules.router]` `consumer` (`main`), `providers` (`["openrouter"]`), `max_attempts` (3, 1-10), `cooldown_seconds` (60, 5-86400) | |

Capabilities: `hermes.hooks` (required to start), `llm.free`, `llm.paid` (optional; paid stays off without
it), `ui.panel`. The router needs the `resources` module running; without it every request passes through.

## State and removal

Tables `rules`, `pins`, `cooldowns`, `spend` (paid requests per day), `kv`, `decisions`. Removed with the module
unless `keep_data`.
