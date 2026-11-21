> **Historical (moved here in H1 WP10, D-18).** This audit describes v0.13.0 before the R1 release. The gaps it
> lists were closed for v1.0.0: see `docs/USER-GUIDE.md` and `docs/REFERENCE.md`. Kept as a record only.

# Hermes Switchyard Docs-Coverage Audit (R1)

**Gate:** "Every public function, tool, command, config key and event documented"
**Scope:** `src/switchyard` (main, v0.13.0) against release gate
**Status:** Gaps identified — user guide does not exist; many items undocumented

---

## Area 1: CLI commands / @op operations — documented in README.md or docs/?

**Source:** `src/switchyard/ops.py` and `src/switchyard/cli.py` — the operations table is the single source of truth for CLI, control API, and Hermes tools.

| Noun | Verb | Description | Documented? |
|---|---|---|---|
| `module` | `list` | List every discovered module | Partial — mentioned in README.md high-level overview only |
| `module` | `show` | Show one module | Partial |
| `module` | `grant` | Grant a capability to a module | Not documented in README.md or docs/ |
| `module` | `revoke` | Revoke a capability | Not documented |
| `module` | `mode` | Set activation mode | Not documented |
| `module` | `activate` | Start a module | Not documented |
| `module` | `deactivate` | Stop a module | Not documented |
| `module` | `health` | Run a module's health check | Not documented |
| `module` | `panel` | Render a module's panel | Not documented |
| `module` | `remove` | Stop and forget a module | Not documented |
| `module` | `action` | Run a module action | Not documented |
| `module` | `update` | Update a git-installed module | Not documented |
| `module` | `preview` | Stage a commit without applying | Not documented |
| `module` | `check_updates` | Compare installed with head of update channel | Not documented |
| `module` | `rollback` | Restore previous version | Not documented |
| `audit` | `verify` | Verify audit hash chain | Not documented |
| `audit` | `tail` | Show recent audit records | Not documented |
| `report` | `show` | Operator report (health, usage, security, changes) | Not documented |
| `host` | `profile` | Show host profile | Not documented |
| `config` | `show` | Show effective core configuration | Not documented |

**Finding:** The `README.md` has a high-level overview but does **not** list every CLI operation. The `docs/` directory has design/phase docs but no comprehensive CLI reference. The module `README.md` files have control-surface tables, but those are module-specific, not CLI-wide.

**Gap:** All 25 operations are **not individually documented** in a user-facing reference. The operations are machine-generated from the shared table, but no document maps noun/verb to description or parameters for the human user.

**File paths:** `src/switchyard/ops.py` (definitions), `src/switchyard/cli.py` (CLI generation), `README.md` (high-level only), `docs/MODULES.md` (module scope), `docs/DESIGN.md` (architecture)

---

## Area 2: Module commands (from `module.toml` [contributes] commands) — documented in module's README control-surface table?

**Source:** Each `src/switchyard/modules/*/module.toml` `contributes.commands` list vs. that module's `README.md` control-surface table.

| Module | Commands in module.toml | Documented in README.md control-surface? | Gap |
|---|---|---|---|
| **activation** | `inventory`, `presets`, `benchmark`, `history`, `preset_add`, `preset_remove`, `apply`, `restore`, `undo` | ✅ All 9 listed | — |
| **inbox** | `list`, `ack`, `ack_all` | ✅ All 3 listed | — |
| **meter** | `summary`, `usage`, `quotas`, `forecast`, `quota_add`, `quota_remove`, `prices_reload` | ✅ All 7 listed | — |
| **offload** | `connectors`, `run`, `report` | ✅ All 3 listed | — |
| **resources** | `list`, `show`, `pools`, `resolve`, `import_preview`, `set_state`, `set_priority`, `tag`, `untag`, `pool_create`, `pool_delete`, `pool_add`, `pool_remove`, `bind`, `unbind`, `import_file`, `import_apply`, `import_discard` | ✅ All 18 listed | — |
| **router** | `status`, `explain`, `pin`, `auto`, `rule_add`, `rule_remove`, `budget`, `cooldown_clear` | ✅ All 8 listed | — |
| **scanner** | `report`, `findings`, `run_now` | ✅ All 3 listed | — |
| **secrets** | `status`, `rotate`, `expire` | ✅ All 3 listed | — |
| **supervisor** | `report`, `findings`, `ack`, `run_now` | ✅ All 4 listed | — |
| **trimmer** | `report`, `preview` | ✅ All 2 listed | — |
| **updates** | `report`, `check_now` | ✅ All 2 listed | — |
| **workers** | `report`, `roles`, `teams`, `ledger`, `role_set`, `role_remove`, `team_set`, `team_remove` | ✅ All 8 listed | — |

