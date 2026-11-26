# Module router

> **Type:** module · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** current

| | |
|---|---|
| **Does** | Picks the model for each Hermes request from the registry: free first, paid only by rule and budget, failover with cool-down |
| **Phase / since** | M3 / v0.4.0 |
| **Isolation** | in-process (bundled) |
| **Default activation** | auto |
| **Requests** | [[Capability hermes.hooks]], [[Capability ui.panel]] |
| **Optional** | [[Capability llm.free]], [[Capability llm.paid]] |
| **Needs running** | [[Module resources]] (without it every request passes through unchanged) |
| **Spec** | [README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/router/README.md) |

## What it does

For each Hermes LLM request the router estimates its size (characters / 4, tools, images), gives it a tier
(T1 up to 2 000 tokens … T5 above 128 000) and chooses a resource from the registry's pool for the consumer:
free and self-hosted first, then paid, in pool order. Only the request's `model` changes. When a request fails
it counts an attempt and, for 429, 5xx and connection errors, cools that resource down so Hermes's retry gets
the next candidate. After the turn's attempts are used up it stays free-first.

If nothing fits, Hermes's configured model goes out unchanged. If that model is paid while paid is not allowed,
the router substitutes any free `auto` resource; only if none exists does the paid model pass through, audited
and counted against the day's budget. With `hard_stop = true` such turns are blocked instead.

## Capabilities and why

| Capability | Why it needs it | Without it |
|---|---|---|
| [[Capability hermes.hooks]] | The `llm_request` middleware and the error and response hooks | Does not start |
| [[Capability ui.panel]] | `router.status` panel | Does not start |
| [[Capability llm.free]] | Choose free and self-hosted resources | No free resource is chosen |
| [[Capability llm.paid]] | Choose paid resources (also needs a rule and a budget) | No paid resource is chosen |

## Turn it on

```bash
hermes-signalbox module grant router --capability hermes.hooks
hermes-signalbox module grant router --capability ui.panel
hermes-signalbox module grant router --capability llm.free
hermes-signalbox module activate router
```

> **Security:** granting `llm.paid` alone spends nothing: paid use also needs `rule_add` for the consumer and a
> daily `budget` above 0. The budget limits routing; to block turns that would go out paid anyway, set
> `hard_stop = true`.

## Settings (`[modules.router]`)

| Key | Default | Meaning |
|---|---|---|
| `consumer` | `main` | Consumer whose pool is used for the main session |
| `providers` | `["openrouter"]` | Hermes providers the router acts on; others pass through |
| `max_attempts` | `3` (1-10) | Failed attempts per turn before routing stops choosing |
| `cooldown_seconds` | `60` (5-86400) | Cool-down after 429/5xx; ten times longer for 401, 402, 403, 404 |
| `hard_stop` | `false` | Block turns whose configured model is ruled out and nothing else fits |

## Actions

| Action | Arguments | Model may run | What it does |
|---|---|---|---|
| `status` | — | yes | Paid use today, budget, rules, pins, cool-downs, recent decisions |
| `explain` | `tokens`, `tools`, `vision` | yes | What would be chosen for a request of that shape, and why |
| `pin` / `auto` | `consumer`, `id` / `consumer` | no | Pin a resource for a consumer / return to automatic choice |
| `rule_add` / `rule_remove` | `consumer`, `min_tier` / `consumer` | no | Allow paid from a tier upwards for a consumer |
| `budget` | `paid_requests_per_day` | no | Daily paid-request budget (default 0) |
| `cooldown_clear` | `id` | no | End a resource's cool-down |

## Events and audit records

| Kind | Name | When |
|---|---|---|
| event (subscribes) | `meter.exhausted` | Cools the quota's scope down until the period ends |
| audit | `module.router.paid_decision` | Every paid choice or counted paid pass-through |
| audit | `module.router.paid_passthrough`, `module.router.quota_passthrough` | Ruled-out model went out unchanged (once per resource per day) |
| audit | `module.router.hard_stop` | A turn was blocked |
| audit | `module.router.pin`, `.auto`, `.rule_add`, `.rule_remove`, `.budget` | Operator changes |

## Security notes

The choice and the paid charge happen under one lock, so concurrent requests cannot overspend. The router never
changes provider, base URL or credentials. A model the registry does not know is outside its control and is never
blocked. The model can read `status` and `explain` but cannot change rules, pins or budgets. Review history: the
"Security review" table in the [README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/router/README.md) and R1 findings in
[docs/qa/14-r1-prework.md](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/qa/14-r1-prework.md).

## Related

- [[Module resources]] · [[Module meter]] · [[Capability llm.paid]] · [[Decision ADR-0006]]

---
**Sources:** [router README](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/router/README.md) · [router module.toml](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules/router/module.toml) · [ADR-0004](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/adr/0004-hermes-bridge.md)
