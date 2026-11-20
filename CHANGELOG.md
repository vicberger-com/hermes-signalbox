# Changelog

Format: Keep a Changelog. Versions: Semantic Versioning.

## [Unreleased]

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
- Coverage gate (90%) on `src/switchyard`; mypy strict and bandit now include `src/`.

### Changed
- The manifest schema moved to `src/switchyard/schemas/module.schema.json` so it ships in the wheel.
  `tools/validate_manifest.py` is now a thin CLI over `switchyard.manifest`.

### Fixed
- Module ids containing `__` are rejected; they could have collided with another module's state tables.
- Schema `pattern` checks used Python's `$`, which accepts a trailing newline; they now follow JSON Schema
  semantics (a module id such as `"example\n"` is rejected).

## [0.0.1] - 2026-11-19

Repository bootstrap (phase P0). No runtime code.

### Added
- Design, build plan, module catalog, pre-engagement Q&A and third-party license review.
- Module manifest schema, stdlib validator, module template and contract tests.
- CI, security scanning, release and Dependabot configuration.

### Changed
- Tooling is installed from a hash-pinned `requirements-dev.txt`; `ci-required` and `security-required` gate jobs added.
- Secret scanning runs the pinned gitleaks CLI. Repository moved to the `vicberger-com` organization.
