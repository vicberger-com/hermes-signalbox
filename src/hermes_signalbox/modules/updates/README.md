# Updates (bundled module, M12)

Checks git-installed modules against the head of their update channel on a schedule, and announces each newly
available commit once. It never applies anything. Q&A: [docs/qa/13-m12-prework.md](../../../../docs/qa/13-m12-prework.md);
design: [ADR-0011](../../../../docs/adr/0011-update-preview-and-channels.md).

## Updating a module (operator)

1. `hermes-signalbox module check_updates`: installed commit versus channel head for every git-installed module.
2. `hermes-signalbox module preview ext --ref <sha>`: files changed, permission changes (`widens`), patch notes
   and a `digest`. Nothing is applied.
3. `hermes-signalbox module update ext --ref <sha> --digest <digest>`: installs exactly the previewed files; add
   `--accept-wider` only if you accept the listed permission changes. A failed health check rolls back.
4. `hermes-signalbox module rollback ext` restores the previous version (the last 3 are kept); a previous version
   that may do more than the current one needs `--accept-wider`.

Updates containing compiled Python files (`__pycache__`, `.pyc`, `.pyo`) or `.pth` files are refused: they
would run without appearing in the reviewed source. Checks run at most one at a time, and modules with
`core.read` get a cached result (at most one fresh check a minute).

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `report` (last check) | yes |
| Action | `check_now` | no |
| Panel | `updates.status` | |
| Config | `[modules.updates] interval_hours` (24, 1-168) | |

Grant `schedule`, `core.read`, `ui.panel` (and `notify` for alerts), then activate (manual).

## Security review (M12 gate)

Reviewed 2026-11-20 by a fresh subagent with the M12 diff and threat table.

| Finding | Disposition |
|---|---|
| (high) Compiled `.pyc` files under `__pycache__` were outside the SBOM and digest but would be imported | **Fixed.** Updates with `__pycache__`, `.pyc`, `.pyo` or `.pth` files are refused |
| (medium) New hooks, commands or other contributions did not count as widening | **Fixed.** Added contributions and entry changes are in `widens` |
| (medium) `git ls-remote` ran in the current directory and could read that repository's config | **Fixed.** Empty working directory, `GIT_CEILING_DIRECTORIES` for every git call |
| (medium) Any `core.read` module could start unbounded network checks | **Fixed.** One check at a time, cached result, one fresh check a minute at most |
| (low) Whole files read into memory | **Fixed.** Chunked hashing, 50 MB per-file cap, notes read capped |
| (low) Manifest parsed before the symlink check | **Fixed** |
| (low) Rollback: no widening check, lost installed commit, mtime ordering, unbounded copies | **Fixed.** Widening needs `accept_wider`; commit restored; ordered by recorded time; 3 kept |
| (low) Patch notes matched version prefixes and kept bidi characters | **Fixed.** Exact heading; format characters removed |
| (low) Check errors could show local paths to the model | **Fixed.** Generic reason; detail in the audit log |

