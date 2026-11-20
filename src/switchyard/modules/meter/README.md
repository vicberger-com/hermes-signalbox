# Meter (bundled module, M4)

Counts every Hermes API response and checks opt-in quotas. Q&A: [docs/qa/05-m4-prework.md](../../../../docs/qa/05-m4-prework.md).

## What is counted

From `post_api_request` (metadata only, ADR-0004 decision 6), per UTC day and hour, provider and model (the
model actually sent, else the served one): requests, and the token buckets exactly as Hermes reports them
(`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`). "Tokens" in
quotas and summaries is input + output + cache read + cache write (reasoning is part of output).

- **Accuracy:** token totals are sums of the reported numbers, so they match provider-reported usage exactly
  (tolerance 0) for every response Hermes saw. A response without usage, or with a value that is not a
  non-negative integer up to 10^9, counts as a request with `usage_missing`.
- **Cost:** an estimate in USD from models.dev prices (`cost.input`, `output`, `cache_read`, `cache_write` per
  million tokens; a missing cache price uses the input price). Needs the optional `fs.read` grant to read the
  cached registry; without it, or for a model without prices, responses are `unpriced` and add no cost.
- `api_request_error` adds to `errors`; `subagent_stop` counts runs and duration by role and status.
- Nothing else is stored: no prompt, answer, summary or tool text.

Hourly rows are kept 7 days, daily rows `retention_days` (default 90).

## Quotas

`quota_add {name, scope, metric, period, limit, thresholds}`:

- `scope`: `all`, `provider:<id>`, or one resource `<provider>/<model>` (provider part is lower-cased)
- `metric`: `requests`, `tokens`, `cost_usd`; `period`: `day` or `month` (UTC)
- `limit`: a decimal string; `thresholds`: percentages, default `"80,100"`

Each threshold fires once per quota and period: `meter.threshold` (audited as `module.meter.threshold`), and
at 100 % also `meter.exhausted`. The router (M3) cools the quota's scope down until the period ends.
`summary` totals cover every row (the model list is capped at 200, with `truncated`). `forecast {name}` projects the period total and the exhaustion time from the average rate over the last 24
hours (or since the period start).

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `summary {days}`, `usage {day, provider}`, `quotas`, `forecast {name}` | yes |
| Action | `quota_add`, `quota_remove {name}`, `prices_reload` | no |
| Panel | `meter.status` | |
| Config | `[modules.meter]` `retention_days` (90, 7-3650), `models_dev_cache` (Hermes home) | |

Capabilities: `hermes.hooks`, `ui.panel` (required); `fs.read` (optional, for prices).

## State and removal

Tables `daily`, `hourly`, `subagents`, `quotas`, `fired`. Removed with the module unless `keep_data`.

## Security review (M4 gate)

Reviewed 2026-11-20 by a fresh subagent with the M4 diff, the threat table and the Hermes v0.23.2 sources.

| Finding | Disposition |
|---|---|
| (high) An exhausted `all` / `provider:` quota was not applied on the router's pass-through and paid-fallback paths | **Fixed.** One effective-cooling helper for every path; when nothing is left the request passes through and `quota_passthrough` is audited. Documented as steering (middleware cannot refuse a request) |
| (high) `post_llm_call` carries `side_question_token`, a lease redeemable for an answer over the turn's messages; the denylist forwarded it | **Fixed.** Observer payloads use an allow-list of metadata keys |
| (medium) `llm.free` became optional and was then not checked at all | **Fixed.** The router checks `llm.free` on every request (free and self-hosted candidates need it) |
| (medium) Denylist forwarded unknown text keys and `base_url` with credentials in the query | **Fixed.** Allow-list; `base_url` reduced to scheme and host |
| (low) Quota changes could interleave with a threshold check | **Fixed.** Same lock |
| (low) Mixed-case provider scopes never matched | **Fixed.** Provider part lower-cased |
| (low) `summary`/`usage` totals undercounted past the row limit; subagent query unbounded | **Fixed.** Totals in SQL, `truncated` flag, subagent rows capped at 200 |

