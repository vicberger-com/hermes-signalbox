# Pre-engagement Q&A

Status values: **answered** (operator said so), **default accepted** (recommended option taken under the
auto-accept rule; change by editing this file before the phase that uses it), **operator action** (manual step).

## A. Repository and access

| # | Question | Answer | Status |
|---|---|---|---|
| A1 | GitHub owner | Organization `vicberger-com` (moved from the personal account `vicaberger` on 2026-11-19 so that branch protection and security features can be applied) | answered |
| A2 | Repository name | `hermes-switchyard` | answered |
| A3 | Who creates the repository | Operator, empty (no README, license or .gitignore), because a token scoped to one repository cannot exist before the repository does | operator action |
| A4 | Persistent connection method | Fine-grained personal access token with the organization as resource owner, limited to this one repository, stored in Windows Credential Manager through Git Credential Manager, entered only by the operator | answered; operator action |
| A5 | Token permissions | Repository: Contents RW, Pull requests RW, Issues RW, Workflows RW, Actions R, Commit statuses R, Metadata R. Add Administration RW only if the agent should set branch protection; otherwise the operator sets it once | default accepted |
| A6 | Token lifetime | 90 days; the marker file records expiry and the check command warns 14 days ahead | default accepted |
| A7 | Visibility | Private until the M0 security gate passes, then public (open source is priority 3; CodeQL, Scorecard and attestations need a public repository on a personal account) | default accepted |
| A8 | Branch model | Trunk: protected `main`, short-lived branches, squash merge, conventional commits, signed tags | default accepted |

## B. Product

| # | Question | Answer | Status |
|---|---|---|---|
| B1 | Name | Hermes Switchyard, package `switchyard`, CLI `switchyard` | default accepted |
| B2 | License | Apache-2.0 | default accepted |
| B3 | Language and floor | Python >= 3.11 | default accepted |
| B4 | Platforms | Windows, Linux, macOS; tested in CI on all three | default accepted |
| B5 | Minimum Hermes version | 0.22; developed against 0.23.2 | default accepted |
| B6 | Module manifest format | TOML (`module.toml`) | default accepted |
| B7 | Third-party module isolation | Subprocess with JSON-RPC; in-process only for modules in this repository | default accepted |
| B8 | Remote access to the control API | None in core; loopback only | default accepted |
| B9 | Telemetry | None. No outbound calls except hosts a module declares and the user grants | default accepted |
| B10 | Prompt and completion logging | Off by default; per-module debug stream the user can turn on | default accepted |

## C. Environment and operations

| # | Question | Answer | Status |
|---|---|---|---|
| C1 | Default secrets backend on this workstation | OS keyring (Windows Credential Manager). Vaultwarden backend built in M1 and preferred once the local Vaultwarden is in service | default accepted |
| C2 | Cloud-hosted secret stores | Not supported, by operator policy | answered (standing rule) |
| C3 | Paid resources during the build | None enabled by the build itself; enabling any is a stop condition | default accepted |
| C4 | Hermes plugin packaging | Repository root carries `plugin.yaml` and a thin `__init__.py` that imports `switchyard.hermes`; confirm against `hermes plugins install` behaviour in M0 research | default accepted |
| C5 | Dashboard front end | Plain ES modules without a build step if the Hermes dashboard plugin loader accepts it; decide in the M9 Q&A | default accepted |
| C6 | First offload connectors | JevK5 (installed locally) and n8n; others by demand | default accepted |
| C7 | Release signing | Sigstore keyless through GitHub Actions once public | default accepted |

## D. Open questions carried to later phases

| # | Question | Phase |
|---|---|---|
| D1 | Does Hermes expose `model_switch` and per-task model overrides in `delegate_task` as the requirement document states? | M3, M7 |
| D2 | Where did `JerryLiu369/hermes-proactive-agent` move, and under what license? | M6 |
| D3 | Does `Rainhoole/hermes-agent-acp-skill` exist under another name? | M11 |
| D4 | Which free providers does the operator already hold keys for? (names only) | M2 |
| D5 | Budget ceilings and paid-gating thresholds | M3, M4 |
