# Review C: Hermes adapter and bundled modules (hermes-switchyard v1.0.0)

> Published at the close of phase H1 (v1.0.1, 2026-11-20). Every High and Medium finding is fixed; the
> status of each finding is in [findings-index.md](findings-index.md). Findings still open in the 1.1 backlog are
> withheld (`withheld until fixed (#N)`) and are added when their issue closes. Probe scripts are not published.

Read-only review. Nothing in `<workstation>/src/hermes-switchyard` or the Hermes install was changed. No git, gh or network commands.
Probes ran against a fake in-memory context and the real `switchyard` package, from `switchyard-eval/probes/`.

Hermes API facts were checked against the installed v0.23.2 source (`hermes_cli/plugins*.py`, `hermes_cli/middleware.py`, `hermes_cli/lifecycle.py`, `agent/turn_*.py`, `tools/delegate_tool*.py`, `model_tools.py`, `tools/terminal_tool_result.py`, `hermes_cli/config.py`).

## Summary

| ID | Severity | Confidence | Area | One line |
|---|---|---|---|---|
| C-1 | High | confirmed-by-probe | router / bridge | A route that runs past 2 s fails open: a paid configured model goes out, uncharged. |
| C-2 | Medium | confirmed-by-probe | bridge | A hung observer costs a full timeout per LLM call, queues work without bound, and writes an fsynced audit record per call. |
| C-3 | Medium | confirmed-by-probe | trim / bridge | Must-keep scan runs outside the 2 s timeout: 4 MB of hostile tool output takes 4 to 8 s. |
| C-4 | Medium | confirmed-by-probe | router | A later 429 on a resource overwrites its quota cooldown; the exhausted quota reopens after 60 s. |
| C-5 | Medium | confirmed-by-reading (Hermes source) | meter | `post_api_request` carries no `request`, so the "model actually sent" attribution never applies. Cost and quotas use the served id. |
| C-6 | Medium | confirmed-by-reading | lifecycle / ops | The model can `module activate` any module, including ones the operator set to `manual`. Only `disabled` is refused. |
| C-7 | Medium | suspected | workers / router | A persona's profile model is trusted as free by default (`paid=False`). Unregistered models are never blocked or charged. |
| C-8 | Medium | confirmed-by-probe (mechanism) | router / engine | `need_for` sizes only `messages`. An `input`-style request is sized as T1, which bypasses tier rules. |
| C-9 | Low | confirmed-by-reading | adapter | Adapter exceptions are swallowed with no audit, including in the `pre_llm_call` gate. A broken hard stop is invisible. |
| C-10 | Low | confirmed-by-probe | meter | A float token count is zeroed and flagged `usage_missing`, despite the "exactly as reported" claim. |
| C-11 | Low | confirmed-by-reading | resources | Docs and docstring say the model may run `import_preview`. The code refuses it. |
| C-12 | Low | confirmed-by-reading | dashboard | `dashboard/manifest.json` says version 0.10.0. `plugin.yaml` says 1.0.0. |
| C-13 | Low | confirmed-by-reading | code quality | Helpers duplicated across 9 modules. Four modules are 460 to 555 lines. |
| C-14 | Low | - | - | withheld until fixed (#114) |
| C-15 | Low | suspected (not checked live) | secrets | `bw get` output is returned without stripping; a trailing newline would reach the caller. |
| C-16 | Low | confirmed-by-reading | activation | Read paths write Hermes config: `health()` and `on_turn` can expire and undo a preset. |
| C-17 | Low | confirmed-by-reading | config | Read-modify-write of `config.yaml` has no cross-process lock; a concurrent edit can be lost. |
| C-18 | Info | not checked | dashboard | Dashboard POST routes can deactivate the router (hard stop). This is by ADR-0009. Hermes CSRF or header enforcement on these routes was not traced. |

Counts: Critical 0, High 1, Medium 7, Low 9, Info 1 (18 findings).

---

## Details

### C-1 (High): slow route fails open; the paid gate is skipped

- **Where:** `src/switchyard/bridge.py:169` (default `timeout=2.0`), `:261-275` (`_run`: `future.result(timeout)`, then `return False, None`), `:511-513` (on failure the model stays unchanged). `src/switchyard/modules/router/router_module.py:222-251` (`route`: lock at `:230`, charge at `:234-235`, `_sent` write at `:245`). `src/switchyard/state.py:81` (`busy_timeout = 5000`).
- **What is wrong:** The middleware runs on the module's 2-worker pool with a 2 s deadline. When the deadline passes, the bridge returns the configured model and the request goes out. The route keeps running in the background. Its paid-gate decision and charge are then applied to a request that was never routed that way. The state DB's `busy_timeout` (5 s) is longer than the bridge deadline, and non-hosting processes share `state.db`, so a locked DB can trigger this.
- **Evidence (probe `probe_paid_timeout.py`, real `switchyard` code, fake registry where `paid-x` is paid and not allowed):**
  ```
  fast router: dispatch 0.00s -> model sent = 'free-y'; spend rows = []
  slow router (3 s): dispatch 2.00s -> model sent = 'paid-x'; spend rows = []
  ```
  From `probe_router_meter.py` (late charge): `dispatch returned after 2.02s with result=None`, then `spend 2.5s later: [(1,)]  sent-map: {'a1': 'openrouter/paid-x'}`. The paid charge and the failover map point at a model that was not sent.
- **Impact:** The paid gate, the free-first guard and the budget can all be skipped whenever route work exceeds 2 s. The R1 fix "paid configured model bypassed the paid gate" is undone on this path. The failover map can also blame the wrong resource on a later `api_request_error`.
- **Fix:** (a) Give `llm_request` route work its own budget: cache the `resources.resolve` result per turn, and avoid DB waits on the hot path. (b) When the deadline passes, the late result must never charge or write `_sent`. Use a cancel flag checked before the charge. (c) Choose a fail-closed default for a known paid configured model when no route answer arrives. Middleware cannot refuse a request, so the nearest option is to route to a free fallback that was computed earlier in the turn. (d) Set the router's SQLite busy wait below the bridge deadline, or open a separate connection with a short timeout.
- **Test:** Regression on `probe_paid_timeout.py`. Slow route plus paid configured model must not send the paid model uncharged. A late route must leave `spend` and `_sent` untouched.

### C-2 (Medium): hung observer costs a timeout per call and queues forever

- **Where:** `src/switchyard/bridge.py:191-193` (unbounded per-module queue, `max_workers=2`), `:263-272` (timeout does not cancel the future; audit per timeout), `:373-379` (`dispatch_hook` waits for each module serially). `src/switchyard/audit.py:228` (every append is fsynced). `src/switchyard/hermes/__init__.py:196-209` (forwarder runs observers synchronously on the Hermes thread).
- **What is wrong:** A callback that never returns keeps its worker busy. Each new call submits another task that is never cancelled, so the queue grows. Each call still waits the full timeout, and each timeout writes an fsynced audit record. Observers run serially, so a hung module costs `timeout` for every observer and gate hook on every LLM call.
- **Evidence (probe `probe_bridge_hang.py`, timeout 0.5 s, callback sleeps 3 s):**
  ```
  call 0..5: dispatch took 0.50s each
  pending work items in module pool queue: 3
  audit actions: ['module.hook_timeout' x 6]
  ```
- **Impact:** A hung module adds 2 s per observer hook per LLM call (about 6 s with the default hook set). Memory grows with every call. The audit log fills at one fsynced record per call. This is a latency and resource DoS, not a bypass. The turn still continues.
- **Fix:** Circuit breaker per module, mirroring `_transform_result`: after N timeouts, skip calls for T seconds and audit once per pause. Cap the pending queue (drop or skip when the pool is saturated). Run observers concurrently and join against one shared deadline, not serially.
- **Test:** Hung module: after 3 timeouts, later calls return in under 10 ms; queue length stays bounded; exactly one pause audit record.

### C-3 (Medium): must-keep scan is outside the timeout; hostile output stalls the turn

- **Where:** `src/switchyard/trim.py:24-38` (`MUST_KEEP`), `:69-77` (`must_keep`), `:80-123` (`rebuild`). `src/switchyard/bridge.py:391-411` (`dispatch_transform`: `normalise` and `rebuild` run on the Hermes thread, not through `_run`). `:393` (`MAX_INPUT_CHARS = 4_000_000`).
- **What is wrong:** The 2 s timeout covers module callbacks only. Scanning a 4 MB text with a regex set runs unbounded on the Hermes thread. ADR-0008 bounds work per line, not per text.
- **Evidence (probe `probe_trim_timing.py`, `normalise` plus `must_keep` on about 4 MB of 1000 to 1200 lines):**
  ```
  progress-ish  ("1/" * 1999):   8.27s
  spaces        (" " * 3999):    4.02s
  file-ish      ("ab.cd..."):    2.64s
  dot word      ("a." * 1999):   1.70s
  ```
- **Impact:** Only when a module holds `hermes.output` and a large tool result arrives. The result is a multi-second stall per tool call on hostile content (for example a fetched page). Still no data loss or injection.
- **Fix:** Lower the scan size for transforms (for example 256 KB), or run `dispatch_transform` through the same bounded executor so the 2 s rule applies. Consider a single-pass tokenizer for the must-keep set.
- **Test:** Timing test: 4 MB adversarial input returns under 0.5 s, or fails open with an audit.

### C-4 (Medium): 429 overwrites the quota cooldown

- **Where:** `src/switchyard/modules/router/router_module.py:391-393` (`on_error`: `INSERT OR REPLACE` with `now + cooldown_seconds`), `:406-410` (`on_exhausted`: `until` capped at 32 days, same table). `:319` (quota detection checks `reason.startswith("quota")`).
- **What is wrong:** One table holds both quota exhaustion and per-request error cooldowns, and both write with `INSERT OR REPLACE`. A later error on the same resource replaces the quota row with a short, error-reason row.
- **Evidence (probe `probe_router_meter.py`, scope = resource id, `period_end` 2099 clamped to the 32-day cap):**
  ```
  cooldown after quota exhaustion: [(1797964296.1, 'quota q1 exhausted')]
  cooldown after one 429 on same resource: [(1795199556.1, 'http 429')]
  quota still counted as exhausted by the router: http 429
  ```
- **Impact:** After 60 s the exhausted resource is eligible again, and the quota steering is lost. The passthrough path re-sends the exhausted configured model. The paid-blocked check also stops detecting the quota.
- **Fix:** Use separate tables for quota scopes and error cooldowns. Or change `on_error` to `ON CONFLICT DO UPDATE SET until = MAX(until, excluded.until)` and keep the quota reason.
- **Test:** Quota cooldown survives a later 429; `until` never decreases; `_effective_cooling` still reports the quota.

### C-5 (Medium): meter attribution ignores the sent model on `post_api_request`

- **Where:** `src/switchyard/modules/meter/meter_module.py:247-249` (`sent` from `kw["request"]["body"]["model"]`, else `response_model`, else `response.model`, else `kw["model"]`). Hermes `agent/turn_response_intake.py:80-110` (`post_api_request` kwargs: `model=agent.model`, `response_model`, `response`, `usage`; no `request`). `src/switchyard/bridge.py:128-162` (`metadata_only` copies `request` only if present). `modules/meter/README.md:7-8` ("the model actually sent, else the served one").
- **What is wrong:** On `post_api_request`, `sent` is always `None`. The key is the served id, or the configured model (`agent.model`) when the response lacks a model. The router routes on the request, so the configured model is the wrong one for a routed request.
- **Impact:** (a) If the served id differs from the registry id (for example a dated or suffixed model name), the response is `unpriced` and adds no cost. Per-resource quotas (`_used` matches `provider` and `model` exactly) never count it. (b) If the response lacks a model, usage is charged to the configured model. I verified the mechanism from source. I did not verify what OpenRouter actually returns.
- **Fix:** Carry the routed model with the request. The router already keeps `_sent[api_request_id]`. Expose that to the meter through the bridge, or match on `api_request_id`. Correct the README.
- **Test:** Routed model X, response echoes `X-2024-08-06`: the row lands on X and is priced. Missing response model: charged to X, not to the configured model.

### C-6 (Medium): the model can start manual modules

- **Where:** `src/switchyard/lifecycle.py:298-302` (`activate` refuses only `mode == "disabled"`). `src/switchyard/ops.py:31-44` (`("module", "activate")` in `MODEL_OPS`, line 35). `src/switchyard/hermes/__init__.py:52` (`MODEL_TOOL_ACTIONS` includes `activate`) and `:6-8` (docstring: the model cannot "change modes").
- **What is wrong:** `manual` is not an operator-only gate. The model can start any module the operator left manual, and that module then runs with whatever grants it holds. Grants are not widened, so this is not a privilege escalation. It does defeat the operator's manual intent.
- **Impact:** Modules that are manual by design (`offload` and others; check each `module.toml` `[lifecycle]`) can be started by the model. Modules the operator stopped on purpose can be restarted. The effect depends on each module's grants (for example, an offload connector that is allowed by name still needs its `process.spawn` or `net.outbound` grant). Not each module was checked against this.
- **Fix:** For `MODEL_ACTOR`, refuse `activate` unless `mode == "auto"`, or drop `activate` from `MODEL_OPS` and the tool actions. Make the docstring match the behaviour.
- **Test:** Model `activate` on a manual module is refused with `policy.denied`. The same call on an auto module still works.

### C-7 (Medium, suspected): persona model trusted as free

- **Where:** `src/switchyard/modules/workers/workers_module.py:234-240` (profile route: `free_only: not paid`, and the operator's `paid` is the only check), `:387-390` and `:412` (`paid` defaults to `False`). `src/switchyard/modules/router/router_module.py:316-330` (`_guard_eval`: a model not in the registry is never `paid_blocked`).
- **What is wrong:** For a profile route, Switchyard does not see the model Hermes runs. The operator's `paid` flag decides whether it counts as free. The default is free. A persona whose model is paid and unregistered runs with no budget charge and no `llm.paid` check.
- **Impact:** Unmetered paid spend on a persona, if the operator does not declare it paid. Registered models are protected by the router. Not run against a live persona, so suspected.
- **Fix:** Require `paid` to be declared explicitly for profile routes, or check the profile's model against the registry at `role_set` time and refuse unregistered models. Default unknown persona models to paid.
- **Test:** `role_set` with a profile whose model is not in the registry: refused, or routed with `free_only=False` and budget checks.

### C-8 (Medium, mechanism verified): `need_for` sizes only `messages`

- **Where:** `src/switchyard/modules/router/engine.py:62-76` (`need_for` reads only `messages` and `tools`).
- **What is wrong:** Responses-style requests carry `input`, and Anthropic-style requests carry `system` outside `messages`. Both are counted as zero, so the tier falls to T1.
- **Evidence (`probe_router_meter.py`, 400 000-character prompt):**
  ```
  need_for(messages) tokens: 100001 T4
  need_for(input)    tokens: 1      T1
  ```
- **Impact:** For `input`-style providers, `min_tier` paid rules and the context-window check are bypassed. The default provider (`openrouter`) appears to use `messages`. I did not check which `api_mode` Hermes uses for other providers.
- **Fix:** Count every text-bearing key (`input`, `system`, `instructions`, `prompt`). If the shape is unknown, use T5.
- **Test:** `input`-shaped 400 000-character request is T4 or higher.

### C-9 (Low): adapter exceptions are silent

- **Where:** `src/switchyard/hermes/__init__.py:207-209` (forwarder `except Exception as exc: del exc`), `:226-227` (terminal transform), `:261-262` (tool transform), `:270-271` (`llm_request`).
- **What is wrong:** Any exception in the adapter's own dispatch, including in `dispatch_gate`, returns `None` with no audit or log. A gate that breaks stops blocking, and nothing records it. Module failures are audited, but adapter failures are not.
- **Impact:** A broken `hard_stop` gate fails open silently.
- **Fix:** Audit `core.adapter_error` with the exception class, once per hook and class per process. Log it at warning level.
- **Test:** Inject an exception into `dispatch_gate`; an audit record appears and the turn still proceeds.

### C-10 (Low): float token counts are zeroed

- **Where:** `src/switchyard/modules/meter/meter_module.py:55-59` (`_count`: any non-int becomes 0 and `usage_missing`).
- **Evidence:** `_count(12.0)` returns `(0, True)`; `_count(12)` returns `(12, False)`.
- **Impact:** Tokens reported as floats are dropped. The README claims "exactly as Hermes reports them".
- **Fix:** Accept integral floats (`value.is_integer()`), and round other floats.
- **Test:** `_count(12.0) == (12, False)`.

### C-11 (Low): docs say the model may run `import_preview`

- **Where:** `src/switchyard/modules/resources/resources_module.py:8-9` (docstring: "the model may run it"), `:117` (`read_only = {"list","show","pools","resolve"}`). `modules/resources/README.md:34` ("the model may run it") and `:50` (table: "yes").
- **What is wrong:** The code refuses the model (`import_preview` is not read-only). The docs say it is allowed. The R1 Q&A says "Operator only". Three sources, two positions.
- **Impact:** Documentation only, but the intended behaviour is unclear. The stricter code is the safer reading.
- **Fix:** Settle the intent, then make the code, README and docstring agree. The code appears to match the R1 decision.

### C-12 (Low): version mismatch

- **Where:** `dashboard/manifest.json:6` (`"version": "0.10.0"`), `plugin.yaml:5` (`version: 1.0.0`).
- **Fix:** Align the versions, or generate both from one source at release.

### C-13 (Low): duplication and module size

- **Where:** `_q` and `_t` helpers are repeated in 9 modules. `_int_setting` is repeated in `router_module.py:49`, `supervisor_module.py:36`, `workers_module.py:50` and `scanner_module.py:35`. `default_models_dev_cache` is repeated in `meter_module.py:46-52` and `resources_module.py:48-54`. Module sizes: `meter_module.py` 553 lines, `router_module.py` 502, `resources_module.py` 477, `workers_module.py` 463.
- **Fix:** Move the shared helpers into one module with tests, and split the router (decision, paid gate, failover) and the meter (store, quotas, actions).

### C-14 (Low)

Withheld until #114 is closed.

### C-15 (Low, not checked live): `bw` output not stripped

- **Where:** `src/switchyard/modules/secrets/backends.py:193` (`return str(done.stdout)`). Compare `:116` (keychain uses `rstrip("\n")`).
- **What is wrong:** If `bw get password` prints a trailing newline, the secret includes it. I could not run `bw` here to confirm.
- **Fix:** Strip one trailing newline, and add a test with a recorded `bw` output.

### C-16 (Low): read paths write Hermes config

- **Where:** `modules/activation/activation_module.py:110-114` (`health()` calls `_expire()`), `:180-182` (`on_turn` calls `_expire()`), `:170-174` (`_expire_locked` calls `_undo_preset`, which writes Hermes config).
- **What is wrong:** A dashboard health poll can end an active preset and write `config.yaml`. This is a side effect on a read path.
- **Fix:** Move expiry to the scheduler tick and keep `health()` read-only.

### C-17 (Low): config read-modify-write has no cross-process lock

- **Where:** `src/switchyard/hermes/config_port.py:20-33` (`load_config` then `save_config(merge_existing=True)`). `src/switchyard/hermesconfig.py:115-124` and `:143-151` (`stored` and `unexpected` are compared after the write).
- **What is wrong:** The lock is in-process only, so a concurrent edit of `config.yaml` between the read and write can be lost. The read-back check can then roll back the wrong thing.
- **Impact:** Suspected, not reproduced. Hermes's own `save_config` preserves `${VAR}` refs and strips defaults (I checked), so the YAML-damage concern is mitigated.
- **Fix:** A file lock around the read-modify-write, or re-read inside the lock before writing.
- **Fixed in 1.1 (#115):** `ConfigWriter.set` holds `FileLock(<backups>/.write.lock)` around the read-modify-write, shared by every Switchyard process. The rollback re-reads the key and does not restore when a completed write has since been changed by someone else (audited `restored: skipped`). A part-way failure still rolls back. Hermes's own writers do not take the lock; that limit is documented in ADR-0005.

### C-18 (Info): dashboard can deactivate the router

- **Where:** `dashboard/plugin_api.py:76-80` (`POST /modules/{id}/{verb}` with `activate` or `deactivate`). `dashboard/dist/index.js` (the Modules table button calls the same route). ADR-0009 §4 allows it.
- **Not checked:** whether Hermes requires the session header on these POST routes. The HTTP gate in `hermes_cli/web_server_dashboard.py` and `plugin_host.py` was not traced to the end. The bundled JS uses `SDK.fetchJSON`, which other bundled plugins also use. Please confirm that CSRF-prone cookie auth is not used.
- **Checked in 1.1 (#116), against Hermes v0.23.3:** loopback mode requires `X-Hermes-Session-Token` on every `/api/` request (`web_server.py` `auth_middleware`); a page on another site cannot set that header without a CORS preflight, which is not allowed. Behind the OAuth gate, session cookies are `SameSite=Lax` (`dashboard_auth/cookies.py`), and `dashboard_auth/middleware.py` `_cookie_write_refusal` answers 403 to any non-GET cookie request whose `Sec-Fetch-Site` is `same-site` or `cross-site`; `/api/plugins/` is not on the gate's public list. So cookie CSRF is refused in both modes.
- **Fixed in 1.1 (#116):** `plugin_api.py` repeats the `Sec-Fetch-Site` refusal on its three POST routes (`_own_page_only`), so it does not depend on Hermes keeping that gate. Tested under real FastAPI in `tests/integration/test_dashboard_api.py`.

## Done well

1. **Observer payloads are allow-listed.** `bridge.py:40-84` and `:128-162` drop message text, `side_question_token`, `child_summary` and `tool_call_history`. The `subagent_stop` payload contains `child_summary` and `tool_call_history`, and both are dropped.
2. **Middleware can only change `model`.** `bridge.py:515-534` uses a type-strict deep compare, and modules get deep copies. Unknown keys are rejected and audited.
3. **Gate and delegation messages are core-written.** `bridge.py:435-466` and `:297-355` only accept reason codes that match a regex, and the text is written by the core, so module text never reaches the model's reply.
4. **Hermes config writes are careful.** `hermesconfig.py:115-166`: allow-list, backup first (names only), audit, read-back, rollback. Hermes's `save_config` preserves `${VAR}` refs and strips defaults (checked in `hermes_cli/config.py:2262-2340`).
5. **Offload enforces its data declaration.** `offload_module.py:185-217` refuses fields outside the connector's list before any send. Argv is fixed, the prompt goes on stdin, the CLI runs in an empty cwd, and URLs are loopback-only (`:91-110`). The net broker refuses redirects and proxies (`net.py:43-65`), and spawn uses an allow-listed child environment (`process.py:101`).
6. **Secrets are handled by argv and stdin only.** `backends.py:31-39` rejects names with a leading `-`, values never go on a command line, and helper stderr is never echoed.
7. **Scanner parsers are strict.** `parsers.py` type-checks every field, `scanner_module.py:179-186` treats truncated output as failure, and partial results never resolve findings. `gitleaks` runs with `--redact`, and the trivy secrets rule keeps the rule id and location only.
8. **Model tools are restricted in the core, not just the adapter.** `core.py:248-252` checks `MODEL_OPS`, and `ops.py:228-235` allows only read-only module actions for the model. Every module-written result is wrapped as `untrusted_data` (`hermes/__init__.py:53-55`, `:304-308`).
9. **The trimmer cannot inject text.** `trim.py:80-123` keeps original lines only and writes just the `[switchyard: N lines omitted]` marker. Must-keep covers errors, exit codes and paths. Nothing a module returns is ever written into the output.
10. **Dashboard frontend is safe.** `dashboard/dist/index.js` uses React text nodes only. It has no `innerHTML`, `eval` or `dangerouslySetInnerHTML`. `plugin_api.py:19-21` validates every path parameter against a regex, and the operation list is fixed.
11. **Audit appends are durable and serialised.** `audit.py:6` and `:171-184`: lock, head re-read, fsync per append (`:228`).
12. **SQL f-strings interpolate only constants and `state.table()` names; values are bound.** I checked the f-string SQL in router, meter, resources, supervisor, workers, scanner, activation, trimmer and inbox. The S608 suppressions are justified for the cases read. `state.table()` itself was not read.

## Accepted, documented, not re-reported

- Same-user boundary: T2 processes and a model with a shell can reach state files (`DESIGN.md` §4; R1 Q&A).
- Scanners reach external services (osv.dev, PyPI, trivy DB, semgrep rules), which the net broker cannot gate (`scanner/README.md:8-15`).
- Workers report stuck children but do not stop them (ADR-0007; `workers/README.md:32-33`).
- Trimming is deletion-only, and ANSI removal can join fragments (ADR-0008).
- Router steering is not a hard stop unless `hard_stop` is set (`router/README.md:52-62`).
- Codex in its read-only sandbox can read files (`offload/README.md:16-17`).
- Secret strings are not zeroed (`secrets/README.md:94`).

## Not checked

- `core.py`, `state.py`, `audit.py`, `api.py` and `updates.py` beyond the lines cited. `state.table()` naming was not read.
- The dashboard HTTP gate on POST routes (C-18) was not traced in the H1 review; it was traced in 1.1 (see C-18).
- The offload CLI flags (`claude --tools ""`, `codex --sandbox read-only`) against the installed CLIs.
- Real `wincred`, `bw` and `secret-tool` behaviour (C-15). The ctypes path was not run.
- An item for withheld finding C-14.
- Whether OpenRouter returns dated or suffixed model ids (C-5). Only the mechanism was verified.
- Hermes `api_mode` for providers other than `openrouter` (C-8).
- The test suite, lint and type checks were not run.
- Docs beyond the module READMEs' disposition tables and the claims grepped from them.

## Probe scripts (all under `switchyard-eval/probes/`)

- `probe_bridge_hang.py`: C-2.
- `probe_router_meter.py`: C-4, C-8, C-10, and the late-charge part of C-1. Its module-level output is printed when imported.
- `probe_paid_timeout.py`: C-1 (fast and slow routes). Imports the fake context from `probe_router_meter.py`.
- `probe_trim_timing.py`: C-3.
