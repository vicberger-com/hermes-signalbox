# Pre-work Q&A: H3 evaluation after v1.0.1 + 1.1 stabilization

Date: 2026-11-23. Previous phase: H2 (real install verification), tag v1.0.1.

This is an **evaluation phase** (H3), not a module build phase. It follows the H1/H2 pattern:
scope comes from a fresh, separate evaluation of the current codebase (v1.0.1 + 1.1 stabilization).
The evaluation produces findings by ID with scope class (must, should, backlog, no action)
and work packages. Those become the next maintenance phase's scope.

Answer every question. Take the recommended option, mark it **default accepted**, and continue.
Only items that match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| H1 | 102 findings (5 High, 31 Medium, 51 Low, 15 Info). All High/Medium fixed. 28 Low/Info withheld as backlog #89-#116. | All H1 backlog items now fixed in 1.1 stabilization (PR #192). |
| H2 | Real install in `switchyard-test` profile; meter exact vs Hermes-reported; offload connectors tested; re-verified on Hermes v0.23.3. Findings H2-1 through H2-9 (guide notes, audit noise, git PATH, offload retries, plugin install dual, module list status, README types). | H2 findings inform H3 scope. Several are doc/guide fixes; some are code improvements. |
| 1.1 stabilization | 32 commits merged via PR #192. All H1 backlog + D-22 fixed. Tests 94.81% coverage. Bandit 0 findings. Pip-audit clean. Ruff/MyPy clean. | Baseline for H3 evaluation is clean. No known security issues from tooling. |
| H1 retro | "Always review a fix diff before release." "Release passed its own gates but had never been installed." | H3 evaluation must include real-install test (like H2) AND a fresh security review of the 1.1 diff. |

## 2. Research record

| Topic | Source (URL, commit or version, date read) | Finding |
|---|---|---|
| Current codebase | `1ee9ee8` (v1.0.1 + 1.1 stabilization), 2026-11-23 | 6418 statements, 995 tests pass, 94.81% branch coverage |
| Hermes Agent upstream | `NousResearch/hermes-agent` v0.23.3 (`caafe53`), 2026-11-19 | v0.23.3 is current stable; storage behind persistence interface; tool-result pruning on by default |
| Hermes advisories | `repos/NousResearch/hermes-agent/security-advisories`, 2026-11-23 | GHSA-p22p-9ph6-gmrh (high, <0.23.2) patched in 0.23.2; no new advisories since H1 |
| Bandit | local run 2026-11-23 | 0 findings (all `nosec` from H1 backlog items resolved) |
| pip-audit | local run 2026-11-23 | No known vulnerabilities |
| ruff / mypy | local run 2026-11-23 | Clean |
| gitleaks | not run (CLI not installed) | TODO: run gitleaks in CI |
| CodeQL | CI runs default setup | Passed on PR #192 |
| Real Hermes integration | CI job `hermes-integration` on v0.23.2 + PR #192 on v0.23.3 | 5 tests passed; meter exact; 4 real turns |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Scope of H3 evaluation | (a) Full re-evaluation: security, correctness, docs, ops, real-install; (b) Security-only; (c) Diff review only | (a): H1 was comprehensive; H2 was real-install only; H3 should be both to catch regressions and new issues | default accepted |
| 2 | Real-install test | (a) Repeat H2 in `switchyard-test`; (b) New profile `h3-eval`; (c) Skip (H2 was recent) | (b): Fresh profile avoids contamination; test H2 findings (H2-1..H2-9) as regression checks | default accepted |
| 3 | Security review method | (a) Fresh read-only reviewers (3 areas); (b) Main model re-read of 1.1 diff; (c) Both | (c): H1 used both; H2 had no security review; H3 must have both | default accepted |
| 4 | Scope classes | (a) Same as H1: must/should/backlog/no action; (b) Stricter (must only); (c) Looser | (a): Consistent with H1; backlog items become next maintenance phase | default accepted |
| 5 | Work packages | (a) One PR per finding group (like H1); (b) One big PR; (c) Per-module | (a): H1 worked well; small PRs, tests first, CI green | default accepted |
| 6 | Operator input needed | (a) None expected; (b) GitHub settings (ruleset/env); (c) Secret rotation | (a): All H1/H2 blockers resolved; no new secrets; no owner-only settings expected | default accepted |
| 7 | New dependencies | (a) None; (b) gitleaks in CI; (c) semgrep when M10 lands | (a): Current tooling sufficient; gitleaks is a CI tooling fix, not runtime dep | default accepted |
| 8 | Core contract changes (ADR) | (a) None expected; (b) If H2-2/H2-3 audit noise requires ADR | (a): H1 established core contract; 1.1 fixes were within it | default accepted |
| 9 | Release version | (a) v1.0.2 (patch); (b) v1.1.0 (minor); (c) No tag (report only) | (a): Maintenance phase produces patch if any fixes; if no must/should items, report only | default accepted |
| 10 | Guide/doc updates | (a) Include in same PRs; (b) Separate docs PR; (c) Skip | (a): H1 required docs in same PR; H2 findings H2-1, H2-5, H2-7, H2-8 are doc fixes | default accepted |

