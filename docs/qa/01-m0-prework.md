# Pre-work Q&A: M0 Core framework

Date: 2026-11-19. Previous phase: P0, tag v0.0.1.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| P0 | CI matrix is Linux, Windows, macOS on Python 3.11 and 3.13; tooling is hash-pinned in `requirements-dev.txt` | Runtime code must work on 3.11 (no 3.12+ syntax such as `type` aliases or PEP 695 generics) |
| P0 | The repository is private, so CodeQL, Scorecard and build provenance are skipped; tags are unsigned | Security gate for M0 relies on bandit, ruff `S` rules, gitleaks, pip-audit and the behaviour tests; A7 (go public after the M0 gate) stays open |
| P0 | `tools/validate_manifest.py` is a stdlib validator that rejects unknown schema keywords | Keep that approach: the core manifest loader reuses its checks instead of adding `jsonschema` |
| 00 C4 | Packaging was "root `plugin.yaml` + thin `__init__.py`, confirm in M0 research" | Confirmed and extended, see question 7 and the research record |
| Operator setup | The "Hard" delegation route points at a Haiku-class model | Architecture, security review and integration stay on the main model; delegation is used only for collection and boilerplate |
| Hermes | v0.23.3 was released 2026-11-20 (UTC); development continues against the installed v0.23.2 | Re-check plugin API facts against v0.23.3 before the M0 adapter PR merges |

## 2. Research record

