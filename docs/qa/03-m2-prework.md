# Pre-work Q&A: M2 resource registry and pools

Date: 2026-11-19. Previous phase: M1, tag v0.2.0.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| ADR-0002 | Module actions, `ctx.config`, `ctx.spawn`, `ctx.audit` | The registry's whole control surface is module actions; no core operation table growth |
| M1 review | Helpers are found with `find_program`; results are redacted as values | Same rules apply to any file or helper this module touches |
| M1 retro | `auto` modules wait for grants | The registry can be `auto` without failing on first start |
| M0 | No broker for `fs.read` exists (`ctx.fs` was declared only) | Needed to read catalog files (question 10) |

## 2. Research record

| Topic | Source (URL, commit or version, date read) | Finding |
|---|---|---|
| Hermes provider data | Hermes v0.23.2 `agent/models_dev.py`; `<HERMES_HOME>/models_dev_cache.json` (6.8 MB, 324 providers, read 2026-11-19) | Hermes already downloads models.dev (`https://models.dev/api.json`, ETag, 4 h TTL) to its home. Shape: `{provider: {id, name, api, env, doc, models: {id: {name, limit{context,output}, cost{input,output}, tool_call, reasoning, modalities, open_weights, ...}}}}`. Reading that file needs no network from Switchyard |
| Hermes plugin API | `hermes_cli/plugins_context.py` | No accessor for global provider config; plugins get their own settings only. `config.yaml` holds credentials next to provider settings, so Switchyard does not parse it |
| sst/models.dev | GitHub, MIT, pushed 2026-11-20 | Upstream of the cache above |
| mnfst/awesome-free-llm-apis | GitHub, CC0-1.0, 13.7k stars, pushed 2026-11-19 | README list plus `.verify/` reports; no stable machine-readable catalog |
| open-free-llm-api/awesome-freellm-apis | GitHub, MIT, pushed 2026-11-19 | `status.json` (machine-readable) |
| mvalentsev/awesome-free-ai-coding, ClawLabsAI/free-ai-models | GitHub, MIT, pushed 2026-11-19 | Lists and daily history snapshots; useful as reviewed imports, not as live feeds |
| Current practice for catalog trust | — | Pull is cheap; trust is not. Treat every source as untrusted input: preview a diff, apply only on a human action, never enable anything on import |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Smallest scope that meets acceptance? | (a) registry, pools, bindings, reviewed imports from the Hermes models.dev cache and from local JSON files; (b) also live network refresh | (a). The acceptance ("signed-source or reviewed-diff only") is met by preview-then-apply on local data, and Hermes already keeps models.dev fresh. Network refresh waits until a signed source exists | default accepted |
| 2 | Capabilities | `fs.read`, `net.outbound`, `ui.panel` | `fs.read` and `ui.panel`. Drop `net.outbound` for M2 (question 1) | default accepted |
| 3 | Reuse, adapt or write? | | Write our own. The catalog lists are data sources, imported through the reviewed path; nothing copied into the repository | default accepted |
| 4 | New dependencies? | | None | default accepted |
| 5 | Security | | See threat table | default accepted |
| 6 | State schema; uninstall | | Module tables: `resources` (id `provider/model`, kind, provider, name, state, cost_class, tags, limits, priority, source, updated_at), `pools`, `pool_members`, `bindings` (consumer -> pool), `imports` (pending previews). No credentials. Uninstall drops the tables unless `keep_data` | default accepted |
| 7 | Control surface | | Read-only actions: `list`, `show`, `pools`, `resolve {consumer}`, `import_preview`. Human-only actions: `set_state`, `set_priority`, `tag`, `pool_create`, `pool_delete`, `pool_add`, `pool_remove`, `bind`, `unbind`, `import_apply`, `import_discard`. Panel `resources.status`. The Hermes model reaches read-only actions through `switchyard_modules` action `run`; a dedicated `switchyard_resources` tool is deferred until modules can contribute Hermes tools (M5) | default accepted |
| 8 | Logs, metrics, alerts | | Log stream `resources`; audit `module.resources.*` for state changes, binds and applied imports | default accepted |
| 9 | Update and rollback | | Bundled. Health: tables readable | default accepted |
| 10 | Core contract change? | (a) `fs.read` broker: `ctx.fs.read_text(path, max_bytes)` and `ctx.fs.read_json`, absolute paths only, regular files only, size-capped, audited by path; (b) pass catalog data in through the adapter | (a). Small, reusable by M5 and M10, and matches the capability already in the vocabulary. Recorded as ADR-0003 | default accepted |
| 11 | Operator input? | | None | default accepted |

### Threats and tests (question 5)

| Threat | Control | Test |
|---|---|---|
| A catalog source enables or reprioritises resources silently | Imports produce a preview; `import_apply` is human-only; imported resources start `disabled`; existing state, priority and tags are never changed by an import | `test_import_never_enables`, `test_model_cannot_apply_import` |
| Hostile catalog file (huge, deep, wrong types, odd ids) | Size cap before parsing, type checks per field, id pattern, row cap per import | `test_hostile_catalog_rejected` |
| Model widens its own resources | Every state, pool and binding change is human-only (non-read-only action) | `test_model_actions_read_only` |
| `fs.read` reads arbitrary files | Requires the grant; absolute regular files only, no device files; size cap; every read audited by path | `test_fs_read_rules` |
| Credentials pulled in with provider data | Only listed fields are kept; `env` (variable names), `api` URLs and anything else are dropped | `test_import_keeps_only_known_fields` |

## 4. Acceptance tests (written before code)

Automated in `tests/modules/test_resources.py` and `tests/core/test_fsread.py`.

- [x] Import from the models.dev cache and from a JSON file, filter, prioritise, pool and bind resources; `resolve` returns the bound pool's enabled resources in priority order.
- [x] Catalog refresh is reviewed-diff only: preview shows added, changed and removed; nothing changes until a human applies it.
- [x] Nothing new is enabled without a user action: imported resources are `disabled`.

## 5. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
| A path parameter is harmless if the read needs a grant | The grant is module-wide; a model-supplied path turns a read-only action into arbitrary file reads. Model-runnable actions take no paths | Every module with file inputs |
| `Path.is_absolute()` means "local file" | On Windows UNC paths are absolute and resolving them contacts the remote host (NTLM). Paths are checked syntactically before any I/O | `ctx.fs`, any path handling on Windows |
| A depth check after `json.loads` bounds cost | Parsing already built the structure; screen the text first | Any JSON input |
| A catalog cap can exceed the state store's row cap | Module limits must stay at or below the store's 10 000-row query cap, or page | Every module that stores catalogs |
| An import preview is a pure read | It stores a pending row; one per source prevents slot exhaustion and stale applies | Any preview/apply flow |

