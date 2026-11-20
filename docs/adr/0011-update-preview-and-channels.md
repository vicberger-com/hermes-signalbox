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

5. Staged trees with symlinks, `__pycache__`, `.pyc`, `.pyo` or `.pth` files are refused; added contributions
   and entry changes count as widening; rollback is checked for widening too; 3 previous versions are kept.
6. git never discovers a repository above its working directory (`GIT_CEILING_DIRECTORIES`; `ls-remote` in an
   empty directory). Checks run one at a time; `core.read` callers get a cached result.

## Consequences

- The installed commit is restored on rollback from a sidecar written at update time.
