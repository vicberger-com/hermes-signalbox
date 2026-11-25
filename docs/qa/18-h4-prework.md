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
| WP3b | `fix/h4-n1-revoke` | Module lifecycle | H4-N1 (Medium), found while fixing R1-F9; added to the release by operator decision | must |
| WP4 | `fix/h4-f10-dashboard` | Dashboard backend | R1-F10 (High), R1-F11 (Low) | must, should |
| WP5 | `fix/h4-cli-polish` | CLI, operations, reports | R1-F4, R1-F5, R1-F7, R1-F12 (Low) | should |
| WP6 | `docs/h4-guide` | User guide, reference, README | R1-F1, R1-F2, R1-F3, R1-F6, R1-F13, doc-1 (Documentation) | should |
| Close | `chore/release-1.0.3` | Phase close | - | - |

## 5. Acceptance (written before code)

- [x] Every `must` and `should` finding has a regression test named `test_h4_<id>_...` that failed before its fix
- [x] `tests/test_doc_links.py` and `tools/guide_walkthrough.py` pass on the corrected guide
- [x] All existing tests pass on Linux, Windows and macOS; coverage >= 90% core, >= 85% modules
- [x] ruff, mypy strict, bandit, pip-audit clean; `hermes-integration` job green
- [x] Security review of `git diff v1.0.2..HEAD` by fresh read-only reviewers, every finding re-verified
- [ ] Release-candidate rehearsal on the baseline: the sections that failed in the v1.0.2 run pass, and the
      uninstall leaves the baseline snapshot unchanged
- [ ] Release through the `verify` job; tag `v1.0.3`

Close notes:

- Regression tests: `tests/core/test_h4_hosting.py`, `test_h4_unload.py`, `test_h4_mode.py`, `test_h4_revoke.py`,
  `test_h4_dashboard.py`, `test_h4_cli_polish.py`, `tests/test_h4_guide.py`, and the dashboard test in
  `tests/integration/test_real_hermes.py`. Each PR body records its red run; WP6 was proven against unchanged
  `main` in a worktree. `tests/acceptance/test_h4_acceptance.py` checks that every ID in section 6 is fixed and has
  a `test_h4_<id>_` test.
- Platforms and gates: the CI matrix (Linux, Windows, macOS x Python 3.11 to 3.14), ruff, mypy strict, bandit,
  pip-audit, CodeQL, gitleaks and `hermes-integration`, green on every H4 pull request and on the release PR.
- Security review: two fresh read-only reviewers over `git diff v1.0.2..HEAD` (area 1: hosting, host lock, unload,
  mode and revoke; area 2: dashboard data directory, API and CLI routing, reports), 3 and 6 probe scripts. Both
  confirmed each fix. Their two findings were re-checked against the code: see the table below. The maintainer
  re-read the retry-versus-unload path (`HermesAdapter.close` sets `_closing` under `_host_mutex`, which
  `_host_if_allowed` checks under the same mutex; `Core.acquire_hosting` refuses once closed).
- The rehearsal and the tag are proven only by the release itself; their lines stay unticked until then.

| Review finding | Disposition | Reason |
|---|---|---|
| `SWITCHYARD_DATA_DIR` can point the dashboard backend at another directory | By design | Same precedence as the core since H1; setting the Hermes process environment needs the operator's own OS user (DESIGN trust model). Port and token come from the same directory, so the real token is not sent, and the H1 token proof refuses a listener that does not hold it |
| Health cell shows module text without redaction | Not reproduced | The dashboard reads `module health` through the loopback API, whose `_dispatch` redacts every result; the cell is operator-facing, not model input |

## 6. Dispositions (filled in as each fix merges)

