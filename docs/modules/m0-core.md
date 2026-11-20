# M0 core: specification

Status: frozen for M0, 2026-11-19. Inputs: [DESIGN.md](../DESIGN.md), [ADR-0001](../adr/0001-m0-core-stack.md),
[01-m0-prework.md](../qa/01-m0-prework.md). Changes after freeze need a Q&A retro entry; changes to the module
contract need an ADR.

## 1. Package layout

```
src/switchyard/
  __init__.py        version, public re-exports
  errors.py          SwitchyardError, ManifestError, CapabilityDenied, AuditError, StateError, UpdateError
  paths.py           data-directory resolution
  config.py          CoreConfig (TOML, tomllib), defaults, env override SWITCHYARD_DATA_DIR
  manifest.py        load + validate module.toml -> Manifest (frozen dataclass)
  capabilities.py    capability ids, Grant, PolicyEngine
  context.py         ModuleContext and the per-capability broker facades
  state.py           StateStore (SQLite WAL, migrations, module table namespace)
  audit.py           AuditLog (hash-chained JSON Lines), verify()
  events.py          EventBus (typed, in-process, synchronous with error isolation)
  scheduler.py       Trigger, Scheduler (time / event / usage / capacity)
  lifecycle.py       ModuleManager (discover -> verify -> grant -> load -> active <-> idle -> stopped)
  host_t2.py         Subprocess host: parent side; host_t2_child.py child side; rpc.py framing
  secrets.py         SecretRef, SecretBackend protocol, SecretsBroker, MemoryBackend (tests only)
  hostinfo.py        HostProfile, profile() -> tiny | laptop | workstation | server
  updates.py         UpdateController (fetch, verify, stage, swap, health, rollback)
  api.py             Loopback control API server and bounded client
  cli.py             `switchyard` entry point (argparse)
  core.py            Core: wires all of the above; the only object adapters hold
  hermes/__init__.py Hermes adapter: register(ctx)
```

Root `plugin.yaml` + `__init__.py` (thin re-export of `switchyard.hermes.register`) for `hermes plugins install`;
entry point `[project.entry-points."hermes_agent.plugins"] switchyard = "switchyard.hermes"` for pip installs.
CLI entry point `[project.scripts] switchyard = "switchyard.cli:main"`.

## 2. Data directory

Resolution order: `SWITCHYARD_DATA_DIR` env, `CoreConfig.data_dir`, then inside Hermes `ctx.state.data_dir`, else
platform default: Windows `%LOCALAPPDATA%\switchyard`, macOS `~/Library/Application Support/switchyard`, other
`$XDG_DATA_HOME/switchyard` or `~/.local/share/switchyard`. Created with mode 0700 where POSIX applies.

```
<data_dir>/config.toml   state.db   audit/audit-<n>.jsonl   logs/<stream>.jsonl
          api.token (0600)   staging/<module>/<sha>/   modules/<module>/   backup/
```

## 3. Interfaces

### Manifest

`load_manifest(path) -> Manifest`. Same rules as `tools/validate_manifest.py` (which becomes a thin CLI over
`switchyard.manifest`). Additional core checks: `entry` is `module:Class` with identifier parts only; the resolved
module file is inside the module directory; `isolation = "in-process"` is allowed only for modules whose
directory is inside the package's `modules/` root or a test-registered trusted root.

### Policy

```python
class PolicyEngine:
    def grant(self, module_id: str, capability: str, *, actor: str) -> None      # audited
    def revoke(self, module_id: str, capability: str, *, actor: str) -> None     # audited
    def granted(self, module_id: str) -> frozenset[str]
    def require(self, module_id: str, capability: str, **detail: str) -> None    # raises CapabilityDenied; denial audited
    def require_host(self, module_id: str, host: str) -> None                    # net.outbound + net_hosts allow-list
    def require_secret(self, module_id: str, name: str) -> None                  # secrets.read + secrets allow-list
```

