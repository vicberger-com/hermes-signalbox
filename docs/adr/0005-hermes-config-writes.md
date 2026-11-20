# ADR-0005: Hermes configuration writes

Status: accepted, 2026-11-20. Phase: M5. Q&A: [06-m5-prework.md](../qa/06-m5-prework.md) question 10.

## Context

The activation manager (M5) and later phases switch Hermes skills and plugins by editing Hermes's
`config.yaml`. Switchyard has no YAML parser (ADR-0001), the file holds settings far beyond skills, and a bad
write can break Hermes.

## Decision

1. **Port.** The core defines `HermesConfigPort` (`get(key)`, `set(key, value)`, `skills()`). The Hermes
   adapter implements it with Hermes's published plugin API: `hermes_cli.config.load_config` /
   `save_config(merge_existing=True)` and `tools.skills_tool.find_all_skills`. Without a port (tests, the
   standalone CLI) the capability is unavailable.
2. **Broker.** `ctx.hermes_config` needs `hermes.config.write`. Writable keys are an allow-list:
   `skills.disabled` only. `plugins.disabled` is excluded: it is a deny-list, and shortening it re-enables
   plugins the user turned off, so plugin switching needs its own human-approved capability (M5 review).
   `skills.platform_disabled` is readable. Values are lists of names; names the caller adds must be printable
   without commas, names already in Hermes's list are kept as they are. Essential skills (which Hermes ignores
   in the list) are never written and are reported as `refused`.
3. **Every write:** a backup file (old and new value, module, actor, time; names only) under
   `<data_dir>/hermes-config-backups` (last 200) is written first; the write is audited
   (`hermes.config.write`); the value is read back; if the write raised or Hermes stored a name that was not
   asked for, the old value is restored and `hermes.config.rollback` is audited. Names Hermes declines to store
   (essential skills) are reported as `refused`, not treated as failure.
4. **Reversal.** `revert(backup)` writes the backup's old value through the same path (so it has its own
   backup).

## Consequences

- Switchyard never parses or rewrites `config.yaml` itself and never touches keys outside the allow-list.
- Modules that undo their own changes (activation presets) undo exactly what they changed, not by restoring a
  whole old list, so edits made in between are kept (M5 review).
- A change is effective for skills on the next turn and for plugins at the next Hermes start.