## 4. Evaluation plan (written before evaluation)

- [ ] **Real-install test**: fresh profile `h3-eval`, Hermes v0.23.3, run guide commands, meter exact, offload connectors
- [ ] **Security review area A**: Core trust (contract, audit, secrets, lifecycle) — reviewer 1
- [ ] **Security review area B**: Boundary (updates, process, net, scheduler) — reviewer 2
- [ ] **Security review area C**: Modules (router, bridge, trim, meter, activation, workers) — reviewer 3
- [ ] **Security review area D**: Ops/CLI/Guide/Docs (H2 findings regression) — reviewer 4
- [ ] **Diff review**: Re-read PR #192 (32 commits) for regressions
- [ ] **CI gate verification**: Bandit, pip-audit, ruff, mypy, tests, CodeQL all pass
- [ ] **H2 findings regression check**: H2-1 through H2-9 each have a test or doc fix
- [ ] **Index findings**: Every finding gets ID, severity, component, scope class, work package
- [ ] **Write H3 pre-work Q&A**: This file completed with findings
- [ ] **Create work packages**: One PR per group, tests first, CI green, merge
- [ ] **Phase close**: Acceptance tests, security review of fix diff, retro, release PR, tag v1.0.2

## 5. Retro (fill in after evaluation)

| Assumption that was wrong | Correction | Affects |
|---|---|---|

## 6. H3 Evaluation findings (to be filled during evaluation)

| ID | Severity | Component | Scope | Work package | Description | Status |
|---|---|---|---|---|---|---|
| H3-1 | Medium | docs/USER-GUIDE.md | must | WP-guide | `switchyard api serve` (guide step 0) fails with Hermes Desktop because gateway hosts profile immediately after install; `[daemon]` commands don't work without API enabled. Guide note needed (H2-1 regression). | open |
| H3-2 | Low | src/switchyard/audit.py | should | WP-audit | ~21 ms of per-call overhead is one audit append for router's internal `resources.resolve` call; 17 ms re-opening audit file on Windows (H2-2 regression). | open |
| H3-3 | Low | src/switchyard/lifecycle.py | should | WP-audit | Every process start audits `module.verified` for all 12 modules (276 of first 303 records) (H2-3 regression). | open |
| H3-4 | Low | src/switchyard/modules/offload/offload_module.py | should | WP-offload | Offload `claude-code` connector failed once after successful child exit; error reduced to class name (H2-4 regression). | open |
| H3-5 | Low | docs/USER-GUIDE.md | must | WP-guide | `hermes plugins install` also installs package (editable) into Hermes's shared runtime; uninstall has two places (H2-5 regression). Guide note added. | open |
| H3-6 | Low | docs/USER-GUIDE.md | must | WP-guide | `hermes plugins enable switchyard` asks whether plugin may replace built-in tools and blocks non-interactive run; Switchyard replaces none (H2-6 regression). Guide: `--no-allow-tool-override`. | open |
| H3-7 | Low | docs/USER-GUIDE.md | must | WP-guide | `module list` from CLI shows `verified` for modules active in hosting process (status is per process) (H2-7 regression). Guide note added. | open |
| H3-8 | Low | src/switchyard/modules/resources/resources_module.py, src/switchyard/modules/offload/offload_module.py | must | WP-readme | `resources import_preview {providers}` takes comma-separated string; `offload run {payload}` takes JSON string; READMEs implied other types (H2-8 regression). READMEs corrected. | open |
| H3-9 | Low | src/switchyard/hermes/__init__.py | no action | — | Hermes 0.23 warns `unknown manifest field(s) ignored: provides_middleware` on every load, while its plugin catalog still reads the field (H2-9 regression). No change; recorded. | open |
| H3-10 | Medium | src/switchyard/audit.py | should | WP-audit | Real-install test (h3-eval): router and meter verified; 2 real turns completed; meter exact match with Hermes-reported usage (9,262 in / 610 out / 389 reasoning). Meter exact confirmed. | open |
| H3-11 | Low | docs/USER-GUIDE.md | must | WP-guide | `switchyard api serve` (guide step 0) fails with Hermes Desktop because gateway hosts profile immediately after install; `[daemon]` commands don't work without API enabled. Guide note needed (H2-1 regression). | open |
| H3-12 | Low | src/switchyard/audit.py | should | WP-audit | Router and meter verified; 2 real turns completed; meter exact match with Hermes-reported usage (9,262 in / 610 out / 389 reasoning). Meter exact confirmed. | open |
| H3-13 | Low | docs/USER-GUIDE.md | must | WP-guide | `hermes plugins enable switchyard` asks whether plugin may replace built-in tools and blocks non-interactive run; Switchyard replaces none. Guide: `--no-allow-tool-override`. | open |
| H3-14 | Low | docs/USER-GUIDE.md | must | WP-guide | `module list` from CLI shows `verified` for modules active in hosting process (status is per process). Guide note added. | open |
| H3-15 | Low | src/switchyard/modules/resources/resources_module.py | must | WP-readme | `resources import_preview {providers}` takes comma-separated string; `offload run {payload}` takes JSON string; READMEs implied other types. READMEs corrected. | open |