A grant is effective only if the capability is also in the manifest's `request` list; `contributes.policies` can
only remove. M0 policy grammar: `deny:<capability>`; any other rule is a manifest error. Grants persist through a
`GrantStore` (SQLite in `state.db`; `MemoryGrantStore` for tests). Decisions go to an `AuditSink`. Allowed checks
are not audited; grants, revokes, refused grants and denials are.

### ModuleContext

Built per module at activation from `ContextServices(policy, logs, panels, bus, brokers)`. Members always present:
`module_id`, `log(stream, event, **fields)` (declared `log_streams` only), `register_panel(panel_id, render)`
(declared `panels` only, needs `ui.panel`), `emit(type, data)` (type must be `<module_id>.<name>`, so a module
cannot spoof core events), `subscribe(type, handler)`, `state` (namespaced store, added with the state store),
`health_report(ok, detail)`. `close()` removes panels and subscriptions and makes every member raise. Capability-gated members raise `CapabilityDenied` when ungranted: `secrets`
(`secrets.read`), `net` (`net.outbound`, host allow-list), `schedule` (`schedule`), `spawn` (`process.spawn`).
The context never exposes the core, other modules or the policy engine.

### State store

`StateStore(path)`; `migrate()` applies `switchyard/migrations/NNNN_*.sql` in order inside a transaction after
copying the file to `backup/`. `ModuleState(module_id)`: `create_table(name, columns, primary_key)` (STRICT tables; types TEXT, INTEGER, REAL,
BLOB), `execute(sql, params)` (one statement), `kv_get`, `kv_set`, `drop_all()`. Confinement uses SQLite's
authorizer callback, not SQL parsing: while a module statement is prepared, any table outside `m_<id>__`
(core tables, other modules, `sqlite_master`) and any PRAGMA, ATTACH, DDL or transaction control is denied.
Names match `^[a-z][a-z0-9_]{0,31}$`; module ids and table names may not contain `__`, so one module cannot
forge another's prefix (also a manifest rule). Grants persist through `SqliteGrantStore`.

### Audit log

Record: `{"seq", "ts", "actor", "action", "module", "detail", "prev", "hash"}` where
`hash = sha256(canonical_json(record without hash))` and `prev` is the previous `hash` (genesis `"0"*64`). Canonical
JSON: sorted keys, `separators=(",", ":")`, UTF-8. `append(...)` fsyncs. `verify() -> VerifyResult(ok, first_bad_seq)`
detects edit, deletion, insertion and reorder. Tail truncation is detected against a stored head anchor:
`verify(expected_head=(seq, hash))`; the core keeps the head in `state.db`. A torn last line makes opening fail
closed. `detail` values must be strings (max 1024 chars) and pass through the redactor before writing. Files
rotate at 8 MiB with the chain running across files.

### Events and scheduler

`Event(type, source, data, ts)`; types are dotted lower-case with at least two parts; subscriptions take an exact
type, `<prefix>.*` or `*`. Handlers run synchronously in subscription order, each on its own copy of the data
(JSON-compatible, <= 64 KiB). A handler exception is audited by class name only, reported to `on_handler_error`,
and never propagated. Re-entrant publishing is limited to depth 8 per thread.

`Trigger(id, owner, kind, spec, callback, min_interval_s)`. Specs: `time` `{"every": s}` or `{"cron": "m h dom mon dow"}`;
`event` `{"type": pattern}`; `usage`/`capacity` `{"metric": name, "above"|"below": x}` fed by `observe()`
(edge-triggered). `tick()`, `observe()`, `fire()`; one run at a time per trigger; runs within `min_interval_s` are
skipped and counted; `trigger.fired`/`trigger.skipped` events; failures audited by class name. The scheduler owns
no thread. **Open (Hermes adapter PR):** Hermes idle tasks are gated by `min_idle_hours`/`interval_hours`, too
coarse for minute-level triggers; choose the Hermes-side driver (plugin thread or Hermes cron) in that PR.

