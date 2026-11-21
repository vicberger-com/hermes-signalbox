# Hermes Switchyard v1.0.0: engineering-practice and operational-readiness review

Date: 2026-11-20. Reviewed commit: `a141ec0` (main). Tag `v1.0.0` points at `4393461`; two commits on main came after it and are not in CHANGELOG `[Unreleased]`: `7695d2b` (issue forms) and `a141ec0` (84 files: wiki source and `tools/wiki_publish.py`).
Scope: tests, CI/CD, release and supply chain, packaging and install, first-run walkthrough, documentation accuracy, repo hygiene.

## Method and limits

- The source repo `C:/Users/Vic/src/hermes-switchyard` was not modified. All builds, installs and test runs happened in `C:/Users/Vic/AppData/Local/hermes/cache/scratch/switchyard-eval/clone` (a `git clone --local`), with scratch venvs next to it. Repo reads were `git` read-only commands, grep and file reads. Git may refresh its index stat cache on `git status`; no tracked content changed.
- Python 3.11 venv: installed `requirements-dev.txt` with `--require-hashes` (3m22s), then `pip install -e .`. Python 3.14 venv: unlocked `pytest`, `pytest-cov`, `hatchling`, `editables` (no hashes).
- Walkthrough: wheel built with `python -m build --no-isolation` (as the release job does), installed into a fresh venv with no source on the path. All commands ran with `SWITCHYARD_DATA_DIR` pointing at a scratch directory, so the real `%LOCALAPPDATA%` and the Hermes profile were never touched.
- Not run: `pip-audit` (needs the OSV network service; the task allows only PyPI pip installs), Linux and macOS, a live GitHub check (branch protection, rulesets, action SHA vs upstream, `gh attestation verify`), and the Hermes runtime plugin loader (the local Hermes v0.23.2 was only queried for its version). See D-29.

## Summary

