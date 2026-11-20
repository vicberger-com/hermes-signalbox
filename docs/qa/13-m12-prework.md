# Pre-work Q&A: M12 update and release control for modules

Date: 2026-11-20. Previous phase: M11, tag v0.12.0.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| M0 | Core already updates git-installed modules: pinned https URL, exact commit, verify, stage, swap, health check, automatic rollback, manual rollback | M12 builds on it; no second updater |
| M11 | `net_hosts` widen silently with an existing `net.outbound` grant | An update that widens declared permissions needs explicit acceptance |
| M10 | External programs: bounded, scrubbed environment | `git ls-remote` uses the same scrubbed `git` runner |

## 2. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Smallest scope? | | Core: preview (SBOM delta, patch notes, tree digest), digest pinning, widening gate, channels and checks; bundled `updates` module for scheduled checks | default accepted |
| 2 | Capabilities | | Updates stay in the core (T0). Module: `schedule`, `core.read`, `notify` (optional), `ui.panel`. MODULES.md listed `net.outbound` and `fs.write`; not needed because the core performs fetches | default accepted |
| 3 | What is a channel? | (a) a branch whose head is compared; (b) signed release feed | (a). Manifest `[update] channel` (default `main`). Checks only report; the operator previews and applies a specific commit | default accepted |
| 4 | Automatic apply? | (a) never; (b) opt-in | (a). Applying runs new code; it stays an operator command | default accepted |
| 5 | SBOM format | (a) file list with SHA-256 plus declared permissions; (b) CycloneDX | (a), stdlib only. Stored as `staging/<id>/sbom-<ref>.json`, returned by preview and update | default accepted |
| 6 | Tamper protection | | Commit SHA pinning (existing), plus `digest` from preview: update refuses different files | default accepted |
| 7 | Widening | | New capabilities, hosts or secrets, in-process isolation, or a license-class change need `accept_wider` | default accepted |
| 8 | Patch notes | | `## [version]` section of the staged CHANGELOG.md, control characters removed, 4,000 characters; shown to the operator only | default accepted |
| 9 | Model access | | None: preview, update, rollback and check_updates are not model tool actions; module `check_now` is human-only, `report` read-only | default accepted |
| 10 | Core contract change? | | ADR-0011: manifest `[update] channel`; `CoreView.update_checks()` | default accepted |

### Threats and tests

| Threat | Control | Test |
|---|---|---|
| Files change between review and install | `digest` pinning | `test_tampered_update_rejected` |
| Update gains permissions silently | `widens` + `accept_wider` | `test_widening_needs_explicit_acceptance` |
| Broken update stays installed | Health check and automatic rollback (now with delta) | `test_failed_health_check_rolls_back_with_delta` |
| Channel name used for option injection | Pattern, `--` before the URL, `refs/heads/` prefix | `test_git_latest_reads_channel_head` |
| Patch notes carry terminal escapes | Control characters removed | `test_preview_reports_delta_and_notes_without_applying` |
| Model triggers checks or updates | Human-only | `test_rights_and_settings` |

## 3. Acceptance tests (written before code)

- [x] Tampered update rejected.
- [x] Failed health check rolls back.
- [x] SBOM delta produced for each update.

## 4. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
| Hashing the source files covers what runs | Python also imports `.pyc` and `.pth` files; refuse what cannot be reviewed | Any code install path |
| Permission names are the whole permission surface | Contributions (hooks, commands) gain power under existing grants | Widening checks |
| Scrubbing global git config isolates git | git still reads the repository above its working directory | Every git call |

