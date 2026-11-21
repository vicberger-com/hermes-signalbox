# Pre-work Q&A: H1 hardening after the v1.0.0 evaluation

Date: 2026-11-20. Previous phase: R1, tag v1.0.0. Target tag: v1.0.1.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`. Rules for this kind of phase:
[BUILD-PLAN.md](../BUILD-PLAN.md) "Maintenance phases". Review material: [h1/](h1/README.md).

Read this file from top to bottom before the first change. It is written to be followed without the
conversation that produced it.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| R1 | Per-phase and whole-system reviews by the building agent still left failure paths under-tested | An evaluation by separate reviewers was run on the release: 102 findings (0 Critical, 5 High, 31 Medium, 51 Low, 15 Info) |
| R1 | The release was tagged `Production/Stable` without ever running inside a real Hermes or being installed anywhere | H1 changes the classifier to Beta; H2 does the first real install |
| R1 retro | "Always review a fix diff before release" | H1 closes with a fresh review of the fix diff |
| R1 | Tag signing deferred (needs an operator-created key) | Still deferred; H1 adds a release test gate and tag protection instead |
| Evaluation | The first-run steps in the user guide fail as written | A CI job runs the guide's commands from now on |
| Evaluation | On a Windows host with Hermes Desktop, the `git` found first on `PATH` cannot be run by this process, so git-based update operations are disabled there and three tests skip | WP4; a skip allow-list in CI (WP3) |
| Evaluation | `docs/DESIGN.md` section 6 lists Hermes mechanisms the code does not use | Corrected in WP10; the unused ones are recorded as planned |

## 2. Research record

| Topic | Source (URL, commit or version, date read) | Finding |
|---|---|---|
| Hermes release state | GitHub API `repos/NousResearch/hermes-agent/releases`, read 2026-11-20 | v0.23.3 published 2026-11-19 (about 370 pull requests since v0.23.2; storage layer moved behind a persistence interface; tool-result pruning on by default). The design was verified against v0.23.2 only |
| Hermes advisories | `repos/NousResearch/hermes-agent/security-advisories`, read 2026-11-20 | GHSA-p22p-9ph6-gmrh (high, 2026-11-19) affects `>= 0.21.6, < 0.23.2`; patched in 0.23.2 |
| Hermes hooks available | installed v0.23.2 `hermes_cli/plugins.py` `VALID_HOOKS`, read 2026-11-20 | `pre_tool_call`, `post_tool_call`, `pre_approval_request`, `pre_verify`, kanban hooks, `on_skill_lifecycle`, `post_compaction` exist; Switchyard uses none of them |
| Hermes features overlapping modules | installed v0.23.2 `hermes --help`, read 2026-11-20 | `hermes secrets` (Bitwarden, 1Password), `hermes security audit` (OSV), `hermes fallback`, `hermes auth` (credential pools), `hermes pause`, `hermes egress`, `hermes kanban`, Docker terminal backend. Not H1 scope; input for later phases |
| Published wheel | release asset `hermes_switchyard-1.0.0-py3-none-any.whl`, read 2026-11-20 | Checksum matches `SHA256SUMS`; 85 entries; no `dashboard/`, no `plugin.yaml`, no `py.typed` |
| Local gates on `a141ec0` | run 2026-11-20, Windows, Python 3.11.15 | 671 passed, 10 skipped, 94.39% branch coverage; ruff, format, mypy strict, bandit, pip-audit clean |
| `llm_request` middleware contract (WP1) | installed v0.23.2 `hermes_cli/middleware.py` `apply_llm_request_middleware`, `agent/turn_api_request.py` lines 158-176, read 2026-11-20 | Middleware may return `{"request": ...}` to replace the provider kwargs; it cannot refuse. An exception is logged and the request is sent unmodified. Context keys: `task_id`, `turn_id`, `api_request_id`, `session_id`, `platform`, `model`, `provider`, `base_url`, `api_mode`, `api_call_count`. `llm_execution` middleware wraps the call and could refuse it (not used; a feature). `pre_llm_call` runs once per turn (`agent/turn_context.py`). Api modes: `chat_completions`, `anthropic_messages`, `codex_responses`, `bedrock_converse`, `codex_app_server` |
| Dashboard discovery for pip-installed plugins (WP3) | installed v0.23.2 `hermes_cli/web_server_dashboard.py` `_discover_dashboard_plugins` and `hermes_cli/plugins_discovery.py` `discover_entrypoint_manifests`, read 2026-11-20 | Dashboard tabs come only from `<plugins root>/*/dashboard/manifest.json` (user, bundled, project plugin directories); entry-point plugins get a metadata-only manifest and no dashboard. Decision D6 is therefore implemented as: ship `plugin.yaml` and `dashboard/` in the wheel under `switchyard/_plugin/`, and document that the tab needs `hermes plugins install` |
| GitHub settings with the repository token (WP3) | `POST repos/.../rulesets`, `PUT repos/.../environments/release`, 2026-11-20 | HTTP 403 "Resource not accessible by personal access token" for both; recorded in `BLOCKERS.md` B-H1-1 |
| Upload/download artifact actions (WP3) | GitHub API `repos/actions/{upload,download}-artifact/releases/latest`, 2026-11-20 | upload-artifact v7.0.2 (`cf430e0`), download-artifact v8.0.2 (`9000827`), both published 2026-10-07; pinned by SHA |
| Python versions (WP3) | `uv python list`, 2026-11-20 | 3.14.10 current; 3.15.2 is released. CI now covers 3.11 to 3.14 as the finding asks; 3.15 is a backlog item |
| To do in the phase | each work package | Before relying on a Hermes hook, keyword argument or loader rule, read it in the installed source and add a row here (WP1: `llm_request` middleware contract; WP3: how a pip-installed plugin's dashboard files are found; WP8: `post_api_request` keyword set) |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Scope | (a) all High and Medium, plus Low items that are cheap and adjacent; (b) High only; (c) everything | (a): Medium items include every security finding of substance; fixing all 66 Low and Info items would turn a patch into a rewrite | default accepted (operator, 2026-11-20) |
| 2 | Version | (a) v1.0.1; (b) v1.1.0 | (a): no feature is added. Behaviour changes that tighten security are listed under `### Changed` with the operator step | default accepted |
| 3 | Router when no route answer arrives in time | (a) fall back to a known free model and never apply a late result; (b) block the turn; (c) pass through and record it | (a), with (b) when hard stop is on and no free model is known, and (c) only as a counted, audited last resort. Needs ADR-0013 | default accepted (operator) |
| 4 | Release integrity | (a) test gate, tag ruleset, protected environment now, signing when a key exists; (b) wait for the key | (a) | default accepted (operator) |
| 5 | Maturity label | (a) Beta until it has run in a real profile; (b) keep Stable | (a) | default accepted (operator) |
| 6 | pip install route | (a) ship dashboard files and `plugin.yaml` in the wheel; (b) document git install as the only route with a dashboard | (a), after reading how Hermes finds them for a pip-installed plugin | default accepted (operator) |
| 7 | Model's reach over module state | (a) the model may activate only `auto` modules, and no actor may activate while required grants are missing; (b) leave as is | (a) | default accepted (operator) |
| 8 | Design text versus code (Hermes mechanisms listed but unused) | (a) correct the design now, build the tool-call guard later as a module; (b) build now | (a): a tool-call guard is a feature | default accepted (operator) |
| 9 | Real-Hermes test | (a) CI job with a pinned Hermes release; (b) contract fixture recorded from the installed source; (c) none | (a); (b) only if Hermes cannot be installed in CI, with the reason recorded here | (a) implemented in WP11. PyPI stops at 0.19.0 and Hermes refuses wheel builds, so CI checks out tag v0.23.2 and runs `uv sync --frozen` (Python 3.14, as its lock requires) |
| 10 | First real install | (a) a dedicated test profile; (b) the default profile | (a), in H2 | default accepted (operator) |
| 11 | New dependencies | | None expected. Any CI-only tool is pinned and hash-locked like the rest | default accepted |
| 12 | Core contract changes (ADR) | | ADR-0013 (router timeout behaviour). Activation rule change is recorded in `docs/modules/m0-core.md` and DESIGN section 5; add an ADR if the lifecycle states change | default accepted |
| 13 | Operator input needed | | A signing key (deferred). Possibly owner rights for the tag ruleset and the release environment: try with the repository token first | open until tried |
| 14 | Security review at phase close | (a) fresh read-only reviewers on the fix diff, every finding re-verified by the main model; (b) none | (a) | default accepted |
| 15 | Single maintainer (finding D-13) | | Accepted, documented: pull requests still require the two gate checks. Revisit when a second maintainer joins | default accepted |

## 4. Work packages

One pull request each, in this order. "IDs" are defined in [h1/findings-index.md](h1/findings-index.md).
Must items first; should items of a package only after its must items are in review. Every code pull request
adds a `[Unreleased]` changelog entry and the regression tests for its IDs.

| WP | Branch | Area | Must IDs | Should IDs | Required end state (public summary) |
|---|---|---|---|---|---|
| WP0 | `docs/h1-prework` | This plan | | | Merged before any code |
| WP1 | `fix/h1-router` | Router | C-1, C-4, C-8 | | ADR-0013 merged; regression tests for each ID |
| WP2 | `fix/h1-cli-guide` | User guide, CLI, daemon files | D-1, D-7, D-8, D-9, D-10 | D-20, D-26, B-20, B-24 | The guide's commands succeed as written, in CI; failed results exit non-zero; a denial names the capability; the resolved data directory is shown; no stale daemon files after exit |
| WP3 | `ci/h1-release-gate` | Release and packaging | D-3, D-5, D-6, D-12 | D-23, D-24, D-25 | Release needs a passing verify job and a tag on `main`; CI builds and smoke-tests the wheel; the wheel carries the dashboard files and `plugin.yaml`; skip sets are checked per OS |
| WP4 | `fix/h1-git-resolution` | Program lookup | D-2 | D-15 | `git` is found and runs on a Windows host with Hermes Desktop; the git tests no longer skip there |
| WP5 | `fix/h1-activation` | Activation rules | C-6, A-5, C-7 | | Question 7 implemented; lifecycle text matches the code |
| WP6 | `fix/h1-core-trust` | Core trust layer | A-1, A-3, A-4, A-6, A-7 | A-15, A-18, A-19, A-21, A-22, C-15 | Regression tests for each ID |
| WP7 | `fix/h1-failure-paths` | Updates, process broker, subprocess host | B-1, B-2, B-3, D-11 | B-11, B-14, B-21, D-27 | Regression tests for each ID, including the two missing subprocess-host kill-path tests |
| WP8 | `fix/h1-hot-path` | Bridge, trimmer, meter | C-2, C-3, C-5 | C-9, C-10, C-16 | Regression tests for each ID |
| WP9 | `fix/h1-audit` | Audit log and startup | A-2, A-8, A-9, A-10, A-11 | A-12, A-13, A-14, B-4 | Regression tests for each ID |
| WP10 | `chore/h1-hygiene` | Documentation and metadata | D-14 | A-26, A-28, C-11, C-12 (= D-17), C-13 (shared helpers only; no module splits), D-16, D-18, D-19 | Classifier is Beta; DESIGN section 6 lists only what the code uses; one test asserts all version fields agree |
| WP11 | `test/h1-real-hermes` | Integration test | D-4 | | Question 9 implemented |
| Close | `chore/release-1.0.1` | Phase close | | | Section 5 all ticked; tag `v1.0.1` |

Backlog items (class "Backlog 1.1" in the index) each get one issue with label `backlog` and milestone `1.1`,
titled without describing an unfixed weakness. They are not fixed in H1.

Phase H2 (after the tag): install into a Hermes profile named `switchyard-test`; run real turns with the
router, meter and trimmer active; compare metered usage with provider-reported usage; run the offload
connectors against real local services; update that profile to the current Hermes release and re-verify the
adapter; measure per-call overhead. Results are appended to this file under a new heading.

## 5. Acceptance tests (written before code)

- [ ] `tests/acceptance/test_h1_acceptance.py` exists with one test per must ID, each named `test_h1_<id>_...`
      (for example `test_h1_c1_...`), driven through a public surface where one exists.
- [ ] Each must ID is fixed with a regression test that failed before the fix, or has a disposition in section 6.
- [ ] The guide walkthrough job runs every command in `docs/USER-GUIDE.md` sections 2, 3, 6, 7 and 8 against a
      temporary data directory and fails on a non-zero exit or a `status: failed` result.
- [ ] The wheel built in CI contains the files listed in an expected manifest, installs into a clean
      environment, and `switchyard version` prints the version in `pyproject.toml`.
- [ ] `pytest -rs` skip sets equal the per-OS allow-list on Linux, Windows and macOS.
- [ ] All gates in `docs/BUILD-PLAN.md` pass on Python 3.11, 3.12, 3.13 and 3.14.
- [ ] A release cannot be published from a tag that is not on `main` or whose verify job failed (checked by
      reading the workflow and at the `v1.0.1` tag).
- [ ] `docs/DESIGN.md`, `docs/USER-GUIDE.md`, `docs/REFERENCE.md`, `docs/modules/m0-core.md` and the module
      READMEs match the code after every package (link check passes).
- [ ] The fix-diff security review has run and each of its findings is fixed or dispositioned.
- [ ] Every "Backlog 1.1" ID has an issue number recorded in the index.

## 6. Dispositions (fill in as each package merges)

| ID | Disposition (Fixed / Fixed (adapted) / Not reproduced / By design / Accepted, documented) | Pull request | One-line reasoning |
|---|---|---|---|
| D-13 | Accepted, documented | WP0 | Single-maintainer project; both gate checks are required on every pull request |
| D-21 | No action | - | Stale metadata in one local environment only; refreshed 2026-11-20 |
| C-1 | Fixed | #78 | ADR-0013: bridge fallback and claim, router fallback from remembered candidates, 1 s store budget |
| C-4 | Fixed | #78 | Cool-down upsert keeps the later end and the quota reason |
| C-8 | Fixed | #78 | All text keys sized; unknown shape is T5 |
| D-1 | Fixed | #79 | Guide grants `ui.panel`; table of capabilities needed to start; walkthrough test runs the guide on every CI OS |
| D-7 | Fixed | #79 | Guide step 0 is `switchyard api serve`; `[daemon]` marks in `--help`, the guide and REFERENCE |
| D-8 | Fixed | #79 | Failed results exit 1 naming the missing grants; `missing_grants` in list/show; inactive panel message |
| D-9 | Fixed | #79 | SIGTERM/SIGBREAK handlers; client clears files left by a dead daemon under `host.lock`; 0.5 s connect timeout |
| D-10 | Fixed | #79 | Guide section 2 explains the two stores; `config show` prints `data_dir_source` |
| D-20 | Fixed | #79 | Description lists only the enum's actions; test keeps them equal |
| D-26 | Fixed | #79 | Unknown capability exits 2; dotted nested output; readiness line flushed |
| B-20 | Fixed | #79 | `_unsupported` runs the Host/Origin check first |
| B-24 | Fixed | #79 | `handle_error` is silent for dropped connections, one line (class only) otherwise |
| D-3 | Fixed (adapted) | #80 | `verify` job (tag on `main`, annotated, matches version, full gate, wheel check) gates `release`; notes from the CHANGELOG. Tag signing deferred (D2); tag ruleset and environment protection need the owner (B-H1-1) |
| D-5 | Fixed (adapted) | #80 | `py.typed`, `plugin.yaml` and `dashboard/` in the wheel; Hermes 0.23.2 shows the tab only for directory installs, documented in the guide |
| D-6 | Fixed | #80 | CI `package` job: wheel and sdist built, file list checked, clean install and CLI smoke test; release SBOM from a clean environment with only the wheel |
| D-12 | Fixed | #80 | Per-OS skip allow-list enforced in CI; FileLock timeout test runs on every OS |
| D-23 | Fixed | #80 | CI matrix 3.11 to 3.14; leaking SQLite connections in tests closed |
| D-24 | Fixed | #80 | `tools/release_notes.py` feeds `--notes-file`; compare links in the CHANGELOG; post-tag changes under `[Unreleased]` |
| A-5 | Fixed | #82 | Activation refuses while required grants are missing, before importing module code; no `granted` state added, DESIGN and m0-core lifecycle text corrected |
| C-6 | Fixed | #82 | `module activate` refuses the model actor unless the mode is `auto` (`policy.denied`, reason `mode manual`) |
| C-7 | Fixed | #82 | Reproduced: an unregistered persona model went out uncharged. Delegated requests now treat unknown models as paid (steer to free, else counted pass-through); main session unchanged (M6 rule) |
| A-1 | Fixed | #83 | Explicit data directory beats `SWITCHYARD_DATA_DIR`; the contract cannot touch the real store |
| A-3 | Fixed | #83 | Reproduced with a junction. `X.py` beside `X/` rejected at load; module file checked after import (T1 and T2) |
| A-4 | Fixed | #83 | Contract `trust` check; `bundled=True` opt-in for this repository's modules and the template |
| A-6 | Fixed | #83 | `register` removes stored grants no longer requested (audited `policy.revoked`) |
| A-7 | Fixed | #83 | `Core.run` passes every result through `Redactor.redact_obj` |
| A-15 | Fixed | #83 | `require_host` / `require_secret` deny when the module was unregistered mid-check |
| A-18 | Fixed | #83 | Backend exceptions become `SecretUnavailable` with the class name; `secret.backend_error` audited |
| A-19 | Fixed | #83 | `cross_field` checks the `policies` grammar |
| A-21 | Fixed | #83 | Contract reads the grant store (`PolicyEngine.stored_grants`) |
| A-22 | Fixed | #83 | `ModuleContext.close` runs every cleanup step and re-raises the first error |
| C-15 | Fixed | #83 | One trailing newline stripped from `bw get` |
| B-1 | Fixed | #84 | Swap wrapped: a failed rename restores the previous directory, restarts it and audits `module.rolled_back`; `_restart` treats any exception as failure |
| B-2 | Fixed | #84 | `Operation.locked=False` for update, preview, check_updates; the swap runs under the core lock via `swap_guard`; per-module update lock; `ls-remote` 60 s |
| B-3 | Fixed | #84 | stdin written on a thread inside the same deadline; 1 MB input cap; kill and audit on every failure path |
| B-11 | Fixed | #84 | `.pyd .so .dylib .dll .pyw` refused, suffix compared case-insensitively |
| B-14 | Fixed | #84 | `Channel.request` sets the deadline before the send; the T2 writer waits at most the call's remaining time |
| B-21 | Fixed | #84 | `_number` requires `math.isfinite` |
| D-11 | Fixed | #84 | Regression tests for the T2 flood kill and the stalled-writer kill |
| D-27 | Fixed | #84 | Vacuous assertion replaced by a status check |
| C-2 | Fixed | #85 | Breaker per module (3 timeouts: 60 s pause, audited once); 4 in-flight calls max; observers share one deadline |
| C-3 | Fixed | #85 | `trim.normalise` / `must_keep` take a deadline (0.5 s per step); past it the transform fails open, audited `core.transform_skipped` |
| C-5 | Fixed | #85 | Bridge remembers the model sent per `api_request_id` and passes `sent_model` to `post_api_request` / `api_request_error` observers; meter uses it first |
| C-9 | Fixed | #85 | `core.adapter_error` once per hook and class, warning logged; gate dispatch separated from observer dispatch |
| C-10 | Fixed | #85 | Finite float counts are rounded |
| C-16 | Fixed | #85 | `health()` is read-only; expiry at the next turn or apply/restore |
| A-2 | Fixed | #86 | `PolicyEngine._deny`/`_refuse` clip values to 1000 characters with a `[+N chars]` marker; the denial is always recorded |
| A-8 | Fixed | #86 | `tail` and `_iter_lines` split on `\n` only |
| A-9 | Fixed | #86 | Torn tail repaired on open (`audit.torn_tail_repaired`); `verify` requires the final newline; docstring corrected |
| A-10 | Fixed | #86 | `Core.__init__` releases the host lock and closes the store on any start failure; `StateStore` closes its connection if a pragma fails |
| A-11 | Fixed | #86 | `ack_audit`: append, re-anchor, then clear the flag |
| A-12 | Fixed | #86 | `verify_directory` reads bytes and reports decode errors and `RecursionError` as `unparseable record` |
| A-13 | Fixed | #86 | `_recover` widens its window until the last record is whole; `MAX_RECORD_BYTES` 128 KiB |
| A-14 | Fixed | #86 | Write loop; zero progress raises `AuditError` without advancing the chain |
| B-4 | Fixed | #86 | Header fields cut to 256 characters; an over-long line is re-serialised with `{"truncated": true}` |
| D-14 | Fixed | #87 | Classifier `4 - Beta`; support and deprecation policy in SECURITY.md |
| A-26 | Fixed | #87 | m0-core section 4 lists what the bus actually publishes; `policy.denied` is audit-only |
| A-28 | Fixed | #87 | m0-core disposition corrected: CTEs allowed, bounded by the work budget and row cap |
| C-11 | Fixed | #87 | README and docstrings say `import_preview` is operator-only (code unchanged; matches R1) |
| C-12 | Fixed | #87 | Same as D-17 |
| C-13 | Fixed | #87 | `switchyard.modkit`: `StateTables` (7 modules), `int_setting` (5), `default_models_dev_cache` (2); no module splits |
| D-16 | Fixed | #87 | Pre-commit revs frozen to ruff v0.17.6 and gitleaks v8.30.1 (CI versions); note removed; test |
| D-17 | Fixed | #87 | Dashboard manifest 1.0.0; test that all version fields agree |
| D-18 | Fixed | #87 | Moved to `docs/qa/2026-11-20-docs-gap-audit-r1.md` with a historical note |
| D-19 | Fixed | #87 | "Generated" wording dropped; missing flags, directory, events and states added; test checks every operation |
| D-4 | Fixed | WP11 | `tests/integration/test_real_hermes.py` + CI job `hermes-integration` (Hermes v0.23.2 at `ae2a81c`, `uv sync --frozen`, Python 3.14); required by `ci-required`. The acceptance file keeps its name (M0 scope); the 1.0 integration coverage is the new file |
| D-25 | Fixed | #80 | `hatchling>=1.27,<2` in `[build-system]` |
| D-2 | Fixed | #81 | `find_runnable` tries each `PATH` candidate with `--version`; `[tools] git` override; `config show` names it; git tests run on this workstation |
| D-15 | Fixed | #81 | Test forces an absolute working-directory hit on every OS; shared `_outside_cwd` check also guards `program_candidates` |

Changes visible to existing users (complete this list; it becomes the `### Changed` section):

- The model can no longer activate a module whose mode is `manual` (WP5).
- A module cannot be activated while a required capability is not granted (WP5).
- Commands that return a failed result exit with status 1; an unknown capability name exits with status 2 (WP2).
- The classifier changes from Production/Stable to Beta (WP10).
- For delegated subagents, a model the registry does not know is treated as paid (WP5, C-7).
- A request with no recognised text key is routed as tier T5 (WP1). With `hard_stop`, the turn after a slow
  route that let a paid model through is blocked once (WP1).

## 7. Retro (fill in after release)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
| A release that passes its own gates is ready to be called stable | It had never been installed or run in a real Hermes | Maturity label; H2 exists |
| The user guide was correct because it was written from the code | Its first activation example was never executed | Guide commands now run in CI |