| Topic | Source (URL, commit or version, date read) | Finding |
|---|---|---|
| Hermes API changes since last phase | Installed Hermes v0.23.2 source, `hermes_cli/plugins.py`, `plugins_context.py`, `plugins_discovery.py`, `plugins_manifest.py`, `plugins_state.py`, read 2026-11-19 | `SUPPORTED_MANIFEST_VERSION = 2`. `VALID_HOOKS` still contains every hook named in `DESIGN.md` section 6, plus new ones (`on_session_open`, `pre_verify`, `pre_auxiliary_call`, kanban hooks). `register_tool(name, toolset, schema, handler, check_fn, requires_env, is_async, description, emoji, override)`; `register_command(name, handler, description, args_hint, argument_mode)` rejects names that clash with built-ins; `register_cli_command(name, help, setup_fn, handler_fn)`. `ctx.get_config(key)` reads `plugins.entries.<id>.settings.<key>`. `ctx.state.data_dir` is `<HERMES_HOME>/plugin-data/<namespace>` |
| Hermes plugin capability consent (new) | `hermes_cli/plugin_capabilities.py`, v0.23.2 | Hermes now has its own declared-capability consent for plugins (`tools.override`, `llm.*_override`, `llm.side_question`, `llm.session_fork`, `gateway.platform_actions`). Unknown ids are dropped (fail closed). Switchyard's M0 adapter needs none of them |
| Hermes plugin isolation (new) | `hermes_cli/plugin_isolation.py`, `plugin_host.py`, v0.23.2 | `plugins.isolation: host` runs third-party plugins in one plugin-host process per profile. This is Hermes's boundary around the Switchyard plugin as a whole; it does not isolate Switchyard modules from each other, so Switchyard keeps its own T2 subprocess host |
| Hermes plugin discovery | `hermes_cli/plugins_discovery.py`, v0.23.2 | Three sources: bundled, `<HERMES_HOME>/plugins/<name>/plugin.yaml`, project `.hermes/plugins/`, and the entry-point group `hermes_agent.plugins` (capabilities through `hermes_agent.plugin_capabilities`). `hermes plugins validate` imports a plugin in a scratch child process and compares registrations to the manifest's `provides_*` lists |
| Hermes release state | GitHub API `repos/NousResearch/hermes-agent/releases`, read 2026-11-19 | Latest stable v0.23.3 (2026-11-20T00:34Z). Its notes defer curated notes to v0.24.0 and list no plugin API change |
| `MyAiFreedomSystems/hooks-guide` (M0 source) | GitHub API, read 2026-11-19 | MIT, last push 2026-08-14, 0 stars. Used as reading only; hook names are taken from Hermes source, not from this guide |
| PyYAML (planned) | PyPI JSON + OSV, 2026-11-19 | 6.0.3 (2025-09-25), MIT, no OSV advisory at latest. **Not needed in M0** (see question 4) |
| httpx (planned) | PyPI JSON + OSV, 2026-11-19 | 0.28.1 (2024-12-06), BSD-3-Clause, no advisory, no release for 23 months. **Not adopted**; stdlib suffices for a loopback API |
| platformdirs, psutil, jsonschema, tomli-w (alternatives) | PyPI JSON + OSV, 2026-11-19 | platformdirs 4.14.7 MIT; psutil 7.2.2 BSD-3-Clause; jsonschema 4.26.0 MIT; tomli-w 1.2.0 MIT; none has an OSV advisory. None adopted in M0; each need is under 60 lines of stdlib code |
| Advisories: stdlib `http.server` | cpython issue #142533 and docs PRs #142605, #143395, #148020, #148021 | `send_header()` does not reject CRLF; CPython chose a documentation warning. The control API must never place request-derived text in a header, and must validate header values itself |
| Advisories: stdlib `http.client` | NVD CVE-2025-13836 | Reading a response without an explicit size trusts `Content-Length`. The CLI's API client always reads with a byte cap |
| Current best practice for loopback control APIs | Same CPython docs; DNS-rebinding guidance as applied by Jupyter and similar local servers | Bind 127.0.0.1 only; random per-start bearer token in a user-only file; constant-time token compare; reject unexpected `Host` (DNS rebinding) and any cross-origin `Origin`; no CORS headers; cap body size; JSON only |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | What is the smallest scope that meets the acceptance criteria? | (a) all 12 items of the M0 work breakdown; (b) defer T2 host and update control to later phases | (a). The acceptance criteria name update, rollback and a third-party boundary; deferring them would change the core contract later. Delivered as a sequence of PRs: (1) package, config, data dir, manifest loader; (2) policy, grants, `ModuleContext`; (3) state store, audit log; (4) event bus, scheduler; (5) lifecycle T1, then T2 host; (6) secrets broker interface; (7) host profiler; (8) CLI and API; (9) Hermes adapter; (10) update control; (11) example module and contract test suite. Tag v0.1.0 after the last | default accepted |
| 2 | Which capabilities does the module need, and which can be dropped? | Core is T0 and holds no grant; it enforces the schema's capability vocabulary | Keep the schema's 13 capability ids unchanged. The example module requests only `ui.panel`. The contract suite proves a denied call on an ungranted capability (`net.outbound`) | default accepted |
| 3 | Reuse, adapt or write: which upstream code, under which reuse class? | Copy from Hermes `plugin_host` (MIT); write our own | Write our own. Hermes is called through its public plugin API only, never imported for internals, so the core keeps no dependency on Hermes. Hermes `plugin_host.py` and `plugins_state.py` are read as design references (MIT, `vendor-ok`; nothing copied, so no `NOTICE` entry yet). `hooks-guide` is reading only | default accepted |
| 4 | New dependencies: are all five rules in `THIRD-PARTY.md` met? | (a) zero runtime dependencies; (b) PyYAML + httpx as planned in `DESIGN.md` | (a). Inside Hermes, config comes from `ctx.get_config`, so PyYAML is not needed; standalone config is TOML through `tomllib`. A loopback API needs no HTTP client library. Data-dir resolution and host profiling are small enough to own. Zero runtime dependencies means a smaller trusted base and no supply-chain surface for the core. Recorded in ADR-0001 | default accepted |
| 5 | What can go wrong for security (inputs, secrets, spend, egress)? How is each tested? | | See the threat table below; each row has a named test | default accepted |
| 6 | State schema and migration; what is removed on uninstall? | One SQLite file with per-module table prefixes; one file per module | One file `<data_dir>/state.db` (WAL). Core tables: `meta`, `modules`, `grants`, `activation`, `triggers`. Module tables are named `m_<module_id>__<name>`, created only through `ctx.state`, which validates names and uses parameter binding. Migrations: numbered, forward-only, each in one transaction, `user_version` checked; a file copy is taken before any migration. Uninstall drops the module's tables, grants and triggers unless the user passes `--keep-data`. The audit log is never pruned by uninstall | default accepted |
| 7 | Control surface: tools, commands, panel, config keys | | CLI `switchyard module list/show/grant/revoke/enable/disable/activate/deactivate/update/rollback/remove`, `switchyard audit verify/tail`, `switchyard host profile`, `switchyard api serve`. API: `POST /v1/<noun>/<verb>`, JSON, same operations. Hermes: tools `switchyard_modules`, `switchyard_audit`, `switchyard_host` (toolset `switchyard`); slash command `/switchyard`; CLI command `hermes switchyard`. Packaging: an entry point in group `hermes_agent.plugins` for pip installs, plus a root `plugin.yaml` and `__init__.py` for `hermes plugins install` from git. Config keys: `data_dir`, `api.enabled` (default false), `api.port` (default 0 = ephemeral), `log.level`, `host.profile` (default auto) | default accepted |
| 8 | Logs, metrics, report section, alerts | | Stdlib `logging`, one logger per module (`switchyard.module.<id>`), JSON Lines under `<data_dir>/logs/`. Counters (activations, denials, failures) in `state.db`. `health()` per module, aggregated by `switchyard module list`. Alerts are M9 | default accepted |
| 9 | Update source and rollback check | | Sources `bundled` and `git` (pinned 40-char SHA). Flow: fetch to `<data_dir>/staging/<id>/<sha>`, verify commit and manifest, run the module's tests in a subprocess, swap, run `health()`, roll back to the previous directory on any failure. `git` is run with an argument list, never a shell, with a scrubbed environment. Tests use a local bare repository, never the network | default accepted |
| 10 | Does anything need a core contract change (ADR)? | | Yes, small: ADR-0001 records zero runtime dependencies (replacing the PyYAML and httpx plan in `DESIGN.md` section 3), the single-file state store with table prefixes, and Switchyard's own T2 host alongside Hermes `plugins.isolation`. `DESIGN.md` is updated with it | default accepted |
| 11 | Operator input needed (names only for secrets)? | | None for M0. The secrets broker ships with an in-memory test backend only | default accepted |