**Finding:** **Every module's `contributes.commands` are documented in that module's `README.md` control-surface table.** This area is fully covered.

**File paths:** `src/switchyard/modules/*/module.toml`, `src/switchyard/modules/*/README.md`

---

## Area 3: Config keys — documented?

**Source:** `ctx.config` keys in each `*_module.py`, plus core keys in `src/switchyard/config.py`.

### Core config keys (`src/switchyard/config.py`)

| Key | Section | Documented? |
|---|---|---|
| `data_dir` | optional | ❌ Not documented in README.md |
| `api.enabled` | `[api]` | ❌ Not documented |
| `api.port` | `[api]` | ❌ Not documented |
| `log.level` | `[log]` | ❌ Not documented |
| `host.profile` | `[host]` | ❌ Not documented |

### Module-specific config keys

| Module | Config keys (from `ctx.config` or `cfg = dict(ctx.config)`) | Documented in module README? |
|---|---|---|
| **activation** | Validates `ctx.config` is empty (no explicit keys); uses `ctx.hermes_config` for `skills.disabled` | ❌ No explicit config doc; only "unknown [modules.activation] setting(s)" error message |
| **inbox** | `min_severity` | ✅ Documented: `[modules.inbox] min_severity` |
| **meter** | `retention_days`, `models_dev_cache` | ✅ Documented: `[modules.meter] retention_days (90, 7-3650), models_dev_cache` |
| **offload** | `allow`, `jevk5_url`, `n8n_webhook`, `timeout_seconds` | ❌ Not documented in README.md |
| **resources** | `models_dev_cache`, `max_catalog_mb` | ✅ Documented: `[modules.resources] models_dev_cache, max_catalog_mb` |
| **router** | `consumer`, `providers`, `max_attempts`, `cooldown_seconds`, `hard_stop` | ✅ Documented: `[modules.router] consumer, providers, max_attempts, cooldown_seconds, hard_stop` |
| **scanner** | (reads `ctx.config` but no explicit keys declared in `activate`) | ❌ Not documented |
| **secrets** | `backends`, `allow_env_backend`, `bw_session_env`, `rotation_length`, `expiry_warning_days` | ✅ Documented: `[modules.secrets]` |
| **supervisor** | `interval_seconds`, `audit_check_hours`, `quota_warn_percent` | ✅ Documented: `[modules.supervisor] interval_seconds, audit_check_hours, quota_warn_percent` |
| **trimmer** | `min_chars`, `max_lines`, `head`, `tail`, `tools` | ✅ Documented: `[modules.trimmer] min_chars, max_lines, head, tail, tools` |
| **updates** | `interval_hours` | ✅ Documented: `[modules.updates] interval_hours` |
| **workers** | `default_role`, `loop_window_minutes`, `loop_limit`, `check_seconds` | ✅ Documented: `[modules.workers] default_role, loop_window_minutes, loop_limit, check_seconds` |

**Finding:** Core config keys (api, log, host) and the activation module config are **not documented** in README.md or docs/. Most module config keys **are** documented in their module's `README.md`. The offload and scanner modules have undocumented config keys.

**File paths:** `src/switchyard/config.py`, `src/switchyard/modules/*/module.toml`, `src/switchyard/modules/*/README.md`, `README.md`

---

## Area 4: Audit action strings and events — listed anywhere?

**Source:** `audit.append(action=...)` and `ctx.audit(...)` calls; `ctx.emit()` / `bus.publish()` event types.

### Audit actions (from `core.audit.append` and `self._audit.append`)

