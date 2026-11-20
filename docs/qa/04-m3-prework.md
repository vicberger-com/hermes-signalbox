# Pre-work Q&A: M3 router and failover

Date: 2026-11-19. Previous phase: M2, tag v0.3.0.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| M2 | `resources.resolve {consumer}` gives a consumer's enabled resources in order, with cost class, tags, limits | The router's candidate list |
| M2 review | Model-reachable inputs must not choose files or widen access | Pin and auto commands are human-only |
| ADR-0002 | Module actions, read-only flag | Router status is read-only; pin/auto/rules are human-only |
| M0 | `hermes.hooks` is in the capability vocabulary but nothing bridges module code to Hermes hooks | Needed (question 10) |

## 2. Research record

| Topic | Source (URL, commit or version, date read) | Finding |
|---|---|---|
| Hermes hooks | Hermes v0.23.2 `hermes_cli/hooks.py`, `agent/turn_api_request.py`, `agent/turn_context.py` (2026-11-19) | `pre_api_request`, `post_api_request`, `api_request_error` are observers (return ignored). `pre_llm_call` may return context or a block; it cannot change the model |
| Hermes middleware | `hermes_cli/middleware.py`, `agent/turn_api_call.py` | `register_middleware("llm_request", cb)` may return `{"request": {...}}` to replace the provider kwargs (including `model`). `llm_execution` wraps the call, but `next_call` is single-use: no retries inside middleware. Context carries `provider`, `base_url`, `model`, `api_call_count` |
| Hermes retries and fallback | `fallback_providers` in `config.yaml`; retry loop increments `api_call_count` | Failover across attempts is possible: record the failure in `api_request_error`, pick another candidate on the next attempt. Switching provider (base URL, credentials) per request is not possible from a plugin; switching `model` within the active provider is (for example among OpenRouter models) |
| Upstream routers | open-world-project/model-router, Waylish/hermes-smart-model-routing, Zelray/hermes-model-router, Shaf2665/Hermes-router, 0xzr/freellmpool; gateways freellmapi, OmniRoute, 9router | Read as design references only (licenses vary; several missing). Common pattern: tier classification from request features, free-first ordering, cooldown on 429, gateway as one resource. Nothing copied |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Smallest scope? | (a) deterministic decision engine + Hermes `llm_request` middleware that rewrites `model` within the active provider + failover across Hermes retries; (b) also cross-provider switching | (a). Cross-provider switching would need the plugin to hold provider credentials and clients; out of scope until a gateway resource (an external process) is added | default accepted |
| 2 | Capabilities | `hermes.hooks`, `hermes.tools`, `llm.free`, `llm.paid`, `net.outbound` | `hermes.hooks` (middleware and observers), `llm.free`, `llm.paid`, `ui.panel`. The router never calls a provider itself, so no `net.outbound`. `llm.paid` must be granted before any paid candidate is chosen, in addition to a matching rule | default accepted |
| 3 | Reuse, adapt or write? | | Write our own; the routers above are references | default accepted |
| 4 | New dependencies? | | None | default accepted |
| 5 | Security | | Threat table below | default accepted |
| 6 | State; uninstall | | Module tables: `rules` (paid gating), `cooldowns` (resource -> until, reason), `pins` (consumer -> resource), `decisions` (last 1000, no prompt text), `spend` (paid requests per day). Removal drops them unless `keep_data` | default accepted |
| 7 | Control surface | | Read-only actions `status`, `explain {consumer, tier}`. Human-only: `pin {consumer, id}`, `auto {consumer}`, `rule_add`, `rule_remove`, `budget {paid_requests_per_day}`. Panel `router.status`. Config `[modules.router]`: `consumer` (default `main`), `max_attempts` (3), `cooldown_seconds` (60), `providers` (provider ids routed, default `openrouter`) | default accepted |
| 8 | Logs, metrics, alerts | | Log stream `router`; audit `module.router.paid_decision` for every paid choice, plus rule and pin changes | default accepted |
| 9 | Update and rollback | | Bundled | default accepted |
| 10 | Core contract change? | (a) ADR-0004: Hermes bridge (`ctx.hermes_middleware(kind, fn)`, `ctx.hermes_hook(name, fn)`) and read-only cross-module calls (`ctx.call(module, action, args)`); (b) router reads the registry tables directly | (a). The adapter registers one Hermes callback per hook and middleware kind at startup and forwards to active modules with error isolation; a failing module never breaks the Hermes turn. Cross-module calls are limited to read-only actions, so a module cannot change another module's state | default accepted |
| 11 | Operator input? | | None. Paid routing stays off until the operator grants `llm.paid` and adds a rule | default accepted |

### Threats and tests (question 5)

| Threat | Control | Test |
|---|---|---|
| Paid model used without approval | Paid candidate only if `llm.paid` granted, a rule matches, and the daily paid budget remains; otherwise skipped | `test_paid_never_without_rule_and_budget` |
| Router failure breaks every Hermes turn | Bridge isolates exceptions and time; on any router error the request passes through unchanged | `test_router_error_passes_request_through` |
| Request rewritten to another provider or URL | Middleware may change only `model`, only to a resource id of the active provider | `test_rewrite_limited_to_model` |
| Prompt text stored | Decisions keep consumer, tier, chosen id, reason, sizes; never messages | `test_decisions_hold_no_prompt_text` |
| Model pins itself to an expensive resource | `pin`, `auto`, rules and budget are human-only actions | `test_model_cannot_pin` |
| Endless retries | Failover stops after `max_attempts`; cooldowns expire | `test_failover_bounded` |

## 4. Acceptance tests (written before code)

- [ ] Deterministic routing per tier (T1 to T5) over a fixed candidate list.
- [ ] Paid never used without a matching rule, the `llm.paid` grant and remaining budget.
- [ ] Failover within a bounded number of attempts; a failed resource cools down.
- [ ] Every paid decision audited.

## 5. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