### Lifecycle

`ModuleManager`: `discover(roots)` (load + verify manifests; reject invalid, duplicate, or untrusted in-process
modules), `activate(id)`, `deactivate(id, reason)`, `health(id)`, `remove(id, keep_data=False)`,
`set_mode(id, manual|auto|disabled)`, `start_auto()`, `touch(id)`, `tick()` (idle stop), `modules()`, `info(id)`.
States: `verified`, `active`, `stopped`, `failed`. Modes persist in the `modules` table. Each module is imported as
the synthetic package `_switchyard_modules.<id>` rooted at its directory (no name clashes, relative imports work,
removal purges `sys.modules`). In-process modules are accepted only under trusted roots (resolved paths). Any
exception from import, construction, `activate`, `health` or a bus handler fails that module closed (audited by
class name); deactivation always closes the context and removes the module's triggers. `health()` may return a
bool, `(bool, str)` or an object with `ok`/`detail`. Logs: `JsonlLogSink` (one user-only file per stream, every
string redacted, 16 KiB line cap). Panels: `MemoryPanelRegistry`. `ctx.state` returns the module's `ModuleState`.
Release signature verification of T1 modules is deferred until a signing key exists (Q&A A8/C7).

### T2 subprocess host

Child started with `[sys.executable, "-I", "-m", "switchyard.host_t2_child"]`, cwd = module dir, stderr discarded,
environment reduced to an allow-list (`PATH`, `SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR`, `TEMP`, `TMP`, `TMPDIR`, `HOME`,
`USERPROFILE`, `LANG`, `LC_ALL`) plus `SWITCHYARD_T2=1`; module `print()` goes to stderr. Framing (`switchyard.rpc`):
4-byte big-endian length + UTF-8 JSON-RPC 2.0, max frame 1 MiB both ways. One symmetric `Channel` on both sides serves
nested calls while waiting for its own response (depth 16). Parent calls time out (default 10 s); a timeout, protocol
violation or child exit kills the child and fails the module closed (`T2Timeout`, `ProtocolError`). `T2Module` presents
`activate/deactivate/health`, so `ModuleManager` drives T1 and T2 identically (`t2_factory`). Child `ctx.*` calls are
replayed on the module's real `ModuleContext`; state operations are limited to `table`, `create_table`, `execute`,
`kv_get`, `kv_set`; capability brokers are policy-checked and then refused in M0 (objects cannot cross the boundary).
Errors cross with the exception class only; core errors (`CapabilityDenied`, `StateError`) also carry their message and
are rebuilt as the same class in the child.

### Secrets broker (interface only in M0)

`SecretRef("secret://name")`; `SecretBackend` protocol (`name`, `available()`, `get(name)`). `SecretsBroker.use(module,
ref, fn)`: policy (`secrets.read` + declared names), first available backend wins, none -> `SecretUnavailable`
(audited); the value is registered with the `Redactor` and the use audited by name; `fn(value)`'s result is returned
only if the value does not appear in it (`SecretLeak`, audited). If `fn` raises, only its class name is re-raised,
with no exception context, and the value is deleted from the frame before any raise so tracebacks carry no copy.
`ctx.secrets` returns `ModuleSecrets` (broker bound to the module, via a `for_module` hook on brokers). `Redactor`
masks registered values (>= 4 chars, longest first) and default credential shapes (OpenAI/Anthropic `sk-`, GitHub
`ghp_`/`github_pat_`, AWS `AKIA`, Slack `xox?-`, bearer tokens). `MemoryBackend` is test-only (refuses outside pytest
unless `allow_test_backend=True`).

### Host profiler

