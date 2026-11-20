# Pre-work Q&A: M4 metering, quotas and budgets

Date: 2026-11-20. Previous phase: M3, tag v0.4.0.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| M3 retro | Hook payload shapes must come from the Hermes source, and tests must use them | Research record below; tests replay the real `post_api_request` shape |
| M3 | The router consumes registry candidates and cools resources down | It also acts on `meter.exhausted` (question 10) |
| M3 review | Deep copies of hook arguments; a raw SDK object in a payload cannot always be copied | Bridge reduces payloads to metadata first (question 10) |
| Q-GH-5 | The repository is public since 2026-11-20 | CodeQL and Scorecard now run; nothing in this phase may need a private repo |

## 2. Research record

| Topic | Source (version, date read) | Finding |
|---|---|---|
| `post_api_request` | Hermes v0.23.2 `agent/turn_response_intake.py` 80-110, `agent/api_request_hooks.py` 35-50 (2026-11-20) | Carries `provider`, `model` (configured), `response_model`, `api_request_id`, `turn_id`, `api_duration`, `finish_reason`, `message_count`, and `usage` = `CanonicalUsage` as a dict (`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`, `request_count`, `prompt_tokens`, `total_tokens`). Also `response` (with assistant text) and `assistant_message` (a raw SDK object) |
| `post_llm_call` | `agent/turn_finalizer.py` 490-512 | Carries the user message, the answer and the whole conversation: text only, no usage. Not needed for metering |
| `subagent_stop` | `tools/delegate_tool_results.py` 375-392 | `child_role`, `child_status`, `duration_ms`, plus a summary and tool trace (text) |
| Pricing | `agent/usage_pricing.py` `estimate_usage_cost` | Hermes prices usage itself, but the price is not in any hook payload. models.dev (`cost.input`, `cost.output`, `cost.cache_read`, `cost.cache_write`, USD per million tokens) is available in the cached registry file |
| References | Hiutaky/token-saver (MIT), WolfMark-Ltd/spendsense (GPL-3.0) | Read for the idea of threshold rules and burn-rate forecasts only. Nothing copied; spendsense not opened as code |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Smallest scope? | | Account every Hermes API response by day, hour, provider and model (tokens as reported, requests, errors, estimated cost); quota rules with thresholds that fire once per period; a burn-rate forecast; events for other modules | default accepted |
| 2 | Capabilities | | `hermes.hooks`, `ui.panel`; `fs.read` optional, only to read model prices from the models.dev cache (without it, cost is "unknown") | default accepted |
| 3 | Reuse, adapt or write? | | Write; references above for ideas only | default accepted |
| 4 | New dependencies? | | None | default accepted |
| 5 | Security | | Threat table below | default accepted |
| 6 | State; uninstall | | Tables `daily`, `hourly` (kept `retention_days`, default 90 and 7), `quotas`, `fired`, `prices`. Removal drops them unless `keep_data` | default accepted |
| 7 | Control surface | | Read-only: `summary {days}`, `usage {day, provider}`, `quotas`, `forecast {name}`. Human-only: `quota_add {name, scope, metric, period, limit, thresholds}`, `quota_remove {name}`, `prices_reload`. Panel `meter.status` | default accepted |
| 8 | Logs, metrics, alerts | | Log stream `meter`; event `meter.threshold {quota, percent, used, limit, period}` once per threshold per period; `meter.exhausted` at 100 %; both audited | default accepted |
| 9 | Update and rollback | | Bundled | default accepted |
| 10 | Core contract change? | (a) amend ADR-0004: the bridge hands modules **metadata only** (drops message text and raw objects) for observer hooks; (b) each module filters | (a). Privacy by default for every module, and it removes the deep-copy failure on raw SDK objects. The router keeps working: its error hook needs only `request.body.model`, which stays | default accepted |
| 12 | Auto-start needs every requested capability, so an optional grant (`fs.read` here, `llm.paid` for the router) blocks it | (a) manifest `capabilities.optional`, a subset of `request` not needed to start; (b) drop the optional capability | (a). The router no longer waits for `llm.paid` to auto-start | default accepted |
| 11 | Operator input? | | None. Quotas are opt-in | default accepted |

Accuracy: token totals are the provider-reported usage as normalized by Hermes, summed without conversion, so
they match exactly (tolerance 0 tokens) for every response Hermes saw. Cost is an estimate from models.dev
prices (stated as such); responses with no usage are counted as requests with `usage_missing`.

### Threats and tests (question 5)

| Threat | Control | Test |
|---|---|---|
| Prompt or answer text stored or exposed to modules | Bridge reduces observer payloads to metadata; meter stores counters only | `test_observer_payloads_hold_no_text`, `test_meter_stores_no_text` |
| A threshold alert repeats or floods | `fired` table keyed by quota, period and percent | `test_threshold_fires_once_per_period` |
| Model changes quotas to hide spending | Quota changes are human-only actions, audited | `test_model_cannot_change_quotas` |
| Hostile usage numbers (negative, huge, bool, float) | Non-negative ints up to 10^9 per field accepted; others counted as 0 and flagged | `test_hostile_usage_values` |
| Unbounded growth | Hourly rows 7 days, daily rows `retention_days`, pruned hourly by the scheduler | `test_retention` |

## 4. Acceptance tests (written before code)

- [x] Totals equal the sum of reported usage (tolerance 0 tokens); cost estimate from models.dev prices.
- [x] Threshold events fire once per quota, threshold and period.
- [x] No prompt text stored by default; observer hooks deliver metadata only.

## 5. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
| A denylist of text keys keeps text out | Hermes payloads carry text and tokens under keys nobody listed (`side_question_token`); forward an allow-list only | Bridge; any filter on third-party payloads |
| "Optional" capabilities only change start-up | Once optional, nothing checked them; every optional capability needs a run-time `ctx.has` check | Every manifest with `optional` |
| Cooling a quota scope stops traffic | Middleware can only steer; the pass-through path needs the same rules and an audit trail, and a hard stop needs a blocking hook | Router, M6 policies |
| GitHub CodeQL can run as a workflow job | With default setup on (enabled when the repository went public) advanced uploads are rejected | CI |

