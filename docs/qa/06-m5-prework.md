# Pre-work Q&A: M5 skill and plugin activation manager

Date: 2026-11-20. Previous phase: M4, tag v0.5.0.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| M4 retro | Every optional capability needs a run-time check; allow-lists, not denylists | Config keys are an allow-list; each write is checked at the broker |
| M4 | Quota and paid stops are steering only | Not affected |
| ADR-0001 | No YAML parser in the standard library | Hermes's own config API does the reading and writing (question 10) |

## 2. Research record

| Topic | Source (Hermes v0.23.2, 2026-11-20) | Finding |
|---|---|---|
| Skill switches | `hermes_cli/skills_config.py`, `agent/skill_commands.py` 722 | `skills.disabled` (global) and `skills.platform_disabled.<platform>` in `config.yaml`; applied on every call, so a change takes effect on the next turn. Essential skills (`hermes-agent`) are silently dropped from the list |
| Prompt cost | `agent/prompt_builder.py` 1240-1365 | Each enabled skill adds one `- name: description` row to the `<available_skills>` index in the system prompt. Hermes already demotes some categories to names only in coding posture (internal, not configurable) |
| Plugin switches | `hermes_cli/plugins_cmd_toggle.py` | `plugins.disabled` / `plugins.enabled` keyed by canonical plugin key; take effect at restart |
| Public plugin API | `hermes_cli/data/plugin_api.json` | `hermes_cli.config` (`load_config`, `save_config(merge_existing=True)`) and `tools.skills_tool:find_all_skills` are published; private imports are flagged at admission |
| References | willingning-coder/eagle-eye, freehul/progressive-skill, jiangyuxue666/skill-auto-maintain, Kori-x/hermes-dashboard | Read for the preset and progressive-disclosure ideas; nothing copied |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Smallest scope? | | Skills: inventory with prompt cost, presets (names, `category:<c>`, `*`), benchmark, apply with optional time limit, restore, undo. The broker also allows `plugins.disabled` for later phases; the module does not switch plugins yet (restart needed, and plugins are code) | default accepted |
| 2 | Capabilities | | `hermes.config.write` (new broker), `hermes.hooks` (`pre_llm_call` to expire timed presets), `ui.panel`. `fs.read` not needed: the inventory comes from Hermes's API | default accepted |
| 3 | Reuse, adapt or write? | | Write | default accepted |
| 4 | New dependencies? | | None | default accepted |
| 5 | Security | | Threat table below | default accepted |
| 6 | State; uninstall | | Module tables `presets`, `active`. Config backups are core files under `<data_dir>/hermes-config-backups` (last 200), kept on module removal so changes stay reversible | default accepted |
| 7 | Control surface | | Read-only: `inventory {category}`, `presets`, `benchmark {name}`, `history {n}`. Human-only: `preset_add`, `preset_remove`, `apply {name, ttl_minutes}`, `restore`, `undo {backup}`. Panel `activation.status` | default accepted |
| 8 | Logs, metrics, alerts | | Audit `hermes.config.write` / `hermes.config.rollback` per change; `module.activation.*` for presets and expiry | default accepted |
| 9 | Update and rollback | | Bundled | default accepted |
| 10 | Core contract change? | (a) ADR-0005: `hermes.config.write` broker over a port the Hermes adapter implements with Hermes's public config API; (b) modules edit `config.yaml` themselves | (a). One audited, backed-up, verified path; no YAML handling in Switchyard; keys are an allow-list | default accepted |
| 11 | May the model apply presets? | (a) human-only; (b) presets flagged by the human | (a) for now. The model can see the inventory and benchmarks; switching skills changes what the model can do, so it stays a human action until M6 policies exist | default accepted |
| 12 | Progressive disclosure | (a) presets plus timed presets; (b) rewrite the skills index | (a). Hermes owns the index format (and already compacts categories in coding posture); rewriting it would couple to internals | default accepted |
| 13 | Operator input? | | None | default accepted |

### Threats and tests (question 5)

| Threat | Control | Test |
|---|---|---|
| A module writes arbitrary Hermes config (model, providers, keys) | Broker allow-list: `skills.disabled`, `plugins.disabled` only; values are validated name lists | `test_writer_backs_up_audits_verifies_and_rolls_back` |
| A failed or partial write leaves Hermes broken | Backup first, read back, restore the old value on error or unexpected content, audit the rollback | same |
| Change cannot be undone | Every write has a backup id; `undo` and `restore` re-apply it and are backed up themselves | `test_apply_restore_and_undo` |
| The model widens its own skills | Writes are human-only actions | `test_model_is_read_only_and_bad_inputs` |
| A timed preset never ends | Expiry checked before each Hermes turn and on every health poll | `test_ttl_restores_previous_state` |

## 4. Acceptance tests (written before code)

- [x] Measured prompt-size reduction on a fixed benchmark (`benchmark`; the test fixture shows > 40 % for a coding preset).
- [x] Every config write is backed up, audited and reversible.
- [x] A failed change rolls back.

## 5. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
