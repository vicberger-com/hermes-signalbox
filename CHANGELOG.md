# Changelog

Format: Keep a Changelog. Versions: Semantic Versioning.

## [Unreleased]

### Fixed
- Installing as a plugin no longer changes Hermes's own environment: `plugin.yaml` declares
  `python_runtime: external` (Switchyard has no dependencies). Before, Hermes installed the package into its
  shared environment, every profile listed `switchyard`, and a Hermes Desktop install warned
  `install out of sync` on every command. The plugin loads its own `src/` before any other installed copy.
- The command line works while Hermes hosts the modules (#123). Offline commands (grant, revoke, mode, audit,
  config) run on the data directory again when the loopback API inside Hermes is enabled; before, it refused all
  of them. That API also serves the read-only `module health`. A refused command names the routes that work
  (`/switchyard ...` in a Hermes chat, or `switchyard api serve` with Hermes stopped), instead of
  "use the CLI".
- Routed model calls no longer pay about 20 ms each for audit writes (#124). A read-only call from one module
  to another (the router asking `resources` for candidates on every request) is now recorded once per minute
  per caller, target and action, with a `calls` count, instead of one record per call. Operator, chat and model
  actions are still recorded every time. Appending to the audit log no longer re-reads the log's tail when
  this process wrote the last record (checked by file name and size; another writer still forces a re-read).
- Each process start no longer writes a `module.verified` audit record for every module (#125). A record is
  written when a module's verified manifest is new or changed (by directory and manifest digest, kept in the
  state database); an unchanged module is only announced on the in-process event bus. On a fresh profile,
  most audit records were these (276 of the first 303). Rejections are still recorded every time.
- The Claude Code offload connector no longer fails a run whose program succeeded (#126). On Windows, a helper
  that Claude Code leaves running briefly holds the empty working directory, so removing it raised
  `PermissionError`; in live checks this happened on every run once the cleanup was traced. Removal is now
  retried for up to 1.5 s; if it still fails, the run succeeds and the offload log records
  `workdir_cleanup_failed` with the error class. Empty leftovers older than 10 minutes are removed on the next run.
- `switchyard api serve` runs from Task Scheduler (1.1 S-7). Task Scheduler starts programs in
  `C:\Windows\System32`, where the safe program lookup refuses every hit, so the daemon could not restrict its
  token file and exited with a traceback. Windows system tools (`icacls`, `taskkill`) now come from
  `%SystemRoot%\System32` directly; the same fault had also skipped the process-tree kill on timeout for
  daemons started this way. A start failure prints one `error:` line and exits 1.
- Secret handling (H1 A-17 #90, A-24 #92). `MemoryBackend`, the test-only backend, now refuses to construct
  without `allow_test_backend=True`; the old "running under pytest" check could be met by any module named
  `pytest`. The redactor keeps the 256 most recently used secret values instead of every value ever used, and
  forgets a backend's values when the module that provided it is deactivated. Credential-shape patterns still
  redact regardless.
- CLI to daemon trust (H1 B-8 #101, B-9 #102). The CLI now sends its token only to a daemon that proves it holds
  it: a fresh challenge to `GET /v1/health` must come back as the HMAC of the challenge keyed with the token.
  Anything else on the daemon's port gets "token not sent". When the connection fails after a command was sent,
  the CLI reports that the daemon may have applied it, instead of running the command again locally. A CLI of
  this version cannot talk to a daemon started by 1.0.x; restart the daemon after upgrading.
- `fs.read` refuses the remaining Windows device aliases (H1 B-6 #99): superscript forms (`COM¹`, `LPT³.txt`)
  and names with a colon (`NUL:`, `CON:stream`). Alternate data streams on ordinary files stay allowed.
- `net.outbound` drops a module-supplied `Host` header (any case), so a request always goes to the host the
  allow-list checked (H1 B-22, part 1 of #111).

### Documentation
- USER-GUIDE: running under Hermes (what works where), `hermes -p <profile> switchyard` for plugin installs,
  and a new section 10 on running the standalone daemon as a service (Task Scheduler, systemd, launchd).
- Phase H2 results (first real install and real turns; re-verified on Hermes v0.23.3) in
  `docs/qa/15-h1-prework.md`. The user guide covers Hermes Desktop, where the gateway hosts the modules,
  the shared-runtime install, and `--no-allow-tool-override`. The resources and offload READMEs state that
  `providers` and `payload` are strings. Follow-ups: #123-#126.
- USER-GUIDE section 10: the Windows Task Scheduler recipe was run end to end. It now uses a repeating trigger
  with `IgnoreNew` (Task Scheduler's restart setting does not restart a daemon that stops), and passes
  `--data-dir`.


## [1.0.1] - 2026-11-20

Maintenance release from phase H1: fixes for the 2026-11-20 evaluation of v1.0.0 (every High and Medium
finding; index in `docs/qa/h1/findings-index.md`).

### Upgrading from 1.0.0
- `module activate` refuses (exit 3, `policy.denied` audited) until every required capability is granted;
  grant them first (`switchyard module show <id>` lists them under `missing_grants`). The model may start only modules in `auto` mode.
- A delegated persona model with no registered cost is treated as paid: register its cost to keep it free.
- An explicit `--data-dir` (or the plugin's configured directory) now wins over `SWITCHYARD_DATA_DIR`.
- Modules from outside the bundled roots must run as subprocess (T2) modules; in-process is bundled-only.
- A grant whose capability a module's manifest no longer requests is removed (audited `policy.revoked`).
- A module whose hooks time out 3 times is paused for 60 seconds (`module.hooks_paused`); an expired
  activation preset ends at the next turn.

### Fixed
- Release workflow: the annotated-tag check fetches the pushed tag object first (`actions/checkout`
  rewrites a pushed tag as a lightweight ref, so the check refused every tag). The first `v1.0.1` tag's run
  stopped there and published nothing; the tag was re-created on the fixed commit.

### Security
- Module updates: the swap step re-checks, under the core lock, that the installed module is still the one
  that was staged and compared; otherwise the update is refused and audited (phase-close review CR-1).
- Release workflow (H1 D-3): a `verify` job re-runs the full gate and checks that the tag is an annotated tag on
  `main` matching the project version; the release job needs it. Release notes come from this file.
- Router: H1 C-1, C-4, C-8 (ADR-0013). A route that misses the bridge deadline fails closed: a remembered
  free candidate is sent, or a paid configured model is charged as a paid pass-through; late route results
  never charge or record. Cool-downs are never shortened by a later error. Every request shape is sized.

### Changed
- Real-Hermes integration test (H1 D-4). CI job `hermes-integration` installs Hermes Agent v0.23.2 (commit
  `ae2a81c`, the release the operator runs) from a checkout with `uv sync --frozen`, then loads Switchyard
  through Hermes's own plugin discovery and drives the model tools, the slash command, hooks, `llm_request`
  middleware and the dashboard API module through Hermes. The job never skips and is required by `ci-required`.
- Project status is **Beta** (`Development Status :: 4 - Beta`; H1 D-14). SECURITY.md states the support and
  deprecation policy: breaking changes only in minor releases, with the operator step in this file.
- Documentation and metadata (H1 WP10). The dashboard manifest version matches the package, and a test checks
  every version field (D-17). Pre-commit hooks are pinned to the same ruff and gitleaks versions as CI (D-16).
  REFERENCE.md no longer claims to be generated; it documents `--json`, `--data-dir`, `backup/`, the
  `trigger.*` and `module.*` events and the module states and modes, and a test checks every operation is
  listed (D-19). `docs_gap_audit.md` moved to `docs/qa/` as a historical record (D-18). DESIGN section 6 lists
  only the Hermes mechanisms the plugin uses. Docs corrected: `policy.denied` is an audit record, not an event
  (A-26); CTEs are allowed and bounded by the work budget (A-28); the resources module's `import_preview` is
  operator-only (C-11). Shared module helpers (`switchyard.modkit`) replace seven copies of the state helpers
  and four of the integer-setting check (C-13).
- Audit log and startup (H1 WP9). A torn last line (a crash mid-write) is repaired when the log is opened, so
  startup no longer reports it as tampering; a record whose final newline was stripped now fails `verify` (A-9).
  `audit tail` splits on `\n` only, so records holding U+2028/U+2029 read back (A-8). A failed start releases the
  host lock and closes the database (A-10). `audit ack` records the acknowledgement before clearing the warning
  (A-11). Policy denials with long module-supplied values are always recorded, values shortened (A-2). Bad bytes
  or deeply nested JSON in the log give a verify report instead of an exception (A-12); records are capped at
  128 KiB and the last record is found whatever its size (A-13); short writes are completed (A-14). Log lines
  with long event names stay valid JSON (B-4).
- Hot path (H1 WP8). Bridge calls have a per-module circuit breaker: three timeouts in a row pause that module's
  hooks, gates and middleware for 60 s (audited `module.hooks_paused`), and at most 4 calls per module run at once;
  observers run side by side against one shared deadline (C-2). The core's own scan of tool output has a 0.5 s
  budget per step; past it the output is kept unchanged and `core.transform_skipped` is audited (C-3). Observers
  of `post_api_request` and `api_request_error` get `sent_model`, the model the request actually went out with,
  and the meter charges that model (C-5). Adapter errors are audited once as `core.adapter_error` and the gate
  still runs when observers fail (C-9). Float token counts are rounded, not dropped (C-10). The activation
  module's health check no longer ends an expired preset; that happens at the next turn (C-16).
- Failure paths (H1 WP7). A failed directory swap during `module update` puts the previous version back and
  audits `module.rolled_back`; any error while restarting the new version counts as a failed restart (B-1).
  `module update`, `preview` and `check_updates` run git without the core lock; only the swap takes it, and one
  update per module runs at a time; `ls-remote` times out after 60 s (B-2). The process broker's deadline covers
  writing stdin, input is capped at 1 MB, and every failure path kills the tree and is audited (B-3). Updates
  also refuse `.pyd`, `.so`, `.dylib`, `.dll` and `.pyw` files, case-insensitively (B-11). An RPC call's deadline
  includes the send (B-14). Trigger numbers must be finite (B-21). The T2 flood kill and stalled-writer kill now
  run in the suite (D-11).
- Core trust (H1 WP6). An explicit `--data-dir` / `Core(data_dir=...)` now wins over `SWITCHYARD_DATA_DIR` (A-1),
  and the module contract no longer reads it. An entry `X.py` beside a directory `X/` is rejected, and module code
  is checked after import to come from inside its directory (A-3). `run_contract` has a `trust` check: in-process
  modules outside the bundled modules fail unless `bundled=True` (A-4). A stored grant the manifest no longer
  requests is removed (`policy.revoked`, reason `no longer requested`) and must be granted again if a later
  version asks (A-6). Operation results (health detail, panels, actions) pass through the secret redactor (A-7).
  Backend errors reach callers as their class name only, audited as `secret.backend_error` (A-18). The manifest
  validator checks the `policies` grammar (A-19). Smaller: A-15, A-21, A-22; `bw` drops one trailing newline (C-15).
  **Operator step:** a third-party in-process module must move to `isolation = "subprocess"` to pass the contract.
- Activation (H1 A-5, C-6, decision D8): a module starts only when every required capability is granted;
  otherwise activation is refused (`policy.denied`, exit 3 in the CLI) before any module code runs, and the
  module is not marked failed. The model may start only modules in `auto` mode. **Operator step:** grant every
  required capability before `module activate` (`module show <id>` lists `missing_grants`), and set modules
  the model should be able to start to `--mode auto`.
- Router (H1 C-7): for delegated subagents, a model the registry does not know is treated as paid (steered to
  a free resource, or counted as a paid pass-through). **Operator step:** register persona models with their
  real cost class.
- Packaging (H1 D-5, D-6, D-25): the wheel ships `py.typed`, `plugin.yaml` and the dashboard files (under
  `switchyard/_plugin/`); CI builds the wheel and sdist, checks the wheel's file list against
  `tools/wheel_files.txt` and smoke-tests a clean install; the release SBOM lists what the wheel installs, not
  the build tools; `[build-system]` pins `hatchling>=1.27,<2`. A pip install has no dashboard tab in Hermes
  0.23 (use `hermes plugins install` for it).
- CI (H1 D-12, D-23): Python 3.11 to 3.14; the skipped tests must match `tests/skip_allowlist.json` per OS.
- Updates (H1 D-2, D-15): git is the first runnable git on `PATH` (Windows hosts with Hermes Desktop put a
  packaged git first that other processes may not run), or `[tools] git` when set; `config show` prints the
  git in use. Programs found in the working directory stay refused, now tested on every OS.
- Bridge: `ctx.hermes_middleware` takes an optional `fallback`; middleware gets `context["claim"]`
  (ADR-0013). State store: `ModuleState.deadline(seconds)` bounds a thread's store waits.
- Router: a request with no recognised text key is sized as tier T5. With `hard_stop = true` the turn after
  a slow route that let a paid model through is blocked once (`route timeout`). No operator step needed.
- CLI (H1 D-7, D-8, D-9, D-10, D-26): a result with `status: failed` or `ok: false` exits 1 and says why
  (missing grants are named); an unknown capability name exits 2; `module panel` on an inactive module says
  so; `config show` prints `data_dir_source` and nested settings as `section.key: value`; `--help` marks
  operations that need the daemon with `[daemon]`. Scripts that relied on exit 0 for failed results must
  check the new exit code.
- Daemon: SIGTERM and Ctrl+Break stop `switchyard api serve` cleanly; the readiness line is flushed. The client
  removes `api.port`/`api.token` left by a daemon that died (only while no process holds `host.lock`) and
  connects with a 0.5 s timeout.
- `module list` / `module show` add `missing_grants`. The model tool description no longer names
  `deactivate` (H1 D-20).
- Loopback API: unsupported methods are Host/Origin-checked too; dropped connections print no traceback
  (H1 B-20, B-24).
- User guide: two data stores explained, `switchyard api serve` as step 0, the capabilities each module needs
  to start, and grant examples that work as written (H1 D-1). `tools/guide_walkthrough.py` runs the guide's
  commands in CI (`tests/acceptance/test_guide_walkthrough.py`).

### Added
- Bug-report and feature-request issue forms; wiki framework, page templates and generated wiki source with
  `tools/wiki_publish.py` (both merged after the v1.0.0 tag).
- Phase H1 (hardening, target v1.0.1) and H2 (first real install) in `docs/BUILD-PLAN.md`, with rules for
  maintenance phases; H1 pre-work Q&A `docs/qa/15-h1-prework.md`; findings index and the full engineering
  review under `docs/qa/h1/`. No code change.

## [1.0.0] - 2026-11-20

Phase R1: hardening review, documentation, first stable release. Review dispositions:
`docs/qa/14-r1-prework.md` section 3.

### Added
- `docs/USER-GUIDE.md` and `docs/REFERENCE.md` (every operation, tool, core setting, audit action and event).
- `audit ack` (operator only): acknowledge a recorded audit-chain failure.
- ADR-0012: replacing Hermes compaction is deferred past 1.0.

### Changed
- The model actor is limited in the core to an allow-list of operations (`MODEL_OPS`); `deactivate` is no
  longer a model tool action; module action results reach the model wrapped as `untrusted_data`.
- `module remove --keep-data` keeps data only, never grants. Module ids may not end in `_`.
- `inbox` requests `core.read`: subscribing to `*` or `core.*` events needs it. Grant it after upgrading.
- `resources import_preview` is operator only; cost-class changes are listed and applied as `manual`.
- Every meter quota fires at 100 %; cost quotas need loaded prices.
- Router: free-first after repeated failures; paid pass-through is counted against the budget.
- Supervisor reports modules that stopped since its last pass.

### Security
- Audit log: inter-process append lock and monotonic anchor; failures persist until acknowledged.
- T2 host: bounded message queue and one deadline per call; log streams rotate at 20 MB.
- Broker facades re-check context and grant on every call.
- Trimming keeps 401/403/rejected/blocked lines. Secret leak guard checks encoded forms. Short secrets refused.
- Documented the same-user boundary (DESIGN section 4, SECURITY.md).
- Follow-up review: T2 send deadline and flood kill; guarded facades hide private state; torn audit tails are
  repaired and recorded; leak tripwire no longer blocks ordinary text; all module-written text reaching the
  model is labelled; verify takes the append lock.

## [0.13.0] - 2026-11-20

Phase M12: update and release control for modules.

### Added
- ADR-0011: `module preview` (SBOM delta, patch notes, tree digest); `module update` takes `digest` and refuses
  permission widening without `accept_wider`; SBOM delta stored for every update; manifest `[update] channel`
  and `module check_updates`.
- Bundled `updates` module (M12): scheduled channel checks with one alert per new commit; never applies.

### Security
- M12 security review (`src/switchyard/modules/updates/README.md`): compiled and `.pth` files refused; added
  contributions widen; git isolated from surrounding repositories; checks single and cached; chunked hashing with
  a size cap; rollback widening check, commit restore and pruning; exact patch-note headings.

## [0.12.0] - 2026-11-20

Phase M11: offload connectors.

### Added
- ADR-0010: `net.outbound` broker (`ctx.net.request`): manifest host list, no redirects or proxies, capped bodies,
  audited by host and status only.
- Bundled `offload` module (M11): JevK5, n8n, Claude Code and Codex connectors with declared license class, target
  and data sent; non-open connectors off until allowed by name; payload fields enforced.

### Security
- M11 security review (`src/switchyard/modules/offload/README.md`): Claude Code runs with no tools and agent CLIs
  in an empty working directory (process broker `cwd`); total request deadline; short responses and malformed
  URLs are failures.

## [0.11.0] - 2026-11-20

Phase M10: security testing connectors.

### Added
- Bundled `scanner` module (M10): gitleaks, bandit, pip-audit, osv-scanner, semgrep and trivy as external processes
  on a schedule or on demand; normalised, de-duplicated findings; failures reported as findings; alerts via
  `notify`.

### Security
- M10 security review (`src/switchyard/modules/scanner/README.md`): the process broker writes output to files,
  caps it, decodes leniently and kills the whole process tree on timeout; empty output, oversize output and too
  many findings are failures; semgrep messages are not stored; one scan at a time; skipped scheduled runs are
  audited.

## [0.10.0] - 2026-11-20

Phase M9: dashboard, reporting and notifications.

### Added
- ADR-0009: `notify` broker (`ctx.notify.send`), `report show {kind}` (health, usage, security, changes), control API
  started by the Hermes adapter when `[api] enabled`, API responses redacted.
- Bundled `inbox` module (M9) and a Switchyard dashboard tab (`dashboard/`: modules, inbox, reports).

### Security
- M9 security review (`src/switchyard/modules/inbox/README.md`): the API Hermes starts serves a dashboard profile
  only (no grants or config); severity-aware inbox pruning; redact before truncating; redacted API errors;
  reserved module ids; no address reuse on the API port; a failed API start no longer stops the tick.

## [0.9.0] - 2026-11-20

Phase M8: token economy (trimming).

### Added
- ADR-0008: `hermes.output` capability and deletion-only output transforms (`ctx.hermes_transform`): modules choose
  lines, the core rebuilds output and always keeps errors, exit codes and paths.
- Bundled `trimmer` module (M8): shortens long terminal and tool output; reduction measured on recorded fixtures.

### Security
- M8 security review (`src/switchyard/modules/trimmer/README.md`): linear-time must-keep patterns and long-line
  bound; carriage-return collapse never hides errors; coalesced ranges; fail open over the must-keep cap; more
  exit-code and error forms; progress-only shape dedupe; file-writing tools excluded; hung transforms paused;
  duplicate-key JSON left alone.

## [0.8.0] - 2026-11-20

Phase M7: workers, personas and teams.

### Added
- ADR-0007: `hermes.delegation` capability and a `switchyard` Hermes delegation backend (`ctx.hermes_delegation`);
  `subagent_start` observer hook with a goal digest; `delegated` marker for routed children's requests.
- Bundled `workers` module (M7): worker roles bound to a model pool or a Hermes profile (persona), teams, a
  restart-safe ledger, stuck-worker and repeated-delegation detection.
- Router `explain` takes a `consumer`; requests from routed children are routed within their role's consumer.

### Security
- M7 security review (`src/switchyard/modules/workers/README.md`): routed children's requests are routed and
  charged per request within the role's consumer; paid personas need `llm.paid`; the child marker is consumed
  once, cleared with its owner and removed on `subagent_stop`; ledger pruning covers running rows; goal digests
  fold case and punctuation.

## [0.7.0] - 2026-11-20

Phase M6: supervisor.

### Added
- ADR-0006: `schedule` capability (`ctx.schedule.every`), `core.read` capability (`ctx.core`: module states,
  audit verification), and `pre_llm_call` turn gates (`ctx.hermes_gate`; first reason blocks; fail open).
- Bundled `supervisor` module (M6): scheduled deterministic checks (failed modules, audit chain, quotas, router
  pass-throughs), de-duplicated findings with automatic resolution, `supervisor.alert` events; no LLM calls.
- Router `hard_stop` (opt-in): blocks a turn when only a ruled-out model is left.

### Security
- M6 security review (`src/switchyard/modules/supervisor/README.md`): the router gate blocks only with positive
  registry knowledge and works with Hermes's real `pre_llm_call` arguments; gates return reason codes and the
  core writes the block message; scheduled jobs run time-bounded on per-module workers without the core lock;
  hooks use per-module pools; revoking a required capability deactivates the module; audit verification for
  modules is cached.

### Fixed
- Control API: a request with `Transfer-Encoding` no longer resets the connection on Windows before the `400`.

## [0.6.0] - 2026-11-20

Phase M5: skill activation manager.

### Added
- `hermes.config.write` broker (ADR-0005, `ctx.hermes_config`): allow-listed Hermes config keys written
  through Hermes's public config API, each change backed up, audited, read back and rolled back on failure;
  `revert` restores any backup.
- Bundled `activation` module (M5): skill inventory with prompt cost, presets (names, categories, `*`),
  index-size benchmark, timed presets that restore the previous state, restore and undo.

### Security
- M5 security review (`src/switchyard/modules/activation/README.md`): `plugins.disabled` is not writable;
  ending a preset undoes only its own changes (edits made since are kept, drift audited) and no longer
  depends on backup files; expired presets end before a new one applies; essential skills are never written.

## [0.5.0] - 2026-11-20

Phase M4: metering, quotas and budgets.

### Added
- Bundled `meter` module (M4): counts every Hermes API response by day, hour, provider and model (tokens
  exactly as reported, errors, subagent runs, estimated cost from models.dev prices); opt-in quotas on
  requests, tokens or USD per day or month with thresholds that fire once per period (`meter.threshold`,
  `meter.exhausted`); burn-rate forecast. Stores no text.
- Router cools an exhausted quota's scope down until the period ends.
- Manifest `capabilities.optional`: requested capabilities that auto-start does not wait for.

### Changed
- Bridge (ADR-0004 decision 6): observer hooks hand modules metadata only (no message text, conversation,
  tool traces or raw SDK objects); `subagent_stop` is forwarded.
- CI: CodeQL runs through GitHub's default setup; the conflicting advanced job was removed.

### Security
- M4 security review (`src/switchyard/modules/meter/README.md`): observer payloads use an allow-list (a
  Hermes lease token was forwarded); the router applies exhausted quota scopes on every path and audits
  pass-through; `llm.free` is checked on every request; quota changes are serialized with threshold checks.

## [0.4.0] - 2026-11-20

Phase M3: router and failover.

### Added
- Hermes hook bridge (ADR-0004): modules granted `hermes.hooks` observe `pre_llm_call`, `pre_api_request`,
  `post_api_request`, `api_request_error`, `post_llm_call` and register `llm_request` middleware that may
  change only the request's `model`; failures are isolated and audited. `ctx.call` runs another module's
  read-only action; `ctx.has(capability)` checks a grant without an audit record.
- Bundled `router` module (M3): picks the model for each Hermes request from the consumer's registry pool
  within the active provider: tiers T1-T5 by request size, free and self-hosted first, paid only with the
  `llm.paid` grant + a tier rule + daily budget (each paid choice audited), pins, failover with cool-down
  across Hermes retries, bounded per turn. Decisions keep no prompt text.

### Security
- M3 security review (`src/switchyard/modules/router/README.md`): failover now cools down the resource
  actually sent; a paid configured model can no longer bypass the paid gate on pass-through; bridge
  callbacks get deep copies, only `model` is adopted, calls are time-bounded (2 s); paid choice and charge are
  atomic; request-caused 4xx errors no longer cool resources down.

## [0.3.0] - 2026-11-19

Phase M2: resource registry and pools.

### Added
- `ctx.fs` file-read broker for `fs.read` (ADR-0003): absolute regular files only, size-capped, JSON depth
  limit, audited by path.
- M2 bundled `resources` module: registry of models, endpoints, agents and tools; pools; consumer bindings;
  `resolve`; reviewed imports (preview, then human apply) from the Hermes models.dev cache and catalog files;
  imported resources start disabled.

### Security
- M2 security review (`src/switchyard/modules/resources/README.md`): `ctx.fs` refuses UNC and device paths on
  Windows and checks the grant before any file-system call (a UNC path could leak NTLM credentials); the model
  can no longer choose import paths; JSON is screened before parsing; one pending import per source; failed
  reads are audited.

## [0.2.0] - 2026-11-19

Phase M1: secrets.

### Added
- Module actions (`ctx.register_action`, operation `module action`; the Hermes model tool runs read-only
  actions only) and module-provided secret backends (`ctx.provide_secret_backend`,
  `contributes.secret_backends`; trusted in-process modules only). ADR-0002.
- M1 bundled `secrets` module: Windows Credential Manager (ctypes), macOS keychain (read), Secret Service
  via `secret-tool`, Vaultwarden via `bw`, development env backend (off by default); age and expiry by name;
  rotation of generated values; `secrets.status` panel. No new dependencies.
- `ctx.config`, `ctx.spawn` (process broker), `ctx.audit`; `run_contract(settings=...)`; `[modules.<id>]`
  tables in `config.toml`. Auto modules wait for their grants instead of failing.

### Security
- M1 security review (`src/switchyard/modules/secrets/README.md`): helper programs are never taken from the
  working directory (Windows `shutil.which` searched it first, exposing `BW_SESSION` to a planted `bw.cmd`);
  rotation refuses when an earlier backend still serves the name; action results are redacted as values;
  stricter manifest, settings and argument checks.

### Fixed
- The control API answers `PUT`, `PATCH`, `DELETE` and `OPTIONS` with a JSON 501 after reading the body.

## [0.1.0] - 2026-11-19

Phase M0: the core framework.

### Added
- `switchyard` package (phase M0, part 1): data-directory resolution, core configuration (`config.toml`),
  manifest loader returning a typed `Manifest` with entry-path containment checks, error hierarchy.
- Policy engine (default deny, manifest-bounded grants, `deny:<capability>` module policies, host and
  secret-name allow-lists, audited decisions) and `ModuleContext` (declared streams and panels only,
  namespaced events, capability-gated brokers, `close()` revokes the context).
- State store (SQLite WAL, transactional numbered migrations with backup, persistent grants, module tables
  confined by the SQLite authorizer) and hash-chained audit log (fsync per record, rotation, head anchor
  for truncation detection, redaction, fail-closed on a torn last record).
- Event bus (typed dotted names, per-handler data copies, isolated and audited handler failures, depth
  limit) and scheduler (time/every, 5-field cron, event, usage and capacity triggers; one run at a time,
  minimum interval, counted skips).
- Module lifecycle manager (T1): discovery with trust roots, per-module import packages, fail-closed
  activation and health, idle stop for auto modules, persistent modes, removal with or without data;
  JSON Lines log sink with redaction; panel registry; `ctx.state`.
- T2 subprocess host: length-prefixed JSON-RPC over stdio (1 MiB frames), scrubbed child environment,
  per-call timeouts, child killed on any protocol violation; module context proxied through the same
  policy and confinement checks as in-process modules.
- Secrets broker interface: `secret://` references, policy-checked use with fail-closed backends, leak
  blocking on results, no value in exception context or traceback locals, redactor with default token
  patterns; test-only memory backend.
- Host profiler (CPU, RAM, disk, GPU hint; `tiny`/`laptop`/`workstation`/`server`) and capacity metrics
  for capacity triggers, without subprocesses or network calls.
- `Core` (wires every component for one data directory; audit head anchor kept in `state.db` and
  checked at startup) and the shared operations table used by the CLI, the API and Hermes.
- `switchyard` CLI generated from the operations table (routes through a running daemon, offline-safe
  operations run directly) and the hardened loopback control API (`switchyard api serve`).
- Hermes plugin adapter: model tools (read and run only; no grants), `/switchyard` slash command,
  `hermes switchyard` CLI command, daily audit verification, redaction patterns; validated with
  `hermes plugins validate`. One hosting process per data directory via an OS file lock.
- Update control for git-installed modules: pinned commit fetch (https only, no hooks, verified HEAD),
  staged manifest checks (same id, same pinned source), swap with health check and automatic rollback,
  manual rollback.
- Module contract suite `switchyard.contract.run_contract`; the template module passes it in-process and
  under the subprocess host. End-to-end M0 acceptance tests across CLI, API and Hermes adapter.
- Coverage gate (90%) on `src/switchyard`; mypy strict and bandit now include `src/`.

### Changed
- The manifest schema moved to `src/switchyard/schemas/module.schema.json` so it ships in the wheel.
  `tools/validate_manifest.py` is now a thin CLI over `switchyard.manifest`.

### Fixed
- Module ids containing `__` are rejected; they could have collided with another module's state tables.
- Schema `pattern` checks used Python's `$`, which accepts a trailing newline; they now follow JSON Schema
  semantics (a module id such as `"example\n"` is rejected).
- Module SQL could not use `count(*)`: SQLite reports no database name for that read, and the authorizer
  denied it.

### Security
- M0 security review (section 6 of `docs/modules/m0-core.md`): module SQL statements now have a work budget
  and a 10 000-row result cap; staged updates containing symlinks are refused; on Windows the API token file
  gets a single-user ACL (inheritance removed), and the server refuses to start if that fails.

## [0.0.1] - 2026-11-19

Repository bootstrap (phase P0). No runtime code.

### Added
- Design, build plan, module catalog, pre-engagement Q&A and third-party license review.
- Module manifest schema, stdlib validator, module template and contract tests.
- CI, security scanning, release and Dependabot configuration.

### Changed
- Tooling is installed from a hash-pinned `requirements-dev.txt`; `ci-required` and `security-required` gate jobs added.
- Secret scanning runs the pinned gitleaks CLI. Repository moved to the `vicberger-com` organization.

[Unreleased]: https://github.com/vicberger-com/hermes-switchyard/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/vicberger-com/hermes-switchyard/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.13.0...v1.0.0
[0.13.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/vicberger-com/hermes-switchyard/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/vicberger-com/hermes-switchyard/releases/tag/v0.0.1
