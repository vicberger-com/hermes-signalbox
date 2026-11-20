# Changelog

Format: Keep a Changelog. Versions: Semantic Versioning.

## [Unreleased]

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
