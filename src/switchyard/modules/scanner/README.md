# Scanner (bundled module, M10)

Runs external security scanners against directories you choose, on a schedule or on demand. Q&A:
[docs/qa/11-m10-prework.md](../../../../docs/qa/11-m10-prework.md).

## Scanners

| Scanner | Finds | Network |
|---|---|---|
| gitleaks | secrets in files (run with `--redact`; only the rule and location are stored) | no |
| bandit | Python security issues | no |
| pip-audit | vulnerable Python dependencies | yes (PyPI, OSV) |
| osv-scanner | vulnerable dependencies in lockfiles | yes (osv.dev) |
| semgrep | static analysis with a rule set (`semgrep_config`, metrics off) | yes (rule download) |
| trivy | vulnerable packages, misconfigurations and secrets in a file tree | yes (database download) |

Install the ones you want; nothing is bundled. Add Hermes skill directories to `targets` to audit skills.

## Findings and failures

Findings are normalised, de-duplicated per scanner, target, rule and location, and resolved when a later run no
longer reports them. New high and critical findings are announced (`scanner.finding` event and, with `notify`,
the inbox). A scanner that is missing, times out, exits unexpectedly or prints output that does not parse
becomes a `scanner:<name>:failed` finding and is announced: **failure is never silent**. It resolves when the
scanner runs cleanly again.

## Turning it on

Grant `process.spawn`, `schedule`, `ui.panel` (and `notify` for inbox alerts), set `targets`, then activate.

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `report` (counts and recent runs) | yes |
| Action | `findings {state: open/acked/resolved/all, limit}`, `run_now` | no |
| Panel | `scanner.status` | |
| Config | `[modules.scanner]` `targets` (absolute directories), `scanners`, `interval_hours` (24, 1-168), `timeout_seconds` (300, 10-600), `semgrep_config` (`p/security-audit`) | |

## State and removal

Tables `findings` (resolved capped at 5000) and `runs` (last 500). Removed with the module unless `keep_data`.
