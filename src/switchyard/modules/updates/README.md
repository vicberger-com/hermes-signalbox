# Updates (bundled module, M12)

Checks git-installed modules against the head of their update channel on a schedule, and announces each newly
available commit once. It never applies anything. Q&A: [docs/qa/13-m12-prework.md](../../../../docs/qa/13-m12-prework.md);
design: [ADR-0011](../../../../docs/adr/0011-update-preview-and-channels.md).

## Updating a module (operator)

1. `switchyard module check_updates`: installed commit versus channel head for every git-installed module.
2. `switchyard module preview --id ext --ref <sha>`: files changed, permission changes (`widens`), patch notes
   and a `digest`. Nothing is applied.
3. `switchyard module update --id ext --ref <sha> --digest <digest>`: installs exactly the previewed files; add
   `--accept-wider` only if you accept the listed permission changes. A failed health check rolls back.
4. `switchyard module rollback --id ext` restores the previous version.

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `report` (last check) | yes |
| Action | `check_now` | no |
| Panel | `updates.status` | |
| Config | `[modules.updates] interval_hours` (24, 1-168) | |

Grant `schedule`, `core.read`, `ui.panel` (and `notify` for alerts), then activate (manual).
