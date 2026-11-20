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
  on failure). With `ttl_minutes` the state before the first active preset comes back after that time; expiry
  is checked before each Hermes turn and on every health poll. Hermes keeps essential skills enabled; those
  are reported as `refused`.
- `restore`: back to the state before the first active preset.
- `undo {backup}`: restore the value before any single change (`history` lists backups).

Changes to skills take effect on the next turn. Plugins are not switched by this module (they need a restart
and are code); the broker already allows `plugins.disabled` for later phases.

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
