# Blockers

Items that match a stop condition in `AGENTS.md`. Each names the manual action needed.

## B-H1-1 (2026-11-20): tag protection and the release environment need the repository owner — OPEN

Stop condition: a GitHub setting only the owner can change. The repository token gets HTTP 403 for creating a
ruleset and an environment. Everything else in WP3 is done: the release workflow refuses a tag that is not an
annotated tag on `main` matching the project version, and re-runs the full gate before publishing.

Operator action:

1. github.com/vicberger-com/hermes-switchyard/settings/rules: New ruleset, **New tag ruleset**: name
   `Release tags`, enforcement Active, target pattern `v*`, rules **Restrict updates**, **Restrict deletions**,
   **Block force pushes**; no bypass.
2. github.com/vicberger-com/hermes-switchyard/settings/environments: `release` (created by the first release
   run, or New environment), Deployment branches and tags: **Selected branches and tags**, add tag rule
   `v*.*.*`. Optional: **Required reviewers** (yourself), which makes every release wait for your approval.

Not blocking the v1.0.1 tag: the workflow gate is the main control; these settings stop a tag from being moved
afterwards and limit which refs can deploy.

## B-R1-1 (2026-11-20): repository security settings needed before the v1.0.0 tag — RESOLVED 2026-11-20

Stop condition: a GitHub setting only the owner can change. Checked with the repository token on 2026-11-20:
private vulnerability reporting is **off** (`SECURITY.md` tells reporters to use it), Dependabot alerts are
**off**, and secret scanning and code scanning alerts cannot be read by the token (403), so the release gate
"no open alerts" cannot be confirmed.

Operator action (github.com/vicberger-com/hermes-switchyard/settings/security_analysis):

1. Enable **Private vulnerability reporting**.
2. Enable **Dependabot alerts** (and security updates if wanted).
3. Enable **Secret scanning** and **Push protection**.
4. Optional: grant the repository token read access to "Code scanning alerts" and "Secret scanning alerts", or
   confirm in the Security tab that there are no open alerts.

All other R1 work continues; only the v1.0.0 tag waits for this.

Resolution (checked with the repository token, 2026-11-20): private vulnerability reporting, Dependabot alerts
and security updates, secret scanning, push protection and validity checks are enabled. Open alerts: Dependabot
0, secret scanning 0, code scanning 7, all OpenSSF Scorecard posture checks, dispositioned in
`docs/qa/14-r1-prework.md` section 4. The token gained read access to alerts and administration.

