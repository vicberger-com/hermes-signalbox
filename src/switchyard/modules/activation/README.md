# Activation (bundled module, M5)

Switches Hermes skills on and off with presets, shows what each skill costs in the system prompt, and makes
every change reversible. Q&A: [docs/qa/06-m5-prework.md](../../../../docs/qa/06-m5-prework.md); config writes:
[ADR-0005](../../../../docs/adr/0005-hermes-config-writes.md).

## Inventory and cost

`inventory` lists installed skills (from Hermes's `find_all_skills`), whether each is enabled, and its cost:
the estimated tokens (characters / 4) of its `- name: description` row in the `<available_skills>` index of the
system prompt. Totals for enabled and disabled skills are included.

## Presets

`preset_add {name, enable, disable, description}`: comma-separated entries, each a skill name,
`category:<name>` (includes sub-categories) or `*` (every skill). Applying a preset sets
`skills.disabled` = (currently disabled + `disable`) - `enable`.

- `benchmark {name}`: index tokens now and with the preset applied, and the reduction (no change is made).
- `apply {name, ttl_minutes}`: writes through `ctx.hermes_config` (backed up, audited, read back, rolled back
  on failure). With `ttl_minutes` the preset ends after that time; expiry is checked before each Hermes turn,
  on every health poll and before any new `apply`. Hermes keeps essential skills enabled; they are never
  written and are reported as `refused` (and never counted as saved in `benchmark`).
- `restore` (and expiry): undo exactly what the active preset(s) changed. Skills you switched by hand in the
  meantime keep your setting; a difference is audited as `module.activation.drift`.
- `undo {backup}`: restore the value before any single change (`history` lists backups).

Changes to skills take effect on the next turn. Only the global `skills.disabled` list is managed;
`inventory` shows platforms that also disable a skill (`disabled_on`) and counts installed skills whose names
cannot be handled (`not_listed`). Plugins are not switched (they need a restart, are code, and their list is a
deny-list); that needs its own capability.

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `inventory {category}`, `presets`, `benchmark {name}`, `history {n}` | yes |
| Action | `preset_add`, `preset_remove {name}`, `apply {name, ttl_minutes}`, `restore`, `undo {backup}` | no |
| Panel | `activation.status` | |

Capabilities: `hermes.config.write`, `hermes.hooks`, `ui.panel`.

## State and removal

Tables `presets`, `active`. Config backups belong to the core (`<data_dir>/hermes-config-backups`) and stay
after removal so changes remain reversible.

## Security review (M5 gate)

Reviewed 2026-11-20 by a fresh subagent with the M5 diff, the threat table and the Hermes v0.23.2 sources.

| Finding | Disposition |
|---|---|
| (medium) An expired timed preset was not ended before a new `apply` | **Fixed.** `apply` ends expired presets first |
| (medium) Backup pruning could delete the baseline an active preset needs | **Fixed.** The active row keeps the baseline and applied lists itself; no backup file needed |
| (medium) Ending a preset restored a whole old list, discarding edits made in between | **Fixed.** Only the preset's own changes are undone; drift audited |
| (medium) `plugins.disabled` writable by any holder of the capability (shortening it re-enables plugins) | **Fixed.** Removed from the writable keys |
| (low) Essential skills written and counted as saved | **Fixed.** Never written, reported as refused, excluded from savings |
| (low) Per-platform disables ignored | **Fixed (shown).** `disabled_on` in the inventory; only global scope is managed |
| (low) An odd existing name in Hermes's list blocked every apply | **Fixed.** Only added names are validated |
| (low) Skills with unusual names silently dropped | **Fixed.** Name rule relaxed to printable without commas; the rest are counted as `not_listed` |

