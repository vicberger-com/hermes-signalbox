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

`import_preview {providers?, free_only?}` reads the configured models.dev cache (no path). It is
operator-only: it replaces the pending import, so it is not read-only and the model may not run it (H1 C-11); `import_file {path}` reads an operator-chosen catalog file and is human-only. Both store a pending
diff (added, changed, removed) and return counts and sample ids only. One pending import per source (a new
preview replaces the old one), at most 5 sources pending. `import_apply {import_id}` (human-only) applies it.
New resources arrive `disabled`. An import replaces only catalog fields (kind, provider, name, cost class,
catalog tags, limits); state, priority and user tags stay. Resources the source no longer lists get the
catalog tag `stale`, which clears when the source lists them again. File sources are labelled
`file:<hash of resolved path>:<name>`. From models.dev only names, limits, prices (as a cost class) and capability tags are
kept; API URLs and environment variable names are dropped.

Own catalog format: `{"resources": [{"id", "kind", "provider", "name", "cost_class", "tags", "limits"}]}`.

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `list {state, cost_class, tag, pool, provider, query, limit, offset}`, `show {id}`, `pools`, `resolve {consumer}` (first 1000) | yes |
| Action | `import_preview {providers, free_only}`, `set_state`, `set_priority`, `tag`, `untag`, `pool_create`, `pool_delete`, `pool_add`, `pool_remove`, `bind`, `unbind`, `import_file {path}`, `import_apply`, `import_discard` | no |
| Panel | `resources.status` (counts, pending imports) | |
| Config | `[modules.resources]` `models_dev_cache` (default `<HERMES_HOME>/models_dev_cache.json`), `max_catalog_mb` (16) | |

## Data

Tables `m_resources__resources`, `__pools`, `__pool_members`, `__bindings`, `__imports`. No credentials.
Removal drops them unless `keep_data`.

## Security notes

Catalog input is untrusted: size-capped read (`ctx.fs`), field-by-field type checks, id and tag patterns, 10 000
rows per import, 32 tags per resource, LIKE patterns escaped. Every change is audited as `module.resources.*`.

## Update and rollback

Bundled. Health reports counts.

## Third-party code

None. Catalog sources (models.dev MIT; awesome-free-llm-apis CC0; others MIT) are imported as data through the
reviewed path, never copied into the repository.

## Security review (M2 gate)

Reviewed 2026-11-19 by a fresh subagent with only the M2 diff and the threat table; every finding was checked
against the code.

| Finding | Disposition |
|---|---|
| (high) On Windows a UNC path was resolved (SMB connection, NTLM hash sent) before the grant check, reachable by the model through `import_preview`'s path | **Fixed.** `ctx.fs` accepts only drive-letter paths on Windows (no UNC, `\\.\`, `\\?\`, device names) and checks the grant before any file-system call |
| (high) The model chose the path and saw content (names) from any readable JSON file | **Fixed.** `import_preview` takes no path (configured cache only); `import_file {path}` is human-only; previews return counts and ids only |
| (medium) Source labels did not identify the file, so a foreign file could rewrite models.dev rows | **Fixed.** models.dev means the configured cache only; files are labelled by a hash of the resolved path |
| (medium) Catalogs up to 20 000 rows broke the next preview and big pools broke `resolve` (state store caps queries at 10 000 rows) | **Fixed.** 10 000 rows per catalog, paged reads of existing rows, `resolve` returns the first 1000 |
| (medium) Unbounded tags per row inflated stored diffs and responses | **Fixed.** 32 tags per resource; previews return ids only |
| (medium) JSON depth was checked after parsing, so a wide 16 MB file cost ~640 MiB | **Fixed.** Depth and value count are screened on the text before parsing |
| (low) `stale` was written to user tags | **Fixed.** Catalog tag; clears when listed again |
| (low) The model could fill all pending slots; older previews could be applied over newer ones | **Fixed.** One pending import per source |
| (low) Tag filter treated `_` as a wildcard | **Fixed.** Escaped |
| (low) stat-then-open race; a FIFO could block the host | **Fixed.** Open (non-blocking on POSIX), then `fstat` the handle |
| (low) Failed reads left no audit record | **Fixed.** `fs.read_failed` with path and reason |
| (low) Ruff S608 ignore covered every future module file | **Fixed.** Scoped to the two module files |

