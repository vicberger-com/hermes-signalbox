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
`hmac.compare_digest`; `Content-Type: application/json`; no `Transfer-Encoding`; body <= 64 KiB, checked before
reading. `GET /v1/health` needs no token. Status codes: 400 usage, 401 token, 403 Host/Origin/denied, 404 route,
409 operation error, 411/413/415 framing, 500 unexpected (class name only). Socket timeout 10 s; request lines are
never logged; `Server: switchyard`. Routes `POST /v1/<noun>/<verb>` map 1:1 to CLI
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

`switchyard [--data-dir D] [--json] <noun> <verb> [id] [--param value]`, generated from the operations table, plus
`switchyard api serve [--port N]` and `switchyard version`. With a daemon running for the data dir every operation goes
through the API; otherwise `offline` operations run directly and live ones (activate, deactivate, health, panel) ask for
the daemon. `api serve` runs `start_auto()`, then `Core.tick()` every second until interrupted. Exit 0 success,
1 operation error, 2 usage error, 3 denied.

### Hermes adapter

`switchyard.hermes.register(ctx)` (entry point `hermes_agent.plugins`; root `plugin.yaml` + shim `__init__.py` for
`hermes plugins install`). Builds `Core` with `data_dir` = setting `data_dir` or `ctx.state.data_dir`. Registers:
model tools `switchyard_modules` (list, show, activate, deactivate, health), `switchyard_audit` (verify, tail),
`switchyard_host` (toolset `switchyard`); slash command `/switchyard <noun> <verb> [id] [key=value]` (every operation);
CLI command `hermes switchyard` (the full CLI; skipped by Hermes under `plugins.isolation: host`); daily idle task
`switchyard-audit-verify`; the redactor's default patterns that start with two literal characters (Hermes rule).
**The model-facing tools cannot grant or revoke capabilities, change modes or remove modules** (a prompt-injected
model could widen its own access); those are human paths only. Tool handlers catch every exception and return JSON
with core messages only, because Hermes otherwise forwards exception text to the model. No Hermes plugin
capabilities are declared. Verified with `hermes plugins validate` on Hermes v0.23.2.

**Hosting.** Only the process holding the OS lock on `<data_dir>/host.lock` (`msvcrt.locking` / `fcntl.flock`;
dropped by the OS on exit) hosts modules: `start_auto()` plus a daemon thread calling `Core.tick()` every 15 s
(resolves the open item: Hermes idle tasks are hour-scale). `Core(hosting=True|None|False)`; non-hosting cores refuse
live operations (activate, deactivate, health, panel). `api serve` requires hosting; the offline CLI never hosts.

### Update control

`UpdateController.update(module_id, ref)` for modules under `<data_dir>/modules` with `[update] source = "git"`
(bundled modules update with the release). `ref` must be a full lower-case SHA; the URL is the one pinned in the
installed manifest. Fetch into `<data_dir>/staging/<id>/stage-<ref>` via an injectable `Fetcher`; `GitFetcher` runs
`git` with a fixed argv, scrubbed environment, `GIT_CONFIG_NOSYSTEM`, empty global config, `core.hooksPath` to the
null device, `protocol.file.allow=never` (tests may allow file URLs), `--depth 1`, a timeout, verifies `HEAD == ref`
and removes `.git`. The staged manifest must be valid and keep the module id and the pinned source URL. Then
deactivate, swap by rename (previous kept as `previous-<version>-<time>`), `ModuleManager.reload` (re-checks trust),
reactivate if it was running, health check; any failure restores the previous directory (`module.rolled_back`).
`rollback(id)` restores the most recent previous version. Operations `module update {id, ref}` and
`module rollback {id}` require the hosting process. Every outcome is audited (`module.update_rejected`,
`module.updated`, `module.rolled_back`).

## 4. Events

`module.discovered|verified|granted|revoked|activated|deactivated|failed|removed|updated|rolled_back`,
`policy.denied`, `trigger.fired|skipped`, `audit.verify_failed`.

## 5. Acceptance tests

**Contract suite.** `switchyard.contract.run_contract(module_dir) -> ContractReport` (stdlib only, usable from
third-party module repositories). Copies the module into a temporary data directory and runs it through a real
hosting core: `manifest`, `discover`, `deny_ungranted` (probe `net.outbound`, or `process.spawn` if the module asks
for net), `activate` (all requested capabilities granted; second activate is a no-op), `health`, `panels` (exactly
the declared panels, JSON-serialisable), `deactivate` (twice; panels removed), `remove` (grants gone), `audit` (chain
verifies; grant/activation/denial/removal recorded). Later checks are skipped after a failure. Checks raise
`ContractFailure`, not `assert`, so they hold under `python -O`. The template passes in-process and in the T2 host.

**End to end.** `tests/acceptance/test_m0_acceptance.py` covers every item of the Q&A section 4 list through the CLI,
the loopback API and the Hermes adapter on one data directory.

