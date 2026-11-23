# Pre-work Q&A: H3 maintenance after v1.0.1 + 1.1 stabilization

Date: 2026-11-23. Previous phase: H2 (real install verification), tag v1.0.1.

This is a maintenance phase (H3) following the H1/H2 pattern. Scope comes from the H3 evaluation
(docs/qa/16-h3-eval-prework.md). All findings are from the fresh evaluation of v1.0.1 + 1.1
stabilization (1ee9ee8) and the security review of the 1.1 stabilization diff.

Answer every question. Take the recommended option, mark it **default accepted**, and continue.
Only items that match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| H3 evaluation | 15 findings from real-install test (H3-1..H3-15) and H2 regression | H2-1,5,6,7,8 fixed via guide/README; H2-2,3,4,9 remain open |
| Security review of 1.1 diff | 12 high/medium improvements verified; 12 new findings (H3-16..H3-27) | All H1/H2 regressions checked (50+ items) — all fixed |
| H1/H2 | All H1 backlog + D-22 fixed in 1.1 stabilization (PR #192) | Baseline is clean; no known security issues from tooling |

## 2. Research record

| Topic | Source (URL, commit or version, date read) | Finding |
|---|---|---|
| Current codebase | `1ee9ee8` (v1.0.1 + 1.1 stabilization), 2026-11-23 | 6418 statements, 995 tests pass, 94.81% branch coverage |
| Audit noise | `src/switchyard/audit.py`, `src/switchyard/lifecycle.py` | `module.verified` on every process start; `resources.resolve` per-call audit; T2 child writes for all 12 modules |
| Process hardening | `src/switchyard/process.py`, `src/switchyard/host_t2.py` | `taskkill` PATH issue; env var hardening coverage; T2 shutdown detail |
| API limits | `src/switchyard/api.py` | `MAX_CONNECTIONS=16`, `REQUEST_READ_DEADLINE_S=10s`; challenge-response proof |
| Error classification | `src/switchyard/errors.py`, `src/switchyard/host_t2.py` | `UsageError`, `PolicyRefused`, `NotAvailable`; `NotAvailable` dual semantics |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Scope of H3 | (a) All 12 work packages as specified; (b) Must/should only, defer backlog | (a): All findings are must/should scope per evaluation | default accepted |
| 2 | Release version | (a) v1.0.2 (patch); (b) v1.1.0 (minor) | (a): Maintenance phase produces patch; no new features | default accepted |
| 3 | WP-audit scope | (a) Suppress T2 child `module.verified`; sample `resources.resolve`; deduplicate process-start audit | (a): Targeted reductions matching H2-2, H2-3, H3-16,17,18,21 | default accepted |
| 4 | WP-process scope | (b) Use `system_program()` for `taskkill`/`icacls` everywhere; expand env var hardening to Unix | (a): Windows fix; (b) parity for Unix — both needed | default accepted |
| 5 | WP-api scope | (a) Make `MAX_CONNECTIONS` and `REQUEST_READ_DEADLINE_S` configurable via `config.toml` | (a): H3-20; allows high-throughput tuning | default accepted |
| 6 | WP-t2 scope | (a) Record exception detail in `shutdown_error` (not just class name) | (a): H3-22; improves debuggability | default accepted |
| 7 | WP-errors scope | (b) Split `NotAvailable` into `ModuleNotRunning` and `BrokerUnavailableToSubprocess` | (a): H3-23; cleaner semantics, but breaking change — use new classes alongside | default accepted |
| 8 | WP-fsread scope | (a) Add Unix device path refusal (`/dev/`, `/sys/`, `/proc/`) alongside Windows aliases | (a): H3-25; parity for Unix | default accepted |
| 9 | WP-readme scope | (a) Add notes: challenge context versioning (H3-26); Unix env var equivalents (H3-27) | (a): Future-proofing documentation | default accepted |
| 10 | Operator input needed | (a) None; (b) Config keys for audit sampling / max connections | (a): Defaults work; config added as optional | default accepted |

## 4. Work packages

One pull request each, in this order. Tests first: each finding gets a regression test that fails before the fix.

| WP | Branch | Area | Findings | Required end state |
|---|---|---|---|---|
| WP0 | `docs/h3-prework` | This plan | — | Merged before any code |
| WP1 | `fix/h3-audit` | Audit noise | H3-16, H3-17, H3-18, H3-21 | T2 child no `module.verified`; `resources.resolve` sampled; process-start audit deduplicated |
| WP2 | `fix/h3-process` | Process hardening | H3-19, H3-24 | `system_program()` for all Windows system tools; Unix env var equivalents |
| WP3 | `fix/h3-api` | API config | H3-20 | `MAX_CONNECTIONS` and `REQUEST_READ_DEADLINE_S` configurable via `config.toml` |
| WP4 | `fix/h3-t2` | T2 shutdown | H3-22 | `shutdown_error` records exception detail (not just class) |
| WP5 | `fix/h3-errors` | Error semantics | H3-23 | New `ModuleNotRunning` and `BrokerUnavailableToSubprocess`; `NotAvailable` deprecated |
| WP6 | `fix/h3-fsread` | Unix device paths | H3-25 | Refuse `/dev/`, `/sys/`, `/proc/` paths on Unix |
| WP7 | `fix/h3-readme` | Future-proofing notes | H3-26, H3-27 | Challenge context versioning note; Unix env var equivalents documented |
| Close | `chore/release-1.0.2` | Phase close | — | Acceptance tests, security review of fix diff, retro, release PR, tag v1.0.2 |

## 5. Acceptance tests (written before code)

- [ ] `tests/unit/test_audit_noise.py`: T2 child does not emit `module.verified`; `resources.resolve` audit count < N per minute; process-start audit deduped
- [ ] `tests/unit/test_process_hardening.py`: `system_program()` used for all Windows tools; Unix env var list blocks known dangerous vars
- [ ] `tests/unit/test_api_config.py`: `MAX_CONNECTIONS` and `REQUEST_READ_DEADLINE_S` read from config; defaults unchanged
- [ ] `tests/unit/test_t2_shutdown.py`: `shutdown_error` includes exception message/detail, not just class name
- [ ] `tests/unit/test_error_semantics.py`: `ModuleNotRunning` and `BrokerUnavailableToSubprocess` raised correctly; `NotAvailable` still works (deprecated)
- [ ] `tests/unit/test_fsread_unix.py`: `/dev/`, `/sys/`, `/proc/` refused on Unix; Windows aliases still refused
- [ ] `tests/unit/test_readme_notes.py`: Challenge context versioning note present; Unix env var equivalents documented
- [ ] All existing tests pass; coverage >= 90% core, >= 85% modules
- [ ] Bandit 0 findings; pip-audit clean; ruff clean; mypy strict clean

## 6. H2 findings regression check (completed)

| H2 finding | Status | Resolution |
|---|---|---|
| H2-1: `switchyard api serve` fails with Hermes Desktop | Fixed | Guide note added (section 2) |
| H2-2: ~21 ms audit overhead from router's `resources.resolve` | Open | WP1 (sampling) |
| H2-3: `module.verified` audit spam on process start | Open | WP1 (dedup/suppress) |
| H2-4: Offload `claude-code` failed once after success | Open | WP2 (retry logic) |
| H2-5: Plugin install also installs editable package | Fixed | Guide note added (section 1) |
| H2-6: `hermes plugins enable` asks about tool override | Fixed | Guide: `--no-allow-tool-override` |
| H2-7: `module list` shows `verified` for active modules | Fixed | Guide note added (section 2) |
| H2-8: README type mismatches (`import_preview`, `run`) | Fixed | READMEs corrected |
| H2-9: `provides_middleware` warning on Hermes 0.23+ | No action | Recorded; upstream issue |

## 7. Retro (fill in after phase close)

| Assumption that was wrong | Correction | Affects |
|---|---|---|