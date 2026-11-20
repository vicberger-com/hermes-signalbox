# Pre-work Q&A: M10 security testing connectors

Date: 2026-11-20. Previous phase: M9, tag v0.10.0.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| M9 | `notify` and the inbox exist | New high and critical findings and scanner failures are announced there |
| M6 | Each check isolated; failure becomes a finding | A failing scanner is a finding, never silence |
| M8 retro | Core-side work on untrusted text needs its own bounds | Scanner output capped at 20 MB and 2000 findings per run; parsers keep bounded fields only |

## 2. Research record

| Scanner | License (checked 2026-11-20) | Invocation used | Notes |
|---|---|---|---|
| gitleaks | MIT | `gitleaks detect --no-git --redact --source <t> --report-format json --report-path -` | Exit 1 = leaks found; `--redact` keeps secrets out of the report; only rule and location stored |
| bandit | Apache-2.0 | `bandit -r <t> -f json -q` | Exit 1 = issues found |
| pip-audit | Apache-2.0 | `pip-audit -f json --progress-spinner off <t>` | Exit 1 = vulnerabilities; queries PyPI/OSV over the network |
| osv-scanner | Apache-2.0 | `osv-scanner scan source --format json -r <t>` | Exit 1 = vulnerabilities; queries osv.dev |
| semgrep | LGPL-2.1 (CLI), rules vary | `semgrep scan --json --metrics off --disable-version-check --config <rules> <t>` | `--metrics off`; registry rule sets are downloaded |
| trivy | Apache-2.0 | `trivy fs --format json --quiet <t>` | Exit 0 by default; secrets reported without the match kept |

All run as separate processes through the `process.spawn` broker (minimal environment, no shell, timeout,
audited by program name and exit code only). Nothing is bundled; the operator installs the scanners they want.
The skills audit is covered by adding Hermes skill directories to `targets`.

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Smallest scope? | | One `scanner` module with six adapters, scheduled and on-demand runs, normalised and de-duplicated findings, failure findings, announcements. "On change" triggers deferred (a file watcher needs `fs.read` scopes per target) | default accepted |
| 2 | Capabilities | | `process.spawn`, `schedule`, `ui.panel`; `notify` optional | default accepted |
| 3 | Reuse, adapt or write? | | Write adapters; scanners stay external | default accepted |
| 4 | New dependencies? | | None | default accepted |
| 5 | Security | | Threat table below | default accepted |
| 6 | State; uninstall | | Tables `findings` (resolved capped at 5000), `runs` (last 500) | default accepted |
| 7 | Control surface | | Read-only `report`; human-only `findings`, `run_now`. Config `targets`, `scanners`, `interval_hours` (24), `timeout_seconds` (300), `semgrep_config`. Activation manual | default accepted |
| 8 | Network use | | pip-audit, osv-scanner, semgrep and trivy contact their databases; documented; choose `scanners` to avoid it | default accepted |
| 9 | Core contract change? | | None | default accepted |
| 10 | Operator input? | | Install scanners and set `targets` (documented) | default accepted |

### Threats and tests (question 5)

| Threat | Control | Test |
|---|---|---|
| A scanner failure goes unnoticed | Missing program, timeout, unexpected exit and unparsable output become `scanner:<name>:failed` findings and are announced | `test_scanner_failure_is_reported_never_silent` |
| Found secrets copied into the store, dashboard or model | gitleaks `--redact`; parsers keep rule and location, never matches | `test_parsers_on_recorded_outputs` |
| Option injection through config | `targets` must be absolute paths; `semgrep_config` may not start with `-`; argv lists, no shell | `test_settings_and_permissions` |
| Model reads finding details or triggers scans | `findings` and `run_now` are human-only; `report` holds counts | same |
| Huge scanner output | 20 MB output cap, 2000 findings per run, bounded fields | parsers |

## 4. Acceptance tests (written before code)

- [x] Seeded-vulnerability fixtures are detected (`tests/fixtures/scanners/seeded/`; real bandit when installed,
  recorded real-format outputs for the others).
- [x] Scanner failure is reported, never silent.

## 5. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