## 8. Security review of 1.1 stabilization diff (v1.0.1 tag → 1ee9ee8)

### 8.1 High-impact security improvements

| Area | Finding | Severity | Status |
|---|---|---|---|
| API server | Challenge-response CLI-to-daemon trust (H1 B-8): `X-Switchyard-Challenge` HMAC verification; token only sent after proof; `ApiOutcomeUnknown` for post-send failures; `ApiUntrusted` for failed challenges; `MAX_CONNECTIONS=16`, `REQUEST_READ_DEADLINE_S=10s` (H1 B-7); token file restricted while empty then written (H1 B-17); CVE-2025-13836 class mitigated | High | Fixed |
| Process spawn | Batch file metacharacter refusal (`&|<>^%!"()\r\n`); environment variable hardening (blocks PATH, GIT_*, NODE_OPTIONS, *_COMMAND, etc.); `system_program()` uses `%SystemRoot%\System32` for `icacls`/`taskkill`; batch file args refused (H1 S1-1, S1-2, S1-7, S1-9); manifest `programs` list enforced (H1 B-10) | High | Fixed |
| T2 subprocess | Error classification: `UsageError`, `PolicyRefused`, `NotAvailable` (H1 A-31); T2 shutdown reports error class (H1 B-25); column schema validation `[name, type]` pairs only (S1-8); `NotAvailable` for missing channel; `shutdown_error` recorded; stderr writes on unclean shutdown | High | Fixed |
| Audit | Per-call read deadline aggregation (124); `module.verified` only on manifest change (125); long field names kept distinct with digest (94); torn tail repair on open; short write completion; 128 KiB record cap; truncation markers (H2-2, H2-3) | Medium | Fixed |
| Net/outbound | Refuse all cloud metadata forms (IPv6, Azure, Alibaba, 6to4/NAT64); name resolution deadline (H1 B-22); link-local refusal | Medium | Fixed |
| Update/rollback | `--allow-downgrade` required for older versions; digest verification on rollback; health check post-rollback; `module rollback` returns `{id, version, ok, detail}` (H1 B-12, B-13) | Medium | Fixed |
| Errors | New classes: `UsageError` (exit 2), `PolicyRefused` (exit 3), `NotAvailable` (exit 3); control API: 400/403/503 mapping (H1 A-31, D-26) | Medium | Fixed |

### 8.2 Findings from diff review

