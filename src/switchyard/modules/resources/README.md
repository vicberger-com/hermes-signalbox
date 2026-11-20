# Resources (M2)

A catalog of the models, endpoints, agents and tools Switchyard may use, grouped into pools and bound to
consumers. Later phases (router, metering, supervisor) read it through `resolve`.

| | |
|---|---|
| Id | `resources` |
| Phase | M2 |
| Isolation | in-process (bundled) |
| License class | open |

## Capabilities requested

| Capability | Why it is needed | What breaks without it |
|---|---|---|
| `fs.read` | Read the Hermes models.dev cache and operator catalog files | Imports fail; the registry still works |
| `ui.panel` | `resources.status` panel | No dashboard view |

No network access: Hermes keeps the models.dev registry fresh in its own home; this module reads that file.

## Model

- **Resource:** id `provider/model` (or any `[A-Za-z0-9][A-Za-z0-9._:/@+-]*`), kind (`model`, `endpoint`, `agent`,
  `tool`), state (`manual`, `auto`, `disabled`), cost class (`free`, `paid`, `self-hosted`), catalog tags plus
  user tags, limits (`context`, `output`), priority (lower is preferred), source.
- **Pool:** named group; each member has a pool priority.
- **Binding:** consumer (`main`, `subagent:<name>`, `function:<name>`, `agent:<name>`) -> pool.
- **resolve {consumer}:** the bound pool's resources that are not `disabled`, by pool priority, then resource
  priority, then id.

## Imports (reviewed diff)

`import_preview {source: "models.dev" | "file", path?, providers?, free_only?}` reads the source and stores a
pending diff (added, changed, removed; at most 5 pending). `import_apply {import_id}` applies it; it is a
human-only action. New resources arrive `disabled`. An import replaces only catalog fields (kind, provider,
name, cost class, catalog tags, limits); state, priority and user tags stay. Resources the source no longer
lists get the `stale` tag. From models.dev only names, limits, prices (as a cost class) and capability tags are
kept; API URLs and environment variable names are dropped.

Own catalog format: `{"resources": [{"id", "kind", "provider", "name", "cost_class", "tags", "limits"}]}`.

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `list {state, cost_class, tag, pool, provider, query, limit, offset}`, `show {id}`, `pools`, `resolve {consumer}`, `import_preview` | yes |
| Action | `set_state`, `set_priority`, `tag`, `untag`, `pool_create`, `pool_delete`, `pool_add`, `pool_remove`, `bind`, `unbind`, `import_apply`, `import_discard` | no |
| Panel | `resources.status` (counts, pending imports) | |
| Config | `[modules.resources]` `models_dev_cache` (default `<HERMES_HOME>/models_dev_cache.json`), `max_catalog_mb` (16) | |

## Data

Tables `m_resources__resources`, `__pools`, `__pool_members`, `__bindings`, `__imports`. No credentials.
Removal drops them unless `keep_data`.

## Security notes

Catalog input is untrusted: size-capped read (`ctx.fs`), field-by-field type checks, id and tag patterns, 20 000
rows per import, LIKE patterns escaped. Every change is audited as `module.resources.*`.

## Update and rollback

Bundled. Health reports counts.

## Third-party code

None. Catalog sources (models.dev MIT; awesome-free-llm-apis CC0; others MIT) are imported as data through the
reviewed path, never copied into the repository.
