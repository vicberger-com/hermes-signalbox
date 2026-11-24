# Build plan

Executed by a Hermes agent under [AGENTS.md](../AGENTS.md). Order is fixed: core first, then one module at a time.

## Phase order

| Phase | Deliverable | Depends on | Tag |
|---|---|---|---|
| P0 | Repository bootstrap: push template, branch protection, CI green, actions pinned to commit SHAs | operator: repo + token | v0.0.1 |
| M0 | Core framework | P0 | v0.1.0 |
| M1 | Secrets broker and backends | M0 | v0.2.0 |
| M2 | Resource registry and pools | M1 | v0.3.0 |
| M3 | Router and failover | M2 | v0.4.0 |
| M4 | Metering, quotas, budgets | M2 | v0.5.0 |
| M5 | Skill and plugin activation manager | M0 | v0.6.0 |
| M6 | Supervisor (free-resource background manager) | M3, M4, M5 | v0.7.0 |
| M7 | Worker, persona and team management | M3 | v0.8.0 |
| M8 | Token economy (output reduction, compaction) | M0 | v0.9.0 |
| M9 | Dashboard, reporting, notifications | M4 | v0.10.0 |
| M10 | Security testing connectors | M0 | v0.11.0 |
| M11 | Offload connectors (n8n, JevK5, ACP agents, others) | M2, M7 | v0.12.0 |
| M12 | Update, patch and release control for modules | M0 | v0.13.0 |
| R1 | Hardening review, full docs pass, public release | all | v1.0.0 |
| H1 | Hardening after the v1.0.0 evaluation: all High and Medium findings, named Low ones ([Q&A](qa/15-h1-prework.md)) | R1 | v1.0.1 |
| H2 | First real install in a Hermes test profile, real-Hermes CI job, live connector checks, re-verification on the current Hermes release | H1 | none (report in the Q&A) |
| H3 | Maintenance after the evaluation of v1.0.1 plus the 1.1 stabilization ([evaluation](qa/16-h3-eval-prework.md), [Q&A](qa/17-h3-prework.md)) | H2 | v1.0.2 |
| H4 | Maintenance after the v1.0.2 install acceptance: every finding of the first acceptance install ([Q&A](qa/18-h4-prework.md)) | H3 | v1.0.3 |

## Maintenance phases (after 1.0)

A maintenance phase (H1, H2, ...) fixes or verifies what exists; it adds no module and no feature.

1. **Scope comes from a recorded review.** The phase Q&A file lists every finding by ID with its scope class
   (must, should, backlog, no action) and work package. Nothing outside that list is changed; anything else
   noticed becomes a `backlog` issue.
2. **Same loop, smaller steps.** Steps 1 to 9 of the per-phase loop apply. "Spec freeze" becomes: an ADR for
   every change to core behaviour, and corrections to `docs/modules/<id>.md` and the module READMEs.
3. **One work package is one pull request**, in the order the Q&A gives. Tests first: each finding gets a
   regression test that fails before the fix.
4. **Triage before fixing.** Reproduce each finding in a test. A finding that does not reproduce is recorded
   as "Not reproduced" with the test and the reason; it is not fixed by guesswork.
5. **Unfixed security detail stays out of this repository.** Findings about the security of a released
   version are listed here by ID, severity, component and work package only. Their mechanism, evidence and
   reproduction live in the maintainer's private record until the fix is merged; pull request titles and
   commit messages refer to the ID. Dispositions are published in the phase Q&A when the fix merges, as in
   earlier phases.
6. **Behaviour changes in a patch release** are allowed only when they tighten security or correct documented
   behaviour. Each is listed under `### Changed` in the changelog with the step an operator must take.
7. **Phase close** is the same as a module phase: acceptance tests, a fresh security review of the fix diff,
   retro, release pull request, tag.

## Per-phase loop

Run every step; do not skip to code.

1. **Research.** Current state of each upstream source for this phase (commits, releases, advisories, license),
   Hermes API changes since the last phase, and current best practice for the problem. Use the fast route for
   collection. Record sources.
2. **Pre-work Q&A.** Copy `docs/qa/TEMPLATE-module-prework.md` to `docs/qa/NN-<phase>-prework.md`. Answer every
   question; choose the recommended option; note what changed because of earlier phases.
3. **Spec freeze.** Write `docs/modules/<id>.md`: interfaces, events, state schema, capabilities, threat notes,
   acceptance tests. Update `docs/DESIGN.md` only if the core contract changes (needs an ADR in `docs/adr/`).
4. **Tests first.** Acceptance and unit tests that fail for the right reason.
5. **Implement.** Smallest code that passes. Reuse per `docs/THIRD-PARTY.md`; attribute in `NOTICE`.
6. **Security review.** Run the gate below. A second pass by a fresh subagent with only the diff and the threat
   notes.
7. **Docs and SBOM.** Module README, user guide page, changelog entry, regenerated SBOM, license report.
8. **PR, CI, merge, tag.** Conventional commit title. Verify checks with `gh pr checks`; verify merge state.
9. **Retro.** Append lessons and changed assumptions to the Q&A file. These seed the next phase's Q&A.

## Gates (all must pass to merge)

| Gate | Tool or check |
|---|---|
| Lint and format | ruff |
| Types | mypy strict on `src/` |
| Tests | pytest on Linux, Windows, macOS; coverage >= 90% for core, >= 85% for modules |
| Manifest | `tools/validate_manifest.py` on every `module.toml` |
| Static security | bandit, CodeQL (GitHub default setup, public repo), semgrep rules when M10 lands |
| Secrets | gitleaks on the full history |
| Dependencies | pip-audit clean or documented exception with expiry; license allow-list |
| SBOM | CycloneDX JSON generated and attached |
| Docs | Every public function, tool, command, config key and event documented |
| Security behaviour | Denied-capability test, secret-never-in-output test, audit-chain test |

## Definition of done for a module

Works standalone and inside Hermes; can be enabled, disabled, updated and removed without restart of the core;
has its own panel or settings section, log stream, health check and report section; holds no capability it does
not use; ships tests, docs and SBOM entries; leaves no state behind on removal unless the user keeps it.

## P0 tasks

1. Operator creates the repository and the scoped token (see `docs/qa/00-pre-engagement.md`, items A1 to A4).
2. Push `main`. Enable branch protection (PR required, checks required, no force push), Dependabot alerts,
   secret scanning and push protection, private vulnerability reporting.
3. Pin every GitHub Action to a full commit SHA (the template uses version tags as placeholders).
4. Create a `uv.lock` (or hashed requirements) for dev tooling. Confirm CI green on all three platforms.
5. Decide the Hermes plugin packaging layout (Q&A item C4) and add the adapter skeleton in M0.

## M0 work breakdown

1. Package skeleton `src/switchyard/`, config loader, data directory resolution.
2. Manifest loader and schema validation (replace the template validator with the core implementation; keep the
   CLI entry point).
3. Policy engine and capability grants; `ModuleContext`.
4. State store with migrations; audit log with chain verification.
5. Event bus; scheduler and trigger engine.
6. Module lifecycle (in-process T1), then subprocess host (T2) with JSON-RPC.
7. Secrets broker interface with an in-memory test backend only.
8. Host profiler and capacity profiles.
9. CLI and loopback control API.
10. Hermes plugin adapter: tools, commands, hook wiring, plugin config.
11. Update control skeleton: pinned source, verify, stage, health check, roll back.
12. Example module from `templates/module/` passing the full contract test suite.