### Threats and tests (question 5)

| Threat | Control | Test |
|---|---|---|
| Module uses a capability it was not granted | Policy engine is the only path to brokers; default deny | `test_denied_capability_raises_and_is_audited` |
| Secret value leaks to a result, log, audit record or exception | Broker returns opaque handles; resolved only inside the outbound call; redaction filter on all log handlers | `test_secret_canary_never_in_output` (canary value searched in every output stream) |
| Audit log is edited or truncated | SHA-256 chain, genesis record, `audit verify` | `test_audit_chain_detects_edit_delete_reorder` |
| Malformed or hostile manifest | Schema + cross-field checks before import; module path must stay under its root | `test_manifest_rejects_*`, `test_entry_path_traversal_rejected` |
| Third-party module code runs in-process | `isolation = "subprocess"` required for anything outside this repository | `test_third_party_forced_to_subprocess` |
| T2 child abuses the pipe or hangs | Size-capped JSON-RPC frames, per-call timeout, kill on protocol violation, scrubbed environment | `test_rpc_oversize_frame_kills_child`, `test_child_env_has_no_secrets` |
| Local web page drives the control API (DNS rebinding, CSRF) | 127.0.0.1 only, bearer token, `Host` allow-list, reject cross-origin `Origin`, no CORS | `test_api_rejects_bad_host`, `test_api_rejects_origin`, `test_api_requires_token` |
| Header injection in the API | No request-derived header values; header writer rejects CR/LF | `test_api_header_crlf_rejected` |
| SQL injection through module table or key names | Name regex, parameter binding only | `test_state_rejects_bad_table_name` |
| Tampered or substituted update | Pinned commit SHA, verify before staging, health check, rollback | `test_update_wrong_sha_rejected`, `test_failed_health_rolls_back` |
| Runaway trigger (spend, CPU) | Per-trigger minimum interval and concurrency 1 | `test_trigger_rate_limited` |
| Unbounded response read in the CLI client | Byte cap on every read (CVE-2025-13836 class) | `test_client_caps_response_size` |

## 4. Acceptance tests (written before code)

- [ ] The example module from `templates/module/` is discovered, verified, granted, loaded and activated.
- [ ] A call needing an ungranted capability raises `CapabilityDenied` and writes an audit record.
- [ ] Every grant, activation, denial, update and rollback appears in the audit log; `audit verify` passes, and fails after any edit.
- [ ] The example module is updated to a pinned commit and rolled back after a failing health check, with the core still running.
- [ ] The same operation (list, enable, disable) works from the CLI, the loopback API and the Hermes tool, with the same result.
- [ ] A secret canary value never appears in any tool result, log line, audit record or exception text.
- [ ] Coverage of `src/switchyard` is at least 90%; mypy strict passes on `src/`.

## 5. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
