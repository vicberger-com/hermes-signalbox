# Pre-work Q&A: H4 maintenance after the v1.0.2 install acceptance

Date: 2026-11-24. Previous phase: H3 (maintenance), tag v1.0.2.

This is a maintenance phase (H4). Scope comes from a recorded review: the first acceptance install of
v1.0.2 (`41ccbb8`) on a real Hermes Desktop baseline, worked through the user guide section by section. The run
failed, so v1.0.2 does not go to user-level testing; H4 fixes every finding and releases v1.0.3, which the
three counted acceptance installs then run against.

Per the maintenance rules in [BUILD-PLAN.md](../BUILD-PLAN.md), findings about the behaviour of a released
version are listed here by ID, severity, component and work package only. Mechanism, evidence and reproduction
are in the maintainer's private record until the fix merges; each disposition is published in section 6 with
the pull request that fixes it.

Answer every question. Take the recommended option, mark it **default accepted**, and continue.
Only items that match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| H3 retro | One pull request for seven work packages was hard to review and slow in CI | One work package is one pull request again |
| H1 retro | "Release passed its own gates but had never been installed" | The release candidate is installed on the baseline before the tag (rehearsal of the failed sections) |
| v1.0.2 acceptance run | The guide's own steps fail on a clean install in two sections | Both are `must`; the guide walkthrough alone does not cover a hosted install |
| Operator decision | Every finding of the run is fixed in v1.0.3, none deferred | No `backlog` class in this phase |

## 2. Research record

| Topic | Source (URL, commit or version, date read) | Finding |
|---|---|---|
| Codebase | `41ccbb8` (v1.0.2), 2026-11-24 | Baseline for every work package |
| Hermes Agent on the baseline | Desktop payload, Hermes Agent v0.23.3, `hermes --version`, 2026-11-24 | The version the acceptance installs run on |
| Host API facts behind WP1 and WP2 | Hermes Agent source at tags v0.22.0 to v0.23.3, read 2026-11-24 | Recorded in the ADR that merges with each fix (maintenance rule 5) |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Scope | (a) Every finding of the run; (b) `must` only | (a): operator decision; the counted installs need a guide that matches behaviour | default accepted |
| 2 | Release version | (a) v1.0.3 (patch); (b) v1.1.0 | (a): fixes and corrected documented behaviour only | default accepted |
| 3 | Pull requests | (a) One per work package; (b) one for the phase | (a): H3 retro | default accepted |
| 4 | ADRs | (a) One ADR for the two core behaviour changes (WP1, WP2), in the pull request that makes each change; (b) none | (a): maintenance rule 2 | default accepted |
| 5 | R1-F4: exit code or guide | (a) Decide by `docs/REFERENCE.md` and the exit-code table; (b) always change the code | (a): the reference is the contract | default accepted |
| 6 | Catalog name collision (R1-F1) | (a) Document: install by owner/repository and commit only; a rename is a separate decision | (a): operator decision | default accepted |
| 7 | New dependencies | (a) None | (a): stdlib-only core (ADR-0001) | default accepted |
| 8 | Operator input needed | (a) None for the code; the acceptance installs and gateway restarts stay operator steps | (a) | default accepted |

## 4. Work packages

One pull request each, in this order. Tests first: each finding gets a regression test that fails before the fix.

| WP | Branch | Component | Findings | Class |
|---|---|---|---|---|
| WP0 | `docs/h4-prework` | This plan | - | - |
| WP1 | `fix/h4-f8-hosting` | Hermes adapter, core hosting | R1-F8 (High) | must |
| WP2 | `fix/h4-f14-unload` | Hermes adapter, core shutdown | R1-F14 (Medium) | must |
| WP3 | `fix/h4-f9-mode` | Module lifecycle, discovery, CLI | R1-F9 (Medium) | must |
| WP4 | `fix/h4-f10-dashboard` | Dashboard backend | R1-F10 (High), R1-F11 (Low) | must, should |
| WP5 | `fix/h4-cli-polish` | CLI, operations, reports | R1-F4, R1-F5, R1-F7, R1-F12 (Low) | should |
| WP6 | `docs/h4-guide` | User guide, reference, README | R1-F1, R1-F2, R1-F3, R1-F6, R1-F13, doc-1 (Documentation) | should |
| Close | `chore/release-1.0.3` | Phase close | - | - |

## 5. Acceptance (written before code)

- [ ] Every `must` and `should` finding has a regression test named `test_h4_<id>_...` that failed before its fix
- [ ] `tests/test_doc_links.py` and `tools/guide_walkthrough.py` pass on the corrected guide
- [ ] All existing tests pass on Linux, Windows and macOS; coverage >= 90% core, >= 85% modules
- [ ] ruff, mypy strict, bandit, pip-audit clean; `hermes-integration` job green
- [ ] Security review of `git diff v1.0.2..HEAD` by fresh read-only reviewers, every finding re-verified
- [ ] Release-candidate rehearsal on the baseline: the sections that failed in the v1.0.2 run pass, and the
      uninstall leaves the baseline snapshot unchanged
- [ ] Release through the `verify` job; tag `v1.0.3`

## 6. Dispositions (filled in as each fix merges)

| ID | Severity | Status | Pull request | What changed |
|---|---|---|---|---|
| R1-F8 | High | fixed | #197 | A one-shot command that loaded the plugin while the data directory was free became the host for its lifetime; a gateway starting in that window never hosted and ran turns without gates. Now only the gateway runtime, or a process that has run a turn, may host, and it retries every 5 s ([ADR-0014](../adr/0014-hermes-hosting-process.md)). `config show`, `module show` and `module health` name the hosting pid |
| R1-F14 | Medium | fixed | #198 | The plugin registered no unload callback, so after disable and uninstall a running gateway kept the host lock, the loopback API and the active modules until restart. `register()` now passes Hermes an `on_unload` callback that stops everything (reason `unload`); `Core.close` releases the lock even when a stop step fails ([ADR-0014](../adr/0014-hermes-hosting-process.md), "Unload"). The note that `HermesAdapter.close()` left the core open was not reproduced |
| R1-F9 | Medium | open | - | - |
| R1-F10 | High | open | - | - |
| R1-F11 | Low | open | - | - |
| R1-F4 | Low | open | - | - |
| R1-F5 | Low | open | - | - |
| R1-F7 | Low | open | - | - |
| R1-F12 | Low | open | - | - |
| R1-F1 | Documentation | open | - | - |
| R1-F2 | Documentation | open | - | - |
| R1-F3 | Documentation | open | - | - |
| R1-F6 | Documentation | open | - | - |
| R1-F13 | Documentation | open | - | - |
| doc-1 | Documentation | open | - | - |

## 7. Retro (fill in after phase close)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
