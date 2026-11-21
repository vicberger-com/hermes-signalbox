# H1 findings index

Every finding of the 2026-11-20 evaluation of v1.0.0, with its disposition. Reviews A, B and C concern the
security of a released version. They are published since the H1 close with the backlog findings withheld
until each is fixed (see [README.md](README.md)). Review D is published in full: [review-D-engineering.md](review-D-engineering.md).

Scope classes: **H1 must** (all High and Medium), **H1 should** (Low or Info, cheap and adjacent; only after the
must items of the same work package), **Backlog 1.1** (one issue each, not fixed in H1), **No action**.

| ID | Severity | Component | Scope | Work package | Description | Status |
|---|---|---|---|---|---|---|
| A-1 | Medium | contract.py, core.py, paths.py | H1 must | WP6 | see [review A](review-A-core.md) | fixed in #83 |
| A-2 | Medium | audit.py, capabilities.py | H1 must | WP9 | see [review A](review-A-core.md) | fixed in #86 |
| A-3 | Medium | host_t2_child.py, lifecycle.py, manifest.py | H1 must | WP6 | see [review A](review-A-core.md) | fixed in #83 |
| A-4 | Medium | contract.py | H1 must | WP6 | see [review A](review-A-core.md) | fixed in #83 |
| A-5 | Medium | lifecycle.py | H1 must | WP5 | see [review A](review-A-core.md) | fixed in #82 |
| A-6 | Medium | capabilities.py | H1 must | WP6 | see [review A](review-A-core.md) | fixed in #83 |
| A-7 | Medium | core.py, lifecycle.py | H1 must | WP6 | see [review A](review-A-core.md) | fixed in #83 |
| A-8 | Medium | audit.py | H1 must | WP9 | see [review A](review-A-core.md) | fixed in #86 |
| A-9 | Medium | audit.py, core.py | H1 must | WP9 | see [review A](review-A-core.md) | fixed in #86 |
| A-10 | Medium | core.py, state.py | H1 must | WP9 | see [review A](review-A-core.md) | fixed in #86 |
| A-11 | Medium | core.py | H1 must | WP9 | see [review A](review-A-core.md) | fixed in #86 |
| A-12 | Low | audit.py | H1 should | WP9 | see [review A](review-A-core.md) | fixed in #86 |
| A-13 | Low | audit.py | H1 should | WP9 | see [review A](review-A-core.md) | fixed in #86 |
| A-14 | Low | audit.py | H1 should | WP9 | see [review A](review-A-core.md) | fixed in #86 |
| A-15 | Low | capabilities.py | H1 should | WP6 | see [review A](review-A-core.md) | fixed in #83 |
| A-16 | Low | config.py, manifest.py | Backlog 1.1 | 1.1 | see [review A](review-A-core.md) | fixed in #142 (backlog #89) |
| A-17 | Low | secrets.py | Backlog 1.1 | 1.1 | see [review A](review-A-core.md) | fixed in #133 (backlog #90) |
| A-18 | Low | secrets.py | H1 should | WP6 | see [review A](review-A-core.md) | fixed in #83 |
| A-19 | Low | capabilities.py, manifest.py | H1 should | WP6 | see [review A](review-A-core.md) | fixed in #83 |
| A-20 | Low | manifest.py | Backlog 1.1 | 1.1 | see [review A](review-A-core.md) | fixed in #149 (backlog #91) |
| A-21 | Low | capabilities.py, contract.py | H1 should | WP6 | see [review A](review-A-core.md) | fixed in #83 |
| A-22 | Low | context.py, lifecycle.py | H1 should | WP6 | see [review A](review-A-core.md) | fixed in #83 |
| A-23 | - | - | No action: withdrawn by the reviewer | - | withdrawn | no action |
| A-24 | Low | secrets.py | Backlog 1.1 | 1.1 | see [review A](review-A-core.md) | fixed in #133 (backlog #92) |
| A-25 | Low | state.py | Backlog 1.1 | 1.1 | see [review A](review-A-core.md) | fixed in #151 (backlog #93) |
| A-26 | Info | capabilities.py, m0-core.md | H1 should | WP10 | see [review A](review-A-core.md) | fixed in #87 |
| A-27 | Info | context.py | Backlog 1.1 | - | private until fixed | backlog #94 |
| A-28 | Info | m0-core.md, state.py | H1 should | WP10 | see [review A](review-A-core.md) | fixed in #87 |
| A-29 | Info | audit.py, context.py | Backlog 1.1 | - | private until fixed | backlog #95 |
| A-30 | Info | capabilities.py, context.py, lifecycle.py | Backlog 1.1 | - | private until fixed | backlog #96 |
| A-31 | Info | errors.py, secrets.py | Backlog 1.1 | 1.1 | see [review A](review-A-core.md) | fixed in #147 (backlog #97) |
| B-1 | Medium | updates.py | H1 must | WP7 | see [review B](review-B-boundary.md) | fixed in #84 |
| B-2 | Medium | core.py, updates.py | H1 must | WP7 | see [review B](review-B-boundary.md) | fixed in #84 |
| B-3 | Medium | process.py | H1 must | WP7 | see [review B](review-B-boundary.md) | fixed in #84 |
| B-4 | Low | logs.py | H1 should | WP9 | see [review B](review-B-boundary.md) | fixed in #86 |
| B-5 | Low | scheduler.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #143 (backlog #98) |
| B-6 | Low | fsread.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #135 (backlog #99) |
| B-7 | Low | api.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #138 (backlog #100) |
| B-8 | Low | api.py, cli.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #134 (backlog #101) |
| B-9 | Low | api.py, cli.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #134 (backlog #102) |
| B-10 | Low | process.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #148 (backlog #103) |
| B-11 | Low | updates.py | H1 should | WP7 | see [review B](review-B-boundary.md) | fixed in #84 |
| B-12 | Low | updates.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #137 (backlog #104) |
| B-13 | Low | updates.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #137 (backlog #105) |
| B-14 | Low | host_t2.py, rpc.py | H1 should | WP7 | see [review B](review-B-boundary.md) | fixed in #84 |
| B-15 | Low | host_t2.py, host_t2_child.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #139 (backlog #106) |
| B-16 | Low | host_t2.py, rpc.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #139 (backlog #107) |
| B-17 | Low | api.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #138 (backlog #108) |
| B-18 | Low | events.py, host_t2.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #139 (backlog #109) |
| B-19 | Low | schedule.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #143 (backlog #110) |
| B-20 | Info | api.py | H1 should | WP2 | see [review B](review-B-boundary.md) | fixed in #79 |
| B-21 | Info | scheduler.py | H1 should | WP7 | see [review B](review-B-boundary.md) | fixed in #84 |
| B-22 | Info | net.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #141 (backlog #111) |
| B-23 | Info | logs.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #140 (backlog #112) |
| B-24 | Info | api.py | H1 should | WP2 | see [review B](review-B-boundary.md) | fixed in #79 |
| B-25 | Info | host_t2.py, ops.py, updates.py | Backlog 1.1 | 1.1 | see [review B](review-B-boundary.md) | fixed in #145 (backlog #113) |
| C-1 | High | router / bridge | H1 must | WP1 | see [review C](review-C-modules.md) | fixed in #78 |
| C-2 | Medium | bridge | H1 must | WP8 | see [review C](review-C-modules.md) | fixed in #85 |
| C-3 | Medium | trim / bridge | H1 must | WP8 | see [review C](review-C-modules.md) | fixed in #85 |
| C-4 | Medium | router | H1 must | WP1 | see [review C](review-C-modules.md) | fixed in #78 |
| C-5 | Medium | meter | H1 must | WP8 | see [review C](review-C-modules.md) | fixed in #85 |
| C-6 | Medium | lifecycle / ops | H1 must | WP5 | see [review C](review-C-modules.md) | fixed in #82 |
| C-7 | Medium | workers / router | H1 must | WP5 | see [review C](review-C-modules.md) | fixed in #82 |
| C-8 | Medium | router / engine | H1 must | WP1 | see [review C](review-C-modules.md) | fixed in #78 |
| C-9 | Low | adapter | H1 should | WP8 | see [review C](review-C-modules.md) | fixed in #85 |
| C-10 | Low | meter | H1 should | WP8 | see [review C](review-C-modules.md) | fixed in #85 |
| C-11 | Low | resources | H1 should | WP10 | see [review C](review-C-modules.md) | fixed in #87 |
| C-12 | Low | dashboard | H1 should | WP10 | see [review C](review-C-modules.md) | fixed in #87 |
| C-13 | Low | code quality | H1 should | WP10 | see [review C](review-C-modules.md) | fixed in #87 |
| C-14 | Low | adapter / router / meter | Backlog 1.1 | 1.1 | see [review C](review-C-modules.md) | fixed in #152 (backlog #114) |
| C-15 | Low | secrets | H1 should | WP6 | see [review C](review-C-modules.md) | fixed in #83 |
| C-16 | Low | activation | H1 should | WP8 | see [review C](review-C-modules.md) | fixed in #85 |
| C-17 | Low | config | Backlog 1.1 | 1.1 | see [review C](review-C-modules.md) | fixed in #150 (backlog #115) |
| C-18 | Info | dashboard | Backlog 1.1 | 1.1 | see [review C](review-C-modules.md) | fixed in #146 (backlog #116) |
| D-1 | High | USER-GUIDE.md, README.md | H1 must | WP2 | Guide's first module activation fails: `router` also needs `ui.panel`, which the guide never grants | fixed in #79 |
| D-2 | High | process.py, updates.py | H1 must | WP4 | On Windows the core picks Hermes Desktop's packaged git (WindowsApps), which this process cannot run; git-based update features are disabled here | fixed in #81 |
| D-3 | High | release.yml, CONTRIBUTING.md | H1 must | WP3 | Release publishes from any `v*.*.*` tag with no test gate or CI-green check; tags are not signed though CONTRIBUTING says "signed"; guide pins pip to a movable tag | fixed in #80 (adapted) |
| D-4 | High | test_m0_acceptance.py, test_hermes_adapter.py, test_inbox.py | H1 must | WP11 | No test or CI job runs against the real Hermes; all Hermes-side tests use fakes, including the dashboard proxy | fixed in #88 |
| D-5 | Medium | wheel contents; pyproject `[tool.hatch.build.targets.wheel]` | H1 must | WP3 | Wheel omits `dashboard/`, `plugin.yaml`, `templates/`, `tools/` and `py.typed`; the guide's pip path cannot give the dashboard tab | fixed in #80 (adapted) |
| D-6 | Medium | ci.yml, release.yml | H1 must | WP3 | CI never builds or installs the wheel or sdist; release SBOM describes the runner's toolchain, not the artifact | fixed in #80 |
| D-7 | Medium | USER-GUIDE.md, ops.py | H1 must | WP2 | Many operations need a running daemon (`activate`, `health`, `report show`, `check_updates`, `panel`, `deactivate`, `preview`, `update`, `rollback`); the guide's steps imply they work standalone | fixed in #79 |
| D-8 | Medium | ops.py, cli.py | H1 must | WP2 | Failed operations exit 0; `CapabilityDenied` names no capability; `module panel` says "unknown panel" for an inactive module | fixed in #79 |
| D-9 | Medium | cli.py, api.py | H1 must | WP2 | After the daemon stops, `api.port`/`api.token` stay behind; every later CLI command then loses ~2.1–2.8 s to a connection refusal | fixed in #79 |
| D-10 | Medium | cli.py, paths.py | H1 must | WP2 | Standalone CLI defaults to `%LOCALAPPDATA%\switchyard`, not the Hermes plugin data dir the guide describes; the two stores silently diverge | fixed in #79 |
| D-11 | Medium | host_t2.py | H1 must | WP7 | T2 host flood-kill and stalled-writer kill never execute in the suite, though CHANGELOG 1.0.0 and the R1 review list them as fixed | fixed in #84 |
| D-12 | Medium | tests (10 skips, listed in details) | H1 must | WP3 | Coverage and the security tests are platform-split: this Windows run skipped 10 tests, including all POSIX permission checks; no skip allow-list in CI | fixed in #80 |
| D-13 | Medium | README.md | No action: accepted, documented (single maintainer) | - | Bus factor 1: 53 of 56 commits from one account, `CODEOWNERS` is a single user, and every "security review" was run by the building agent | accepted, documented (WP0) |
| D-14 | Medium | CHANGELOG.md, pyproject.toml | H1 must | WP10 | `Production/Stable` on 1.0.0, shipped after 16 release headers in about two days, with 13 minor bumps, zero patch releases, breaking behaviour changes in 1.0.0, and no external review | fixed in #87 |
| D-15 | Low | process.py, test_process.py | H1 should | WP4 | process.py refusal of a working-directory executable is only partly tested (absolute PATH entry branch never runs) | fixed in #81 |
| D-16 | Low | .pre-commit-config.yaml, security.yml | H1 should | WP10 | Pre-commit pins ruff v0.6.9 and gitleaks v8.18.4; lock has ruff 0.17.6 and CI runs gitleaks 8.30.1; stale "P0 task" comment | fixed in #87 |
| D-17 | Low | manifest.json | H1 should | WP10 | Dashboard manifest version is 0.10.0; everything else says 1.0.0 | fixed in #87 |
| D-18 | Low | docs_gap_audit.md | H1 should | WP10 | Tracked root `docs_gap_audit.md` describes v0.13.0 and says the user guide "does not exist"; it ships in the sdist | fixed in #87 |
| D-19 | Low | REFERENCE.md | H1 should | WP10 | REFERENCE.md says "Generated from the code" but no generator exists; it omits `--json`, `--data-dir`, `backup/`, `trigger.fired`, and never defines status values | fixed in #87 |
| D-20 | Low | __init__.py | H1 should | WP2 | `switchyard_modules` tool description advertises `deactivate`; its enum excludes it, as the CHANGELOG says | fixed in #79 |
| D-21 | Low | local .venv metadata (read only) | No action: local environment only; fixed 2026-11-20 | - | Local `C:/Users/Vic/src/hermes-switchyard/.venv` reports `hermes-switchyard 0.0.1` (stale editable install); CI installs fresh and is unaffected | no action |
| D-22 | Low | ci.yml | Backlog 1.1 | 1.1 | Dashboard JS/CSS is committed with no source or build; `plugin_api.py` is outside mypy, bandit and any test that uses real FastAPI | fixed in #146 (backlog #117) |
| D-23 | Low | ci.yml, test_r1_hardening.py, test_state.py | H1 should | WP3 | CI runs only 3.11 and 3.13; 3.14 passes locally but emits 10 ResourceWarnings from unclosed SQLite connections in tests | fixed in #80 |
| D-24 | Low | CHANGELOG.md, release.yml | H1 should | WP3 | Release notes are auto-generated from PR titles, not from the CHANGELOG entry; CHANGELOG has no compare links | fixed in #80 |
| D-25 | Low | pyproject.toml | H1 should | WP3 | `build-system` requires `hatchling` unpinned; the lock pins 1.33.0; isolated builds (pip default) get whatever is latest | fixed in #80 |
| D-26 | Low | cli.py, ops.py | H1 should | WP2 | CLI polish: unknown capability exits 3 ("denied"); `config show` prints Python dict reprs; `api serve` readiness line is block-buffered when piped | fixed in #79 |
| D-27 | Low | test_host_t2.py | H1 should | WP7 | Vacuous assertion `assert os.name` in a host test | fixed in #84 |
| D-28 | Info | suite (details) | No action: positive observation | - | Suite is deterministic and reasonably fast: identical results over 3 runs; slowest test 6.3 s; a few real-sleep timing tests | no action |
| D-29 | Info | see "Not checked" | No action: list of things not checked; see H2 | - | Not verified: pip-audit, live GitHub settings, action SHAs vs upstream, Linux/macOS, Hermes runtime, attestation | no action |