| ID | Severity | Status | Pull request | What changed |
|---|---|---|---|---|
| R1-F8 | High | fixed | #197 | A one-shot command that loaded the plugin while the data directory was free became the host for its lifetime; a gateway starting in that window never hosted and ran turns without gates. Now only the gateway runtime, or a process that has run a turn, may host, and it retries every 5 s ([ADR-0014](../adr/0014-hermes-hosting-process.md)). `config show`, `module show` and `module health` name the hosting pid |
| R1-F14 | Medium | fixed | #198 | The plugin registered no unload callback, so after disable and uninstall a running gateway kept the host lock, the loopback API and the active modules until restart. `register()` now passes Hermes an `on_unload` callback that stops everything (reason `unload`); `Core.close` releases the lock even when a stop step fails ([ADR-0014](../adr/0014-hermes-hosting-process.md), "Unload"). The note that `HermesAdapter.close()` left the core open was not reproduced |
| R1-F9 | Medium | fixed | #199 | `module mode` from the command line wrote only the state store; the hosting process kept the mode it had read at load, ignored the change and wrote its old mode back on its next activation, and every command-line call reset the `state` column of running modules. The host now reads the mode from the store for every decision and its tick stops a module set to `disabled`; each write touches only its own columns; offline `module remove` is refused while another process hosts ([ADR-0014](../adr/0014-hermes-hosting-process.md), "Mode") |
| R1-F10 | High | fixed | #200 | The dashboard backend looked for the loopback API in `plugin-data/switchyard`, a directory it created, while the plugin uses the directory Hermes gives it (`plugin-data/agent-plugin-switchyard-<digest>`), so the tab said "API is off". It now resolves the directory with Hermes's `PluginState` naming and the core's precedence (`switchyard.hermes.dashboard`) and creates nothing; a real-Hermes test compares it with the loaded plugin's directory |
| R1-F11 | Low | fixed | #200 | Module list rows carried no health; the backend now fills the Health column from each running module's check (`ok`, `failing: <detail>`, `unknown`) |
| R1-F4 | Low | fixed | #202 | `module grant` to an unknown module was refused as a policy denial (exit 3, API 403); it is now a usage error (exit 2, API 400) as REFERENCE's exit-code table says, and still audited as `policy.grant_refused` |
| R1-F5 | Low | fixed | #202 | A live command run while the gateway hosts with the API off told the operator to start `switchyard api serve`, which cannot start there; it now names `/switchyard <command>` in a chat, or `[api] enabled = true` plus a Hermes restart |
| R1-F7 | Low | fixed | #202 | Setting the mode a module already has recorded `module.mode_changed`; it now records nothing (the mode is compared with the stored one) |
| R1-F12 | Low | fixed | #202 | The usage report printed an exception class name (`unavailable: UsageError`) for a module that was not running; it now says `not installed`, `not active` or `action failed` |
| R1-F1 | Documentation | fixed | #203 | README and guide section 1: install by owner/repository and commit only; the catalog's `hermes-switchyard` entry is an unrelated project |
| R1-F2 | Documentation | fixed | #203 | Guide section 1: the install's "custom (unreviewed) source" warning is expected for a plugin outside the catalog |
| R1-F3 | Documentation | fixed | #203 | Guide section 4: the model tools reach new chats only after `hermes plugins enable` (Hermes defers plugin tools to the next session) |
| R1-F6 | Documentation | fixed | #203 | Guide section 3: a grant records consent and never starts a module; in a running Hermes start it with `/switchyard module activate <id>` |
| R1-F13 | Documentation | fixed | #203 | Guide sections 6 and 7: reports and `check_updates` / `preview` / `update` / `rollback` are chat-only while Hermes hosts |
| doc-1 | Documentation | fixed | #203 | Guide section 9: disable before remove, what Hermes's reply means, when to restart, every data directory; the second section 5 is section 11; wiki page matches |
| H4-N1 | Medium | fixed | #201 | Found while fixing R1-F9, same cause: `module revoke` from the command line stopped a module only in its own process; while Hermes hosted, the module kept running there with the hooks, gates and jobs registered under the revoked grant until restart. The host's tick now stops an active module whose required grants are incomplete (reason `revoked <capability>`) ([ADR-0014](../adr/0014-hermes-hosting-process.md), decision 10) |

## 7. Retro (fill in after phase close)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
| "The guide walkthrough proves the install" (H1 retro already said this) | The walkthrough runs the standalone daemon; the v1.0.2 run failed only in the hosted (gateway) setup. The release-candidate rehearsal on the baseline is now a step before the tag | Phase close |
| `HermesAdapter.close()` never closed the core (R1-F14 root-cause note) | Not reproduced: the missing `on_unload` callback was the whole cause. A root-cause note is a hypothesis until a test pins it | Maintenance triage |
| The hosting process may keep a module's mode and status in memory | Another process (the command line) writes them; the host reads mode and grants from the store before each decision, and each writer touches only its own columns (R1-F9, H4-N1) | Core, every offline operation |
| An unknown name on `grant` is a denial | REFERENCE's exit-code table calls an unknown name a usage error; the reference is the contract (Q&A question 5) | CLI, API, model tool errors |
| A timing test bounded `<= 1.0` on a deadline of 1.0 is safe | On Windows the monotonic clock may not tick between setting the deadline and the first read; bound with a small float tolerance | Tests |
