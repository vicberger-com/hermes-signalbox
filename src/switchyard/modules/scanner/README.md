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
| semgrep | static analysis with a rule set (`semgrep_config`, metrics off); only rule ids are stored, never messages (they can quote matched source) | yes (rule download) |
| trivy | vulnerable packages, misconfigurations and secrets in a file tree | yes (database download) |

Install the ones you want; nothing is bundled. Add Hermes skill directories to `targets` to audit skills.

## Findings and failures

Findings are normalised, de-duplicated per scanner, target, rule and location, and resolved when a later run no
longer reports them. New high and critical findings are announced (`scanner.finding` event and, with `notify`,
the inbox). A scanner that is missing, times out, exits unexpectedly or prints output that does not parse
becomes a `scanner:<name>:failed` finding and is announced: **failure is never silent**. So does no output
from gitleaks or osv-scanner (they always print JSON), output over 20 MB, or more than 2,000 findings (a
partial result never resolves anything). Scans never overlap, and a scheduled run skipped because the previous
one is still going is audited (`module.job_skipped`). It resolves when the
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

## Security review (M10 gate)

Reviewed 2026-11-20 by a fresh subagent with the M10 diff and threat table.

| Finding | Disposition |
|---|---|
| (high) On Windows a timed-out scanner could block forever (a grandchild held the output pipe), silently stopping scheduled scans | **Fixed** in the process broker: output goes to temporary files, the whole process tree is killed on timeout; skipped runs are audited |
| (high) gitleaks fatal errors (exit 1, no JSON) read as an all-clear and resolved findings | **Fixed.** No output is a failure for gitleaks and osv-scanner |
| (medium) Non-UTF-8 output crashed the scan and skipped other scanners | **Fixed.** Lenient decoding; any unexpected error is a failure finding and the loop continues |
| (medium) Output read whole into memory | **Fixed.** Broker caps captured output (`max_output`) |
| (medium) Findings over 2,000 dropped silently and resolved the rest | **Fixed.** Over the cap is a failure; nothing is resolved |
| (medium) semgrep messages can quote matched secrets | **Fixed.** Rule id only |
| (low) Removed scanners or targets stayed open forever | **Fixed.** Resolved at the next scan |
| (low) Deactivation during a scan raised in the worker | **Fixed** |
| (low) `run_now` could overlap a scheduled scan | **Fixed.** One scan at a time |
| (low) Repository text with control characters reached announcements | **Fixed.** Cleaned |