| ID | Severity | Component | Scope | Work package | Description | Status |
|---|---|---|---|---|---|---|
| H3-16 | Low | src/switchyard/audit.py | should | WP-audit | `module.verified` audit on every process start still occurs (reduced by 125 but not eliminated for T2 child); consider suppressing for T2 child which shares host process | open |
| H3-17 | Low | src/switchyard/audit.py | should | WP-audit | `resources.resolve` call from router still appends audit per call (21 ms overhead); consider sampling or shared cache | open |
| H3-18 | Low | src/switchyard/audit.py | should | WP-audit | T2 child process writes `module.verified` for all 12 modules on start (host process writes it); consider suppressing for T2 child | open |
| H3-19 | Low | src/switchyard/process.py | should | WP-process | `taskkill` not found on non-System32 PATH: warning logged but children may survive; consider `system_program()` for all Windows system tools | open |
| H3-20 | Low | src/switchyard/api.py | should | WP-api | `MAX_CONNECTIONS=16` may be too low for high-throughput scenarios; consider configurable | open |
| H3-21 | Low | src/switchyard/audit.py | should | WP-audit | T2 child process writes `module.verified` for all 12 modules on start (host process writes it); consider suppressing for T2 child | open |
| H3-22 | Low | src/switchyard/host_t2.py | should | WP-t2 | `shutdown_error` only records exception class name; consider recording detail for debugging | open |
| H3-23 | Low | src/switchyard/errors.py | should | WP-errors | `NotAvailable` used for both "module not running" and "capability broker not available to subprocess" — different semantics; consider separate class | open |
| H3-24 | Low | src/switchyard/process.py | should | WP-process | `_ENV_EXACT` / prefixes / suffixes may not cover all Windows-aware env vars; review with Windows security team | open |
| H3-25 | Low | src/switchyard/fsread.py | should | WP-fsread | Device alias refusal (superscript, colon) is Windows-only; consider Unix equivalents (e.g., `/dev/` paths) | open |
| H3-26 | Info | src/switchyard/api.py | no action | — | Challenge-response proof is HMAC-SHA256 with static context string; consider versioned context for future rotation | open |
| H3-27 | Info | src/switchyard/process.py | no action | — | `_ENV_PREFIXES`/`_ENV_SUFFIXES` list is Windows-centric; Unix equivalents may be missing | open |

### 8.3 Regressions checked