| ID | Sev | Confidence | Finding | Location |
|---|---|---|---|---|
| D-1 | High | confirmed-by-running | Guide's first module activation fails: `router` also needs `ui.panel`, which the guide never grants | docs/USER-GUIDE.md §3; src/switchyard/modules/router/README.md:73 |
| D-2 | High | confirmed-by-running | On Windows the core picks Hermes Desktop's packaged git (WindowsApps), which this process cannot run; git-based update features are disabled here | src/switchyard/process.py `find_program`; updates.py `git_usable`, `GitFetcher._run` |
| D-3 | High | confirmed-by-reading + running | Release publishes from any `v*.*.*` tag with no test gate or CI-green check; tags are not signed though CONTRIBUTING says "signed"; guide pins pip to a movable tag | .github/workflows/release.yml; CONTRIBUTING.md; USER-GUIDE §1 |
| D-4 | High | confirmed-by-reading | No test or CI job runs against the real Hermes; all Hermes-side tests use fakes, including the dashboard proxy | tests/core/test_hermes_adapter.py:19; tests/acceptance/test_m0_acceptance.py:177; tests/modules/test_inbox.py:164-185 |
| D-5 | Medium | confirmed-by-running | Wheel omits `dashboard/`, `plugin.yaml`, `templates/`, `tools/` and `py.typed`; the guide's pip path cannot give the dashboard tab | wheel contents; pyproject `[tool.hatch.build.targets.wheel]` |
| D-6 | Medium | confirmed-by-reading | CI never builds or installs the wheel or sdist; release SBOM describes the runner's toolchain, not the artifact | .github/workflows/ci.yml, release.yml |
| D-7 | Medium | confirmed-by-running | Many operations need a running daemon (`activate`, `health`, `report show`, `check_updates`, `panel`, `deactivate`, `preview`, `update`, `rollback`); the guide's steps imply they work standalone | docs/USER-GUIDE.md §2, §3, §6, §7; src/switchyard/ops.py `_require_host` |
| D-8 | Medium | confirmed-by-running | Failed operations exit 0; `CapabilityDenied` names no capability; `module panel` says "unknown panel" for an inactive module | src/switchyard/cli.py `main`; ops.py `_module_activate`, `_module_health` |
| D-9 | Medium | confirmed-by-running | After the daemon stops, `api.port`/`api.token` stay behind; every later CLI command then loses ~2.1–2.8 s to a connection refusal | src/switchyard/api.py `ApiClient.from_data_dir`; cli.py `_serve` |
| D-10 | Medium | confirmed-by-running + reading | Standalone CLI defaults to `%LOCALAPPDATA%\switchyard`, not the Hermes plugin data dir the guide describes; the two stores silently diverge | src/switchyard/paths.py `default_data_dir`; cli.py `_run`; USER-GUIDE §2 |
| D-11 | Medium | confirmed-by-running | T2 host flood-kill and stalled-writer kill never execute in the suite, though CHANGELOG 1.0.0 and the R1 review list them as fixed | src/switchyard/host_t2.py:113-119, 145-146; CHANGELOG 1.0.0 Security |
| D-12 | Medium | confirmed-by-running | Coverage and the security tests are platform-split: this Windows run skipped 10 tests, including all POSIX permission checks; no skip allow-list in CI | tests (10 skips, listed in details) |
| D-13 | Medium | confirmed-by-reading | Bus factor 1: 53 of 56 commits from one account, `CODEOWNERS` is a single user, and every "security review" was run by the building agent | .github/CODEOWNERS; git log; README.md |
| D-14 | Medium | confirmed-by-reading | `Production/Stable` on 1.0.0, shipped after 16 release headers in about two days, with 13 minor bumps, zero patch releases, breaking behaviour changes in 1.0.0, and no external review | pyproject.toml classifiers; CHANGELOG.md |
| D-15 | Low | confirmed-by-running | process.py refusal of a working-directory executable is only partly tested (absolute PATH entry branch never runs) | src/switchyard/process.py:71-74; tests/core/test_process.py:69 |
| D-16 | Low | confirmed-by-reading | Pre-commit pins ruff v0.6.9 and gitleaks v8.18.4; lock has ruff 0.17.6 and CI runs gitleaks 8.30.1; stale "P0 task" comment | .pre-commit-config.yaml; requirements-dev.txt; security.yml |
| D-17 | Low | confirmed-by-reading | Dashboard manifest version is 0.10.0; everything else says 1.0.0 | dashboard/manifest.json |
| D-18 | Low | confirmed-by-reading | Tracked root `docs_gap_audit.md` describes v0.13.0 and says the user guide "does not exist"; it ships in the sdist | docs_gap_audit.md |
| D-19 | Low | confirmed-by-reading | REFERENCE.md says "Generated from the code" but no generator exists; it omits `--json`, `--data-dir`, `backup/`, `trigger.fired`, and never defines status values | docs/REFERENCE.md:3; tools/ (only 2 unrelated scripts) |
| D-20 | Low | confirmed-by-reading | `switchyard_modules` tool description advertises `deactivate`; its enum excludes it, as the CHANGELOG says | src/switchyard/hermes/__init__.py `MODULES_SCHEMA` |
| D-21 | Low | confirmed-by-running | Local `C:/Users/Vic/src/hermes-switchyard/.venv` reports `hermes-switchyard 0.0.1` (stale editable install); CI installs fresh and is unaffected | local .venv metadata (read only) |
| D-22 | Low | confirmed-by-reading | Dashboard JS/CSS is committed with no source or build; `plugin_api.py` is outside mypy, bandit and any test that uses real FastAPI | dashboard/dist/*; pyproject mypy `files`; ci.yml bandit paths |
| D-23 | Low | confirmed-by-running | CI runs only 3.11 and 3.13; 3.14 passes locally but emits 10 ResourceWarnings from unclosed SQLite connections in tests | ci.yml matrix; tests/core/test_state.py, test_r1_hardening.py |
| D-24 | Low | confirmed-by-reading | Release notes are auto-generated from PR titles, not from the CHANGELOG entry; CHANGELOG has no compare links | release.yml `--generate-notes`; CHANGELOG.md |
| D-25 | Low | confirmed-by-reading | `build-system` requires `hatchling` unpinned; the lock pins 1.33.0; isolated builds (pip default) get whatever is latest | pyproject.toml `[build-system]` |
| D-26 | Low | confirmed-by-running | CLI polish: unknown capability exits 3 ("denied"); `config show` prints Python dict reprs; `api serve` readiness line is block-buffered when piped | cli.py; ops.py `_config_show`; `_serve` |
| D-27 | Low | confirmed-by-reading | Vacuous assertion `assert os.name` in a host test | tests/core/test_host_t2.py:375 |
| D-28 | Info | confirmed-by-running | Suite is deterministic and reasonably fast: identical results over 3 runs; slowest test 6.3 s; a few real-sleep timing tests | suite (details) |
| D-29 | Info | not checked | Not verified: pip-audit, live GitHub settings, action SHAs vs upstream, Linux/macOS, Hermes runtime, attestation | see "Not checked" |

Counts: Critical 0, High 4, Medium 10, Low 13, Info 2 (29 findings).

## Details

### High

**D-1. The guide's first module activation fails** (confirmed-by-running)
- Location: docs/USER-GUIDE.md §3 (`module grant router --capability hermes.hooks` then `module activate router`); src/switchyard/modules/router/README.md:73 ("Capabilities: `hermes.hooks` and `ui.panel` (required to start)"); router `module.toml` lists `ui.panel` as requested, not optional.
- Evidence:
  ```
  [0] 0.36s  module grant router --capability ui.panel   -> granted: ['ui.panel']
  [0] 0.39s  module activate router   (daemon, before the fix) -> status: failed  error: CapabilityDenied
             requested: ['hermes.hooks', 'llm.free', 'llm.paid', 'ui.panel']  granted: ['hermes.hooks']
  [0] 0.35s  module activate router   (after granting ui.panel) -> status: active  error: None
  [0] 0.32s  module health router  -> ok: True  detail: routing main on openrouter
  ```
- Impact: a new user who follows the guide literally ends with a failed module. Exit status (see D-8) is 0, so the failure is only visible in the printed output.
- Fix: put `--capability ui.panel` into the guide's grant example, and state which capabilities each module requires to start. Add a CI job that runs the guide's commands against a temp data dir.

**D-2. Windows git resolves to Hermes Desktop's packaged git, which cannot run** (confirmed-by-running for the lookup; update path confirmed-by-reading)
- Location: src/switchyard/process.py `find_program` (first `shutil.which` hit, no fallback); src/switchyard/updates.py `git_usable` and `GitFetcher._run` (same lookup); tests/core/test_updates.py skips at lines 198, 217, 342.
- Evidence:
  ```
  find_program('git') -> C:\Program Files\WindowsApps\NousResearchInc.HermesAgent_2026.7675.1816.0_x64__.../tools/git-2.56.1+1-win32-x64/ucrt64/bin/git.EXE
  git_usable() -> False
  subprocess.run([...git.EXE, '--version']) -> PermissionError [WinError 5] Access is denied
  ```
  bash `git --version` on the same machine works (`/ucrt64/bin/git`, 2.56.1). The skip reason on the three tests is "no git executable this process may run".
- Impact: on any Windows host with Hermes Desktop installed, `module check_updates`, `preview`, `update` and `rollback` cannot run git. `GitFetcher._run` catches `OSError` and raises `UpdateError("git could not run: PermissionError")`. The updates.py 84% coverage on this host is an artifact of these skips. The real git code path was not executed in this run.
- Fix: resolve git by trying each PATH candidate in order and taking the first that runs `--version`, or prefer a configured absolute path, or require Git for Windows explicitly. Surface the exact resolved path in `module list`/`health`. Add a CI assertion that the git-dependent tests did not skip.

**D-3. Release pipeline has no test gate and tags are unsigned** (confirmed-by-reading for the workflow; confirmed-by-running for tag signatures)
- Location: .github/workflows/release.yml (`on: push: tags: ["v*.*.*"]`; jobs: build, install wheel, SBOM, sha256sum, attest, `gh release create`); CONTRIBUTING.md "annotated signed tags"; docs/USER-GUIDE.md §1 `pip install "git+...@v1.0.0"`.
- Evidence:
  ```
  $ git cat-file tag v1.0.0            -> object 4393461...  type commit  tag v1.0.0  (no signature block; 0 matches for PGP/SSH SIGNATURE)
  $ git cat-file tag v0.0.1 | grep -c "BEGIN PGP SIGNATURE|BEGIN SSH SIGNATURE" -> 0
  $ git log -3 --format='%h %G?'       -> E (signed; signature not verifiable on this machine)
  ```
  release.yml has no `needs:` on the CI workflow and no `pytest` step. No `environment:` with protection rules. `gh release create ... --generate-notes`.
- Impact: a pushed `v*.*.*` tag publishes a release, including the SBOM and attestation, without re-running the tests or confirming the tagged commit passed CI. Tags are not signed, and the guide's pip command installs whatever commit a movable tag points to. An attacker or a mistake with push rights could publish an unreviewed build under a valid-looking version number.
- Fix: add a `verify` job (full test + lint + wheel smoke install) and make the release job `needs:` it; require the tag to be an ancestor of `main` and signed (`git tag -v`, or the GitHub signed-tag check); protect the release with an `environment:` that needs approval; use tag rulesets to prevent tag moves; make the guide recommend the commit SHA (as §1 already does for `hermes plugins install`) for both install paths.

**D-4. The real Hermes is never exercised by any test or CI job** (confirmed-by-reading)
- Location: tests/core/test_hermes_adapter.py:19 (`FakeCtx`), tests/acceptance/test_m0_acceptance.py:177 (`FakeHermesCtx`), tests/modules/test_inbox.py:164-185 (dashboard proxy test defines its own `HTTPException` and `Router` stubs), tests/core/test_context.py (fake bus and panels). No file imports the `hermes` package; `fastapi` is absent from requirements-dev.txt (grep count 0); CI installs no Hermes.
- Evidence: `grep -rn "import hermes\|hermes_agent" tests/` finds only `from switchyard import hermes`. The acceptance file is named `test_m0_acceptance.py` and its three tests cover the M0 scope, not the 1.0 release.
- Impact: the integration points that matter most (hook registration against real `PluginContext`, idle-task scheduling, `plugins.plugin_storage` import in `dashboard/plugin_api.py`, dashboard routing) are checked only against the authors' own understanding of Hermes. A Hermes API change will not fail CI. The local Hermes (v0.23.2) was not used.
- Fix: add a CI job that installs a pinned Hermes Agent release (or a contract fixture recorded from one) and runs the adapter against the real `PluginContext`. Rename the acceptance file to match its scope, or extend it to 1.0. Add a test that imports the real FastAPI app when `fastapi` is available.

### Medium

**D-5. Wheel omits runtime pieces the guide depends on** (confirmed-by-running)
- Location: built wheel `hermes_switchyard-1.0.0-py3-none-any.whl`; pyproject `[tool.hatch.build.targets.wheel] packages = ["src/switchyard"]`.
- Evidence: 85 entries, all under `switchyard/` and `dist-info/`. Missing: `dashboard/` (manifest, `plugin_api.py`, `dist/`), `plugin.yaml`, the root `__init__.py` shim (fine for a pip install, since the entry point is used), `templates/module/`, `tools/`, and `py.typed`. Present: `switchyard/modules/*/module.toml`, `README.md`, `schemas/module.schema.json`, `migrations/0001_core.sql`, `LICENSE`, `NOTICE`, entry points `switchyard = switchyard.cli:main` and `hermes_agent.plugins: switchyard = switchyard.hermes`.
- Impact: USER-GUIDE §1 offers `pip install` as a route; §5 says the dashboard tab appears after install. The dashboard files and `plugin.yaml` come only from a git install. The effect on Hermes's loader was not checked (suspected: the pip path gets no dashboard tab). Without `py.typed`, downstream mypy users see the package as untyped.
- Fix: include `dashboard/` and `plugin.yaml` in the wheel (via `force-include` or a shared-data layout) or document that the dashboard requires the git install. Add `py.typed`. Decide whether `templates/` belongs in the wheel; the module template is only in the sdist and the repo.

**D-6. CI does not build or check the artifacts; the SBOM describes the wrong thing** (confirmed-by-reading)
- Location: .github/workflows/ci.yml (no `python -m build`, no wheel or sdist install); release.yml (`python -m build`, `python -m pip install dist/*.whl`, then `cyclonedx-py environment --output-format JSON --output-file dist/sbom.cdx.json`).
- Impact: a packaging break (like D-5, or a missing `package-data` file) is found only at tag time. `cyclonedx-py environment` lists the packages installed in the runner: the lock's dev toolchain plus the package itself. The product has no runtime dependencies, so the SBOM is mostly build tooling, not an inventory of what ships.
- Fix: add a CI job that builds the wheel and sdist, installs the wheel into a clean venv, runs the CLI smoke test, and checks the wheel's file list against an expected manifest. Generate the release SBOM from the built wheel's metadata (or from the sdist's lock), and keep a separate build-environment SBOM if wanted.

**D-7. Daemon-only operations are not documented as such** (confirmed-by-running)
- Location: src/switchyard/ops.py `_require_host` callers: `module activate`, `deactivate`, `health`, `panel`, `action`, `preview`, `update`, `rollback`, `check_updates`; `report show` is not `offline` either. docs/USER-GUIDE.md §2 mentions the hosting process once; §3, §6 and §7 show these commands as if they work from a shell.
- Evidence:
  ```
  [1] 0.30s  module activate router      -> error: 'module activate' needs the running daemon: start it with 'switchyard api serve'
  [1] 0.32s  report show --kind health   -> error: 'report show' needs the running daemon: start it with 'switchyard api serve'
  [1] 0.37s  module check_updates        -> error: 'module check_updates' needs the running daemon: ...
  ```
  The error text is clear, which is to its credit.
- Impact: a first-time user following §3 and §6 hits errors at the activation step.
- Fix: mark the daemon-only commands in the guide and in `switchyard --help` output, and show `switchyard api serve` as step 0 of the first run.

**D-8. Failed results exit 0, and the errors do not say what is missing** (confirmed-by-running)
- Location: src/switchyard/cli.py `main` (exit code only from exceptions); ops.py `_module_activate`, `_module_health`, `_module_deactivate` return the state without raising; capability denial raised without a name; panel lookup.
- Evidence:
  ```
  module activate router  -> status: failed  error: CapabilityDenied   (exit 0)
  module health router    -> ok: False  detail: failed                  (exit 0)
  module deactivate router-> status: failed  error: CapabilityDenied   (exit 0)
  module panel router --panel router.status (router inactive) -> error: unknown panel 'router.status' for module 'router'  (exit 1)
  module grant router --capability net.bogus -> denied: cannot grant 'net.bogus' to 'router': unknown capability  (exit 3)
  ```
  The missing capability (`ui.panel`) appears only in `report show --kind security` as a `policy.denied` record.
- Impact: scripts and CI that check `$?` treat a failed activation as success. Operators get "CapabilityDenied" with no capability name. "unknown panel" is wrong, since the panel exists but the module is not running. An unknown capability is a usage error (exit 2), not a denial (exit 3).
- Fix: exit 1 when the result shows `status: failed` or `ok: false`. Put the denied capability in the message (the core knows it). Say "module is not active" for panels. Use exit 2 for unknown capabilities.

**D-9. Stale control-API files after the daemon stops; every later command pays a 2-second penalty** (confirmed-by-running)
- Location: src/switchyard/cli.py `_serve`; src/switchyard/api.py `ApiClient.from_data_dir`; the `api.port` and `api.token` files are written at start.
- Evidence:
  ```
  daemon stop: exit=3221225786 after 0.01s          (0xC000013A, terminated by console control, not a clean exit)
  files in data dir afterwards: api.port, api.token, host.lock, state.db ...
  urlopen 127.0.0.1:57559 -> WinError 10061 (connection refused), elapsed 2.07 s
  module list (daemon stopped)  -> 2.65 s, 2.68 s, 2.78 s    (vs 0.27-0.52 s with daemon running)
  report show health            -> error: 'report show' needs the running daemon   (2.32 s)
  ```
  A new daemon started fine afterwards, so `host.lock` was released by the OS. A clean Ctrl+C shutdown was not tested (the CTRL_BREAK signal was used instead).
- Impact: each command after a daemon exit costs about 2 s on Windows, and the stale port number may point to another process after a reboot. Users may think something is hung.
- Fix: delete `api.port` and `api.token` in a `finally`/`atexit` handler and on SIGBREAK/SIGTERM. Before connecting, check the lock or the process. Use a short connect timeout (under 200 ms for loopback).

**D-10. The standalone CLI and the Hermes session use different data directories by default** (confirmed-by-running + reading)
- Location: src/switchyard/paths.py `default_data_dir` and `resolve_data_dir`; cli.py `_run` (passes no `hermes_dir`); hermes/__init__.py (passes `ctx.state.data_dir`); docs/USER-GUIDE.md §2 ("the profile's plugin data directory unless you set `data_dir`").
- Evidence: `default_data_dir()` with no environment override returns `C:\Users\Vic\AppData\Local\switchyard` (the directory does not exist on this machine yet, so the CLI has not been run here before). The Hermes session uses the profile's plugin storage.
- Impact: `switchyard module list` typed in a shell shows a store that differs from the one the Hermes session hosts. Grants made from the shell do not affect the session, and the reverse. Nothing warns about this. The walkthrough had to set `SWITCHYARD_DATA_DIR` to see one store.
- Fix: document the two stores and the `SWITCHYARD_DATA_DIR` or `--data-dir` setting in §2. Make `switchyard config show` print the resolved store and the reason it was chosen.

**D-11. The T2 flood-kill and stalled-writer kill are untested despite being listed as fixed** (confirmed-by-running)
- Location: src/switchyard/host_t2.py lines 113-119 (queue full: kill child) and 145-146 (writer still alive after deadline: kill child); CHANGELOG 1.0.0 Security ("T2 send deadline and flood kill"); docs/qa/14-r1-prework.md:70 ("Fixed ... a flooding child is killed").
- Evidence: the coverage report lists those lines as missing. `grep -rn -i "flood|stopped reading|queue.Full" tests/` finds nothing. `test_rpc_call_has_one_total_deadline` covers the RPC channel, not the T2 send path.
- Impact: these are the protections against a module that floods or stops reading. A regression would not fail CI.
- Fix: add regression tests: a child that writes frames without reading (queue full), and a child that stops reading stdin (writer deadline). Assert that the child is killed and an audit record is written.

**D-12. Coverage and security tests are split by platform; skips are not controlled** (confirmed-by-running)
- Location: 10 skips in this Windows run (`pytest -rs`, identical in both runs):
  - POSIX permission bits: tests/core/test_audit.py:190, test_logs_panels.py:50, test_paths.py:80
  - POSIX device file: test_fsread.py:75
  - symlinks: test_manifest_loader.py:92, test_updates.py:239
  - no git executable: test_updates.py:198, 217, 342
  - non-Windows path: test_secrets.py:380
- Evidence: the 94.39% gate passes with these skipped. `hostlock.py` 78% is mostly the other OS's lock branch (`msvcrt` vs `fcntl`, lines 40-42, 63-65, 92-94, 115-117), plus the lock-timeout path (96-100), which no test on this host reaches. `process.py` 87% is the same effect (killpg vs taskkill).
- Impact: each OS checks its own half. On Windows the file-permission hardening is never exercised. The CI matrix covers all three OSes, but nothing requires the skip list to match an expected set, so a silent skip on any OS passes.
- Fix: run `pytest -rs` in CI and fail when the skip set differs from an allow-list per OS. Add a test for the lock-timeout path (lines 96-100) that runs on every OS.

**D-13. Bus factor is 1** (confirmed-by-reading)
- Location: .github/CODEOWNERS (`* @vicaberger`); `git log`: 56 commits, 53 by `vicaberger`, 1 by `Vic Berger` (a second identity), 2 by dependabot; README.md "Built by a Hermes instance following AGENTS.md; every phase had a fresh security review".
- Impact: one person and an AI agent wrote, reviewed and released everything. There is no second human reviewer on record; branch protection was not checked (not checked: GitHub settings). Onboarding is reasonable (CONTRIBUTING, AGENTS.md, 12 ADRs with Context/Decision/Consequences and dates, a QA record per phase), but the review history cannot show independent scrutiny.
- Fix: recruit at least one second reviewer with merge rights, document the security-review process as a human checklist (not only agent output), and require a second approval for changes to `ops.py`, `policy`, `audit` and `host_t2.py`.

**D-14. The `Production/Stable` claim rests on about two days of history** (confirmed-by-reading)
- Location: pyproject.toml classifiers (`Development Status :: 5 - Production/Stable`); CHANGELOG.md (16 release headers from 0.0.1 on 2026-11-19 to 1.0.0 on 2026-11-20).
- Evidence: 13 minor bumps (0.1.0 to 0.13.0), zero patch releases, 1.0.0 released the same day as 0.13.0. The 1.0.0 entry itself changes behaviour in ways that need a migration: "`deactivate` is no longer a model tool action", "`inbox` requests `core.read`... Grant it after upgrading", "`module remove --keep-data` keeps data only, never grants". No PyPI publication (GitHub release only). "Security reviews" are the building agent's own (README.md).
- Impact: SemVer signals "stable and compatible" to users, but the 1.0.0 history has not been used by anyone outside, and the behaviour changes are documented in a changelog nobody else has tested. This is a claim problem more than a code problem.
- Fix: use `Development Status :: 4 - Beta` until there is external use or an external review. Publish a support and deprecation policy in SECURITY.md or the README, and keep 0.x semantics for breaking config or behaviour changes.

### Low

**D-15. Working-directory executable refusal is only partly tested** (confirmed-by-running coverage)
- Location: src/switchyard/process.py:71-74 (`if Path(exe).resolve().parent == Path.cwd().resolve(): return None`). Coverage lists 72-74 as missing. tests/core/test_process.py:69 covers the relative-result case only, which Windows `shutil.which` returns before the check.
- Fix: add a test where `PATH` contains the absolute working directory, and assert `find_program` returns `None`.

**D-16. Pre-commit, lock and CI disagree on tool versions** (confirmed-by-reading)
- Location: .pre-commit-config.yaml (`ruff-pre-commit rev: v0.6.9`, `gitleaks rev: v8.18.4`, comment "P0 task: confirm current revisions"); requirements-dev.txt (`ruff==0.17.6`); security.yml (`GITLEAKS_VERSION: "8.30.1"`).
- Impact: a developer's pre-commit lint can disagree with CI. The `P0 task` comment is an unfinished item in a shipped file.
- Fix: run `pre-commit autoupdate --freeze` and align the versions; remove the note.

**D-17. Dashboard manifest version is stale** (confirmed-by-reading)
- Location: dashboard/manifest.json `"version": "0.10.0"`. Everything else is 1.0.0 (pyproject, plugin.yaml, `switchyard.__version__`, CHANGELOG, wheel METADATA, `switchyard version` output).
- Fix: bump it, and add a check in `tools/validate_manifest.py` or a test that all version fields match `pyproject.toml`.

**D-18. Stale root file ships in the sdist** (confirmed-by-reading)
- Location: `docs_gap_audit.md` (tracked; in the sdist). Header: "Docs-Coverage Audit (R1)", "(main, v0.13.0)", "Status: Gaps identified; user guide does not exist". Contradicts docs/USER-GUIDE.md, which exists.
- Fix: delete it or move it to `docs/qa/` with a dated note.

**D-19. REFERENCE.md is described as generated, but it is hand-written and has gaps** (confirmed-by-reading; accuracy checked by parsing)
- Location: docs/REFERENCE.md:3 ("Generated from the code for v1.0.0"). `tools/` contains only `validate_manifest.py` and `wiki_publish.py`, so no generator exists.
- Accuracy checked: the 21 operations in `ops.py` match the REFERENCE table exactly. The 39 literal core audit actions match, with `module.*` actions produced dynamically (context.py:243, lifecycle.py:170) and not checkable statically. Gaps: global flags `--json` and `--data-dir` are not documented (grep: false, false); `backup/` (in `paths.SUBDIRS`) is missing from the data-directory table; the `trigger.fired` event (scheduler.py:296) is not listed; module status values (`verified`, `active`, `failed`, `mode=auto` defaults) are not defined in the guide or the reference.
- Fix: either generate the reference from `OPERATIONS` (and check it in CI), or drop the "Generated" wording. Add the missing flags, directory, event and status definitions.

**D-20. The model tool description names an action its schema rejects** (confirmed-by-reading)
- Location: src/switchyard/hermes/__init__.py `MODULES_SCHEMA`: description "Actions: list, show, activate, deactivate, health, and run"; `"enum": list(MODEL_TOOL_ACTIONS)`, which is `("list", "show", "activate", "health", "run")` by design (the comment says "No deactivate").
- Impact: the model is told it may deactivate modules, then gets a schema refusal. The CHANGELOG says `deactivate` was removed as a model action.
- Fix: remove "deactivate" from the description and add a test that the description and the enum agree.

**D-21. Local .venv has stale package metadata** (confirmed-by-running; read-only)
- Location: `C:/Users/Vic/src/hermes-switchyard/.venv` reports `importlib.metadata.version('hermes-switchyard') == '0.0.1'`. The scratch clone's fresh editable install reports 1.0.0. This explains the `0.0.1` that pip-audit saw. CI installs fresh and is not affected.
- Fix: `pip install --no-deps --no-build-isolation -e .` in the local `.venv`. I did not change it.

**D-22. Dashboard code sits outside every quality gate** (confirmed-by-reading)
- Location: `dashboard/dist/index.js` and `style.css` are committed with no source, no build script and no package file in the repo. `dashboard/plugin_api.py` is not in mypy's `files` (pyproject: `src`, `tools`, `templates/module/example.py`), not in bandit's paths (`src tools templates`), and only ruff covers it. It imports `fastapi` (not locked) and `plugins.plugin_storage` (Hermes internal).
- Fix: keep the bundle's source in the repo (or document that it is hand-edited minified output), add `dashboard/` to mypy and bandit, and lock or optional-import `fastapi`.
- Fixed in 1.1 (#117): `dist/index.js` and `style.css` are the hand-written source (no build step); `dashboard/README.md` says so. `plugin_api.py` is in mypy's `files` (FastAPI and `plugins` count as untyped imports there; strict against real FastAPI types passes) and in bandit's paths in security.yml and release.yml. `tests/integration/test_dashboard_api.py` runs its routes under real FastAPI in the hermes-integration job, using Hermes's own FastAPI rather than a new lock entry.

**D-23. CI omits 3.12 and 3.14; 3.14 shows test-resource leaks** (confirmed-by-running on 3.14)
- Location: ci.yml `python: ["3.11", "3.13"]`. Local 3.14.5 run: `671 passed, 10 skipped, 10 warnings`, with `ResourceWarning: unclosed database` from tests/core/test_r1_hardening.py (`test_auth_failures_are_never_trimmed`) and tests/core/test_state.py (`test_grants_persist_across_reopen`).
- Fix: add 3.12 and 3.14 to the matrix (or document why not), and close SQLite connections in those tests (or use `contextlib.closing`).

**D-24. Release notes are not the CHANGELOG** (confirmed-by-reading)
- Location: release.yml `gh release create ... --generate-notes`; CHANGELOG.md has no link references at the bottom and an empty `[Unreleased]`, although `7695d2b` and `a141ec0` landed on main after the v1.0.0 tag.
- Fix: extract the version's section from CHANGELOG.md into the release body (`--notes-file`), add compare links, and log post-tag changes under `[Unreleased]`.

**D-25. Build tool version is not pinned in pyproject** (confirmed-by-reading)
- Location: pyproject.toml `requires = ["hatchling"]` (no version). The lock pins `hatchling==1.33.0` for CI (`--no-build-isolation`), but a user who builds the sdist with pip's default isolation gets whatever hatchling is current.
- Fix: pin a range in `[build-system]` that matches the lock (for example `hatchling>=1.27,<2`), so isolated and locked builds agree.

**D-26. CLI output and exit-code polish** (confirmed-by-running)
- `module grant ... --capability net.bogus` prints `denied:` and exits 3 (capability denied). An unknown name is a usage error and should exit 2 (see D-8).
- `config show` prints Python reprs (`api: {'enabled': False, 'port': 0}`) while other commands print `key: value` pairs.
- `api serve` prints the "listening" line through a block-buffered pipe, so a service manager or log collector sees nothing until the buffer fills (it appeared only with `PYTHONUNBUFFERED=1`). Flush after printing.

**D-27. A vacuous assertion in a host test** (confirmed-by-reading)
- Location: tests/core/test_host_t2.py:375 `assert os.name  # parent survived`. This is always true. The real check that follows (`pytest.raises(StateError)`) is what matters.
- Fix: replace it with a liveness check (for example, `manager.health('evil')` returning a value without raising).

### Info

**D-28. Determinism and runtime are good** (confirmed-by-running)
- Python 3.11 pass 1: `671 passed, 10 skipped`, 94.39% branch coverage, 230.56 s (wall 232 s). Pass 2: identical outcomes, 249.01 s. Python 3.14: `671 passed, 10 skipped`, 94.36%, 202.53 s.
- Slowest 15 tests all 6.3 s or less (top: `tests/modules/test_scanner.py::test_review_regressions` 6.32 s; `test_settings_and_permissions` 4.61 s; `test_seeded_vulnerabilities_are_detected` 3.86 s).
- Real-time tests exist: tests/core/test_process.py:51 (0.2 s timeout against a 5 s child), tests/core/test_r1_hardening.py:143 (a 0.05 s sleep under a 2 s bound), tests/modules/test_offload.py:46 (a 100 × 0.1 s trickle server). None failed in 3 runs.
- Lint and typing reproduce: `ruff check` passed, `ruff format --check` ("241 files already formatted"), `mypy` ("Success: no issues found in 56 source files"), bandit printed no findings. `tools/validate_manifest.py templates` passed; `tools/wiki_publish.py --check`: "0 problem(s) in 68 pages".

**D-29. Not checked (out of reach or excluded by the task)**
- `pip-audit`: needs the OSV service (network). The task allowed only PyPI installs. Not run.
- GitHub settings: branch protection, rulesets (tags and branches), environment approvals, CodeQL default setup, Scorecard results.
- Action SHA pins: the comments say `# v4` etc., but the SHAs were not checked against upstream tags.
- Linux and macOS: the suite was run on Windows only (3.11 and 3.14).
- Hermes runtime: plugin loader, `hermes plugins install` (git path), dashboard discovery, `plugins.plugin_storage`. The Hermes profile was not touched. The local Hermes is v0.23.2, which meets `requires_hermes: >=0.22`.
- `gh attestation verify` and the release SBOM contents (no release exists to download).
- Dependabot's handling of the uv-compiled, hash-pinned `requirements-dev.txt` (not verified).

## Walkthrough (guide order, built wheel, scratch data dir)

Set-up: `venv-wheel` (fresh, Python 3.11), `pip install hermes_switchyard-1.0.0-py3-none-any.whl` (exit 0). The guide's `pip install git+...@v1.0.0` was replaced by the local wheel (no GitHub network). `hermes plugins install` was not run.

| # | Command (guide step) | Exit | Seconds | Outcome |
|---|---|---|---|---|
| 1 | `switchyard version` | 0 | 0.51 | `1.0.0` |
| 2 | `switchyard module list` (§2) | 0 | 0.52 | 12 modules, all `status=verified`; `mode=auto` on 8 of them, `manual` on 4; none granted |
| 3 | `switchyard audit verify` (§2) | 0 | 0.55 | `ok: True`, 24 records |
| 4 | `switchyard config show` (§2) | 0 | 0.70 | data_dir, api, log, host; Python dict reprs (D-26) |
| 5 | `switchyard module show router` (§3) | 0 | 0.54 | requested `hermes.hooks, llm.free, llm.paid, ui.panel`; granted `[]` |
| 6 | `switchyard module grant router --capability hermes.hooks` (§3) | 0 | 0.58 | `granted: ['hermes.hooks']` |
| 7 | `switchyard module activate router` (§3) | 1 | 0.30 | `needs the running daemon` (D-7) |
| 8 | `switchyard module mode router --mode auto` (§3) | 0 | 0.64 | `mode: auto` |
| 9 | `switchyard report show --kind health` (§6) | 1 | 0.32 | `needs the running daemon` (D-7) |
| 10 | `switchyard audit tail --n 50` (§8) | 0 | 0.75 | most recent records, hash-chained (chain intact) |
| 11 | `switchyard module check_updates` (§7) | 1 | 0.37 | `needs the running daemon` (D-7) |
| 12 | `switchyard --json module list` | 0 | 0.57 | JSON array (the global flag is not in REFERENCE, D-19) |
| 13 | `switchyard module grant router --capability net.bogus` | 3 | 0.68 | `denied: ... unknown capability` (D-8, D-26) |
| 14 | `switchyard module show nosuch` | 1 | 0.56 | `unknown module 'nosuch'` |
| 15 | `switchyard module grant router` (missing flag) | 2 | 0.31 | argparse usage, exit 2 (correct) |
| 16 | `switchyard api serve` (background, §2) | running | 0.58 | `listening on 127.0.0.1:57559`, token path (needs `PYTHONUNBUFFERED=1` to see it, D-26) |
| 17 | `switchyard module activate router` (daemon) | 0 | 0.39 | `status: failed  error: CapabilityDenied` (D-1, D-8) |
| 18 | `switchyard module health router` | 0 | 0.28 | `ok: False  detail: failed` |
| 19 | `switchyard report show --kind health` | 0 | 0.31 | module list plus status |
| 20 | `switchyard report show --kind usage` | 0 | 0.29 | meter, trimmer, workers: `unavailable: SwitchyardError` (no reason) |
| 21 | `switchyard report show --kind security` | 0 | 0.34 | audit ok, 177 records, `policy.denied` for `ui.panel` |
| 22 | `switchyard report show --kind changes` | 0 | 0.30 | grant and mode-change records |
| 23 | `switchyard module check_updates` (daemon) | 0 | 0.37 | `modules: []` (no git-installed modules) |
| 24 | `switchyard audit verify` (daemon) | 0 | 0.33 | `ok: True`, 177 records |
| 25 | `switchyard module panel router --panel router.status` | 1 | 0.30 | `unknown panel` while inactive (D-8) |
| 26 | `switchyard module deactivate router` | 0 | 0.31 | `status: failed` (exit 0, D-8) |
| 27 | `switchyard module revoke router --capability hermes.hooks` | 0 | 0.28 | `granted: []  deactivated: False` |
| 28 | daemon stopped (CTRL_BREAK) | 0xC000013A | 0.01 | not a clean exit; `api.port` and `api.token` left (D-9) |
| 29 | `switchyard module list` after stop | 0 | 2.65 | works, but 2.7 s (connection refused on stale port) (D-9) |
| 30 | `switchyard report show --kind health` after stop | 1 | 2.32 | `needs the running daemon` after 2.3 s |
| 31 | second run: `module grant router --capability ui.panel` | 0 | 0.36 | `granted: ['ui.panel']` (the README-required grant) |
| 32 | `module activate router` (daemon, after grant) | 0 | 0.35 | `status: active  error: None` |
| 33 | `module health router` | 0 | 0.32 | `ok: True  detail: routing main on openrouter` |
| 34 | `module panel router --panel router.status` | 0 | 0.29 | status panel with providers, budget, cooldown |
| 35 | `audit verify` | 0 | 0.34 | `ok: True`, 238 records |

Guide deviations found: step 3's activation and step 6's reports need the daemon (D-7); step 3's grant set is insufficient (D-1); the data dir the bare commands use is not the Hermes store (D-10); the guide does not mention the 2-second penalty after a stop (D-9). Commands took 0.27–0.75 s each when the daemon was not stale. Audit-chain verification passed after every step (up to 238 records).

## Version consistency

| Location | Version | Matches 1.0.0? |
|---|---|---|
| pyproject.toml | 1.0.0 | yes |
| plugin.yaml | 1.0.0 (`requires_hermes >=0.22`) | yes |
| src/switchyard/__init__.py `__version__` | 1.0.0 | yes; `switchyard version` prints 1.0.0 |
| CHANGELOG.md | `[1.0.0] - 2026-11-20` | yes |
| wheel METADATA | 1.0.0 | yes |
| docs/wiki Home.md | "Applies to v1.0.0" | yes |
| dashboard/manifest.json | 0.10.0 | no (D-17) |
| root `__init__.py` | no version | n/a (shim) |
| local `.venv` metadata | 0.0.1 | no, stale (D-21); fresh installs report 1.0.0 |

## What is done well

- Dev toolchain pinned with 1,285 hash lines and installed with `--require-hashes` in CI and release.
- Workflows: top-level `permissions: contents: read`; no `pull_request_target`; the only `${{ }}` in a `run:` is the required-check aggregator; the release uses `$GITHUB_REF_NAME` through `env`.
- Actions pinned to commit SHAs with version comments; gitleaks CLI pinned with a SHA-256 check and a full-history scan; scheduled security workflow; aggregator jobs (`ci-required`, `security-required`) give one stable check name.
- One operations table (`ops.py`) drives the CLI, the control API and the Hermes tools, so the three cannot drift; the 21 operations match the reference exactly.
- Model-actor allow-list enforced in the core (not just the adapter), with tests; audit chain verified after every step.
- Test suite deterministic over three runs and two interpreters (671 passed, 10 skipped, 94.4% branch coverage); 290 `pytest.raises` assertions and 1,132 `assert` statements show negative testing, not just "no exception".
- Wheel: zero runtime dependencies; module manifests, schemas and migrations included; LICENSE and NOTICE included in dist-info; entry points correct.
- Lint and typing gates reproduce cleanly (ruff, format, mypy strict on 56 files, bandit).
- Commands are fast (about 0.3–0.75 s) and most errors are specific (usage errors exit 2 with argparse help; "needs the running daemon: start it with ...").
- ADRs are consistent (Context, Decision, Consequences, date, Q&A link); the wiki source checker and manifest validator pass; `docs/USER-GUIDE.md` and `docs/REFERENCE.md` cover most of the surface.
- Release artifacts planned: SBOM, SHA256SUMS and provenance attestation (not verified live).
- Clean repo: no tracked caches or logs; `.gitignore` covers venvs, caches, build output, `.env`, keys and generated SBOMs; the only large tracked file is the lock.