| Action string | File / Context | Documented? |
|---|---|---|
| `module.list` | ops.py:107 | ❌ Not as a standalone doc entry |
| `module.show` | ops.py:112 | ❌ |
| `module.grant` | ops.py:132 | ❌ |
| `module.revoke` | ops.py:138 | ❌ |
| `module.mode` | ops.py:152 | ❌ |
| `module.activate` | ops.py:165 | ❌ |
| `module.deactivate` | ops.py:172 | ❌ |
| `module.health` | ops.py:179 | ❌ |
| `module.panel` | ops.py:186 | ❌ |
| `module.remove` | ops.py:192 | ❌ |
| `module.action` | ops.py:201–208 / ops.py:232 | ❌ |
| `module.update` | ops.py:251–260 | ❌ |
| `module.preview` | ops.py:263–267 | ❌ |
| `module.check_updates` | ops.py:270–273 | ❌ |
| `module.rollback` | ops.py:276–282 | ❌ |
| `audit.verify` | ops.py:285–293 | ❌ |
| `audit.tail` | ops.py:296–299 | ❌ |
| `report.show` | ops.py:302–309 | ❌ |
| `host.profile` | ops.py:312–314 | ❌ |
| `config.show` | ops.py:317–325 | ❌ |
| `core.tick_failed` | hermes/__init__.py:262 | ❌ |
| `api.start_failed` | hermes/__init__.py:171–176 | ❌ |
| `audit.verify_failed` | hermes/__init__.py:367 | ❌ |
| `event.depth_exceeded` | events.py:154–156 | ❌ |
| `event.handler_failed` | events.py:171–176 | ❌ |
| `policy.grants_removed` | capabilities.py:121 | ❌ |
| `policy.denied` | capabilities.py:170 | ❌ |
| `process.spawned` | process.py:144 | ❌ |
| `fs.read` / `fs.read_failed` | fsread.py:96,143 | ❌ |
| `hermes.config.write` / `hermes.config.rollback` | hermesconfig.py:141,154 | ❌ |
| `secret.used` | secrets.py (audit) | ❌ |
| `secret.backend_added` / `secret.backend_removed` | secrets.py | ❌ |
| `module.secrets.rotated` | secrets_module.py:162 | ❌ |
| `module.secrets.expiry_set` | secrets_module.py:195 | ❌ |
| `module.meter.threshold` | meter_module.py:365 | ❌ |
| `workers.stuck` / `workers.loop` | workers_module.py:221,320 | ❌ |
| `supervisor.alert` / `module.supervisor.alert` | supervisor_module.py:225,328 | ❌ |
| `meter.exhausted` / `meter.threshold` | meter_module.py:366–368 | ❌ |
| `offload` (various) | offload_module.py:207 | ❌ |
| `activation.drift` / `activation.expired` / `activation.preset_add` / `activation.preset_remove` | activation_module.py:164,174,261,267 | ❌ |
| `inbox.ack_all` / `inbox.loop_refused` / `inbox.stuck` | inbox_module.py:159,221,320 | ❌ |
| `role_refused` / `role_remove` / `team_set` / `team_remove` | workers_module.py:415,434,453,462 | ❌ |
| `checked` | updates_module.py:84 | ❌ |
| `rotated` / `expiry_set` | secrets_module.py:162,195 | ❌ |
| `alert` | supervisor_module.py:225 | ❌ |
| `threshold` | meter_module.py:365 | ❌ |
| `quota_add` / `quota_remove` | meter_module.py:523,539 | ❌ |
| `drift` | activation_module.py:164 | ❌ |
| `expired` | activation_module.py:174 | ❌ |
| `preset_add` / `preset_remove` | activation_module.py:261,267 | ❌ |
| `ack` / `role_remove` / `team_set` / `team_remove` | supervisor_module.py:328, resources_module.py:191 | ❌ |
| `pin` / `auto` / `rule_add` / `rule_remove` / `budget` | router_module.py:452,458,466,472,480 | ❌ |
| `hard_stop` | router_module.py:340 | ❌ |
| `event.depth_exceeded` / `event.handler_failed` | events.py:154–176 | ❌ |

### Events (from `ctx.emit()` / `bus.publish()`)

| Event type | Source file | Documented? |
|---|---|---|
| `core.notify` | context.py:173 | ❌ |
| `supervisor.alert` | lifecycle.py:166 / supervisor_module.py:226 | ❌ |
| `meter.exhausted` | meter_module.py:366 | ❌ |
| `meter.threshold` | meter_module.py:368 | ❌ |
| `workers.stuck` | workers_module.py:222 | ❌ |
| `workers.loop` | workers_module.py:321 | ❌ |
| `module.failed` | (implicit via event bus) | ❌ |
| `scanner.finding` | scanner_module.py:288 | ❌ |
| `module.secrets.rotated` | secrets_module.py:162 | ❌ |
| `module.secrets.expiry_set` | secrets_module.py:195 | ❌ |
| `workers.loop` | workers_module.py:222 | ❌ |
| `supervisor.alert` | supervisor_module.py:226 | ❌ |