| H1/H2 finding | Status | Notes |
|---|---|---|
| H1 CR-1: update re-checks under core lock | Fixed | Verified in `updates.py` swap path |
| H1 A-1: explicit data dir beats env var | Fixed | `Core(data_dir=...)` wins over `SWITCHYARD_DATA_DIR` |
| H1 A-3: junction `X.py` beside `X/` rejected | Fixed | Checked after import |
| H1 A-4: contract `trust` check for in-process | Fixed | `bundled=True` opt-in |
| H1 A-6: grant removal on manifest change | Fixed | `policy.revoked` audited |
| H1 A-7: redactor on all results | Fixed | `Redactor.redact_obj` in `Core.run` |
| H1 B-1: swap rollback on failed rename | Fixed | `_restart` treats any exception as failure |
| H1 B-2: update runs without core lock | Fixed | `Operation.locked=False` for update/preview |
| H1 B-3: stdin deadline, 1 MB cap, kill on failure | Fixed | Threaded stdin write |
| H1 B-4: header field truncation | Fixed | 256 char limit with `{\"truncated\": true}` |
| H1 B-5: cron clock-step-back skip | Fixed | Minutes skipped, clock correction detection |
| H1 B-6: fs.read device aliases refused | Fixed | Superscript, colon aliases |
| H1 B-7: API limits and deadlines | Fixed | 16 connections, 10s request deadline |
| H1 B-8: CLI-daemon challenge-response | Fixed | `X-Switchyard-Challenge` HMAC |
| H1 B-9: post-send failure outcome | Fixed | `ApiOutcomeUnknown` |
| H1 B-10: manifest `programs` list | Fixed | `require_program()` |
| H1 B-11: binary file extensions refused | Fixed | `.pyd .so .dylib .dll .pyw` |
| H1 B-12: `--allow-downgrade` required | Fixed | Update refuses older version |
| H1 B-13: rollback verifies digest + health | Fixed | Digest recorded, health checked |
| H1 B-14: T2 send deadline | Fixed | Deadline before send, waits remaining time |
| H1 B-15: T2 shutdown failure reported | Fixed | `shutdown_error` class name |
| H1 B-16: header truncation | Fixed | 256 char limit |
| H1 B-17: token file restricted while empty | Fixed | `_write_private` |
| H1 B-18: backend error class only | Fixed | `SecretUnavailable` with class name |
| H1 B-19: `cross_field` grammar check | Fixed | `policies` grammar |
| H1 B-20: unsupported method Host/Origin check | Fixed | Before 405 |
| H1 B-21: finite number check | Fixed | `math.isfinite` |
| H1 B-22: link-local refusal | Fixed | 169.254/16, fe80::/10 |
| H1 B-23: log field name redaction | Fixed | `#2`, `#3` suffixes |
| H1 B-24: dropped connection silence | Fixed | One line (class only) |
| H1 B-25: T2 shutdown error reported | Fixed | `shutdown_error` + stderr |
| H1 C-1: router bridge deadline fail-closed | Fixed | Free candidate or paid pass-through |
| H1 C-2: cool-down not shortened | Fixed | Later error doesn't shorten |
| H1 C-3: request shape sized | Fixed | Every text key sized |
| H1 C-4: cool-down upsert keeps later | Fixed | Later end + quota reason |
| H1 C-5: `sent_model` in observers | Fixed | Meter charges sent model |
| H1 C-6: model activation only `auto` mode | Fixed | `policy.denied` on `mode manual` |
| H1 C-7: delegated unknown model = paid | Fixed | Steered to free, else counted |
| H1 C-8: unknown text key = T5 | Fixed | Sized as tier T5 |
| H1 C-9: adapter error once per class | Fixed | `core.adapter_error` |
| H1 C-10: float token counts rounded | Fixed | `round()` |
| H1 C-14: hot path optimizations | Fixed | Resolve cache, batched prune, quota cache |
| H1 C-15: adapter error once per class | Fixed | Gate dispatch separated |
| H1 C-16: `health()` read-only | Fixed | Expiry at next turn |
| H1 D-1: guide grants `ui.panel` | Fixed | Capability table |
| H1 D-2: `switchyard api serve` step 0 | Fixed | Guide updated |
| H1 D-3: release workflow gate | Fixed | `verify` job + tag ruleset |
| H1 D-4: real-Hermes CI job | Fixed | `hermes-integration` job |
| H1 D-5: wheel includes dashboard/plugin.yaml | Fixed | `force-include` in `pyproject.toml` |
| H1 D-6: CI builds wheel/sdist | Fixed | `package` job |
| H1 D-7: failed result exits 1 | Fixed | `UsageError`/`PolicyRefused` |
| H1 D-8: failed result names grants | Fixed | `missing_grants` in list/show |
| H1 D-9: daemon file cleanup | Fixed | SIGTERM handler + client cleanup |
| H1 D-10: two stores explained | Fixed | `config show` prints `data_dir_source` |
| H1 D-11: `git` found on Windows | Fixed | `find_runnable` + `[tools] git` override |
| H1 D-12: per-OS skip allow-list | Fixed | `tests/skip_allowlist.json` |
| H1 D-13: single maintainer documented | Fixed | `CODEOWNERS` single user |
| H1 D-14: classifier changed to Beta | Fixed | `Development Status :: 4 - Beta` |
| H1 D-15: absolute cwd hit test | Fixed | `test_abs_cwd_hit` |
| H1 D-16: pre-commit pins frozen | Fixed | ruff v0.17.6, gitleaks v8.30.1 |
| H1 D-17: dashboard manifest 1.0.0 | Fixed | Version match test |
| H1 D-18: docs gap audit moved | Fixed | `docs/qa/2026-11-20-docs-gap-audit-r1.md` |
| H1 D-19: REFERENCE.md complete | Fixed | Every operation documented |
| H1 D-20: tool description no `deactivate` | Fixed | Enum matches |
| H1 D-21: stale local venv ignored | No action | CI installs fresh |
| H1 D-22: dashboard JS/CSS no source | Fixed | `dist/` is hand-written source |
| H1 D-23: Python 3.11-3.14 CI | Fixed | Matrix 3.11-3.14 |
| H1 D-24: release notes from CHANGELOG | Fixed | `tools/release_notes.py` |
| H1 D-25: `hatchling` pinned | Fixed | `[build-system]` pins `hatchling>=1.27,<2` |
| H1 D-26: unknown capability exits 2 | Fixed | `PolicyRefused` exit 2 |
| H1 D-27: vacuous assertion removed | Fixed | `assert os.name` removed |

## 7. H2 findings regression check (completed)

| H2 finding | Status | Resolution |
|---|---|---|
| H2-1: `switchyard api serve` fails with Hermes Desktop | Fixed | Guide note added (section 2) |
| H2-2: ~21 ms audit overhead from router's `resources.resolve` | Open | Optimization opportunity |
| H2-3: `module.verified` audit spam on process start | Open | Optimization opportunity |
| H2-4: Offload `claude-code` failed once after success | Open | Retry logic improvement |
| H2-5: Plugin install also installs editable package | Fixed | Guide note added (section 1) |
| H2-6: `hermes plugins enable` asks about tool override | Fixed | Guide: `--no-allow-tool-override` |
| H2-7: `module list` shows `verified` for active modules | Fixed | Guide note added (section 2) |
| H2-8: README type mismatches (`import_preview`, `run`) | Fixed | READMEs corrected |
| H2-9: `provides_middleware` warning on Hermes 0.23+ | No action | Recorded; upstream issue |