`profile() -> HostProfile(cpu_count, ram_bytes, disk_free_bytes, gpu: str | None, net_class, profile_name)`.
RAM: Windows `GlobalMemoryStatusEx`, Linux `/proc/meminfo`, macOS `sysctlbyname("hw.memsize")`, all via `ctypes`
or files (no subprocess, no network; `net_class` is `unknown`). GPU: best effort (`/proc/driver/nvidia/version`).
Profile: `tiny` < 4 GiB RAM or < 2 CPUs; `laptop` < 16 GiB; `workstation` < 64 GiB; else `server`. Overridable in
config. `capacity_metrics(data_dir)` gives `disk.free_ratio` and (where known) `ram.free_ratio` for capacity triggers.

### Control API

`switchyard api serve` binds `127.0.0.1` on `api.port` (0 = ephemeral; actual port written to `api.port` file).
Token: `secrets.token_urlsafe(32)` written to `api.token` with user-only permissions, rotated per start.
Request checks, in order: method `POST` (or `GET /v1/health`); `Host` is `127.0.0.1:<port>` or `localhost:<port>`;
any `Origin` header (including `null`) is refused, since the only client is the CLI; `Authorization: Bearer` compared with
`hmac.compare_digest`; `Content-Type: application/json`; body <= 64 KiB. Routes `POST /v1/<noun>/<verb>` map 1:1 to CLI
operations. Responses never echo request text into headers; a header writer rejects CR/LF. Client reads are
capped at 1 MiB.

### Core and operations

`Core(data_dir, hermes_dir, trusted_roots, module_roots, secret_backends)` builds every component for one data
directory and is the only object adapters hold. Data dir: resolved per section 2, then `config.toml` there may
redirect it once. `AnchoredAudit` writes the audit head to `meta['audit.head']` after every append; startup runs
`verify(expected_head=...)` and on failure records `audit.verify_failed` and exposes `audit_status` (the core keeps
running so it can report). Trusted and module roots default to the package's `switchyard/modules` (trusted) plus
`<data_dir>/modules` (untrusted, so subprocess only). `Core.run(noun, verb, params, actor)` dispatches through
`switchyard.ops.OPERATIONS`; each `Operation` has typed parameters (`UsageError` on unknown, missing or mistyped
values), a description, and an `offline` flag for operations that are safe without a running daemon.
`Core.tick()` drives time triggers, idle stop and capacity metrics. Operations: `module list|show|grant|revoke|mode|
activate|deactivate|health|panel|remove`, `audit verify|tail`, `host profile`, `config show`.

### CLI

`switchyard [--data-dir D] [--json] <noun> <verb> [args]`. Nouns: `module`, `audit`, `host`, `api`, `config`.
Exit 0 success, 1 operation error, 2 usage error, 3 denied.

### Hermes adapter

`register(ctx)`: builds `Core` with `data_dir = ctx.state.data_dir`; registers tools `switchyard_modules`,
`switchyard_audit`, `switchyard_host` (toolset `switchyard`), command `/switchyard`, CLI command `switchyard`.
Declares no Hermes plugin capabilities. Tool results are JSON strings passed through the redactor.

### Update control

`UpdateController.update(module_id, ref) -> UpdateResult`. Fetcher is injectable (`GitFetcher` runs `git` with an
argument list, `-c protocol.file.allow=never` in production; tests inject a local-repository fetcher because the
manifest schema allows only `https://` URLs). Steps: fetch, check `HEAD` equals `ref`, validate manifest, stage,
deactivate, swap (rename), activate, health; on failure swap back and reactivate the previous version. All steps audited.

## 4. Events

`module.discovered|verified|granted|revoked|activated|deactivated|failed|removed|updated|rolled_back`,
`policy.denied`, `trigger.fired|skipped`, `audit.verify_failed`.

## 5. Acceptance tests

As listed in [01-m0-prework.md](../qa/01-m0-prework.md) section 4, plus the threat tests in its question 5 table.
Coverage target for `src/switchyard`: 90%.