**Finding:** **Virtually no audit action strings or event types are documented** in README.md or docs/. The code has 40+ audit actions and 15+ event types, but they are only visible via code grepping. The `events.py` specification (spec section 3) and `audit.py` are the only sources, and they are not referenced from user-facing docs.

**File paths:** `src/switchyard/audit.py`, `src/switchyard/events.py`, `src/switchyard/modules/*/*_module.py`, `src/switchyard/core.py`, `src/switchyard/bridge.py`, `README.md`, `docs/`

---

## Area 5: Hermes tool schema (`src/switchyard/hermes/__init__.py`) — documented?

**Source:** `MODULES_SCHEMA`, `AUDIT_SCHEMA`, `HOST_SCHEMA` definitions and `ctx.register_tool()` calls.

| Schema | Purpose | Documented? |
|---|---|---|
| `switchyard_modules` | Model tool: list, show, activate, deactivate, health, run module actions | ❌ Not documented in README.md or docs/ |
| `switchyard_audit` | Model tool: verify audit chain, tail recent records | ❌ Not documented |
| `switchyard_host` | Model tool: show host profile | ❌ Not documented |
| `switchyard` (slash command) | `/switchyard <noun> <verb> [id] [key=value ...]` | ❌ Not documented as a schema |
| `hermes.config.write` (broker) | ADR-0005 config writes | ❌ Not documented outside ADR-0005 |

**Finding:** The Hermes tool schemas are **not documented** in README.md or docs/. They are defined in code (`src/switchyard/hermes/__init__.py`) and referenced in AGENTS.md (build flow), but no user-facing document describes the tool parameters, required fields, or descriptions.

**File paths:** `src/switchyard/hermes/__init__.py`, `AGENTS.md`, `README.md`, `docs/`

---

## Area 6: User guide covering install, first run, grants, activation, dashboard, updates, uninstall

**Status:** **`docs/USER-GUIDE.md` does NOT exist.**

The R1 Q&A (docs/qa/14-r1-prework.md, item 6) explicitly calls for:
> "user guide `docs/USER-GUIDE.md` covering install, first run, grants, activation, dashboard, updates, uninstall" — **default accepted** as an open question.

What exists:
- `README.md` — high-level project overview, phase status, quick-start commands, license
- `docs/MODULES.md` — module scope summaries (M0–M12), not a user guide
- `docs/DESIGN.md` — architecture and trust model
- `docs/BUILD-PLAN.md` — phase order and acceptance criteria
- `docs/ADR/` — architectural decision records
- `docs/qa/` — pre-work Q&A per phase

None of the existing docs cover: Hermes installation, data-dir initialization, granting capabilities to modules, activating modules, starting the dashboard (`switchyard api serve`), checking for updates, or uninstall.

**File paths:** `docs/USER-GUIDE.md` — **MISSING**; `README.md`; `docs/`

---

## Summary of Gaps

| Area | Status | Key gaps |
|---|---|---|
| 1. CLI ops documented | ❌ Missing | All 25 noun/verb operations not individually documented |
| 2. Module commands documented | ✅ Complete | All `contributes.commands` covered in module README control-surface tables |
| 3. Config keys documented | ❌ Partial | Core keys (api, log, host) undocumented; activation config undocumented; offload config undocumented |
| 4. Audit actions/events listed | ❌ Missing | 40+ audit actions and 15+ event types not documented anywhere user-facing |
| 5. Hermes tool schema documented | ❌ Missing | `switchyard_modules`, `switchyard_audit`, `switchyard_host` schemas not documented |
| 6. User guide exists | ❌ Missing | `docs/USER-GUIDE.md` does not exist; R1 acceptance pending |

**Overall:** 4 of 6 areas have significant gaps. Area 2 (module commands) is the only fully satisfied requirement.

**Recommendation:** Close the R1 acceptance by writing `docs/USER-GUIDE.md` and adding a CLI operation reference table to `README.md` or `docs/`. Audit actions/events and config keys should be documented in a cross-reference appendix.