As listed in [01-m0-prework.md](../qa/01-m0-prework.md) section 4, plus the threat tests in its question 5 table.
Coverage target for `src/switchyard`: 90%.

## 6. Security review (M0 gate)

Reviewed 2026-11-19 by three fresh subagents (control surfaces; loading, isolation and updates; policy,
secrets, state and audit) given only the M0 diff and the threat table, then triaged against the code.

| Finding | Disposition |
|---|---|
| Recursive-CTE or cross-join query exhausts CPU/memory | **Fixed.** CTEs were already refused by the authorizer; cross joins on a module's own tables are now bounded by a progress-handler work budget and a 10 000-row cap. Also fixed: `count(*)` was wrongly denied |
| Staged update may carry files that point outside the tree | **Fixed (adapted).** `.gitattributes`/`.gitmodules` are inert (no git runs on the staged tree after `.git` is removed), but symlinks are refused anywhere in a staged tree |
| `api.token` readable by other Windows users | **Fixed (hardening).** Default data dirs already inherit a user-only profile ACL; the file now gets an explicit single-user ACL via `icacls`, failing closed |
| Model tool can `activate` modules | **By design.** Activation uses only capabilities a human already granted; grants, modes and removal are not reachable from model tools |
| Trust check at discovery and import at activation (TOCTOU) | **Accepted.** Trusted roots are the installed package directory; an attacker who can write there already controls the code. `reload` re-checks trust |
| T2 child inherits `PATH` | **Accepted, documented.** The T2 host is a fault and capability boundary, not an OS sandbox: a subprocess module runs as the same user. OS-level sandboxing is future work |
| Leak check misses transformed secrets (e.g. base64) | **Accepted, documented.** The broker stops accidental leaks of the raw value; it cannot stop a module that deliberately encodes a secret it was granted. Grant `secrets.read` only to modules you trust |
| Audit anchor lives in the same data directory | **Accepted, documented.** Detects editing, deletion and reordering; an attacker who can rewrite both `state.db` and the log can forge history. External anchoring (e.g. periodic signed checkpoints) is future work |

## 7. Contract additions after M0 (ADR-0002)

- `ModuleContext.register_action(name, handler, *, params, read_only)`: `name` declared in `contributes.commands`,
  `params` values `bool | int | str`. Run with operation `module action {id, action, args}` (hosting process only).
  Arguments are validated against `params`; results must be JSON and are redacted; handler exceptions become
  `"action <name> failed: <ExceptionClass>"`. Audited as `module.action` (action name only). The Hermes model tool
  (`switchyard_modules` action `run`, actor `hermes`) may run `read_only` actions only; `/switchyard` uses actor
  `hermes-user`. CLI: `--args '<json object>'`; slash command: extra `key=value` words go into `args`.
- `ModuleContext.provide_secret_backend(backend)`: in-process modules only, `secrets.read` granted, `backend.name`
  declared in `contributes.secret_backends` (`[a-z][a-z0-9_-]{0,31}`), unique across modules. Removed when the
  module's context closes. Audited `secret.backend_added` / `secret.backend_removed`.
- `ctx.hermes_hook(name, fn)` / `ctx.hermes_middleware("llm_request", fn)` (ADR-0004): needs `hermes.hooks` and the
  name (or `middleware:<kind>`) in `contributes.hooks`. The adapter registers one forwarder per hook and the
  `llm_request` middleware with Hermes (`provides_hooks`, `provides_middleware` in `plugin.yaml`). Callbacks get
  copies; exceptions are audited as `module.hook_failed`; a middleware result that changes anything other than
  `model` is dropped (`module.middleware_rejected`).
- `ctx.call(module_id, action, args)`: another module's read-only action, actor `module:<caller>`.
- Manifest `capabilities.optional` (M4): a subset of `request` that `start_auto` does not wait for; the module
  checks it at run time with `ctx.has`.
- Observer hooks deliver metadata only (`switchyard.bridge.metadata_only`).
- `ctx.hermes_config` (ADR-0005): `hermes.config.write`; allow-listed keys, backup, audit, read-back, rollback,
  `revert`. Provided only when the Hermes adapter supplies a config port.
- ADR-0006: `ctx.schedule.every(name, seconds, fn)` (`schedule`), `ctx.core` (`core.read`), `ctx.hermes_gate(fn)`
  (`gate:pre_llm_call` declared; blocks a turn with a prefixed reason; fails open).
- ADR-0007: `ctx.hermes_delegation(route, roles)` (`hermes.delegation`; one module); Hermes backend `switchyard`.
- ADR-0008: `ctx.hermes_transform(kind, fn)` (`hermes.output`; returns kept line ranges; core rebuilds).
- ADR-0009: `ctx.notify.send(severity, title, detail)` (`notify`); `report show`; dashboard tab via the control API.

