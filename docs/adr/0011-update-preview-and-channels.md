# ADR-0011: Update preview, SBOM delta and channels

Status: accepted, 2026-11-20. Phase: M12. Q&A: [13-m12-prework.md](../qa/13-m12-prework.md).

## Decision

1. `module preview {id, ref}` stages and verifies a commit without applying it and returns the SBOM delta (files
   added, removed and changed by SHA-256; declared-permission differences; `widens`), the version's patch notes
   and the staged tree `digest`.
2. `module update {id, ref, digest?, accept_wider?}`: with `digest`, different files are refused. If `widens` is
   not empty (new capabilities, hosts or secrets; in-process isolation; license-class change), the update is
   refused unless `accept_wider`. The delta is stored as `staging/<id>/sbom-<ref>.json` and returned.
3. Manifest `[update] channel` (default `main`) names the branch compared by `module check_updates`
   (`git ls-remote`, nothing downloaded). The installed commit is recorded in `staging/<id>/installed-ref`.
4. `CoreView.update_checks()` exposes the comparison to `core.read` modules; the bundled `updates` module runs
   it on a schedule and announces each new commit once. Nothing is applied automatically.

## Consequences

- Rollback forgets the recorded installed commit and falls back to the manifest's `ref`, so a check after
  rollback may report the pre-update pin.
