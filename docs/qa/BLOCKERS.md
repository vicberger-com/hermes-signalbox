# Blockers

Items that match a stop condition in `AGENTS.md`. Each names the manual action needed.

## B-R1-1 (2026-11-20): repository security settings needed before the v1.0.0 tag — OPEN

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

