# Design

Source requirement: `Hermes Application.docx` (operator, 2026-11). Hermes facts below were verified against the
installed Hermes Agent v0.23.2 source (`hermes_cli/plugins.py`, `hermes_cli/plugins_context.py`) on 2026-11-19.
Re-verify at each phase; the plugin API changes between releases.

## 1. What it is

A control plane that lets Hermes (or a person) decide which skills, plugins, models, agents and external tools
are active, who may use them, what they cost, and what happens when they fail or run out. It has two parts:

- **Core**: a small trusted framework. It owns loading, policy, secrets, state, audit, scheduling, updates and
  the control interfaces. It does nothing useful on its own.
- **Modules**: snap-on units. Each brings its own capability, control-interface additions, security rules,
  logging, reporting and update source. A module can be added, enabled, disabled, updated or removed without
  touching the core or other modules.

It runs standalone (`switchyard` CLI and a loopback daemon) and as a Hermes plugin. The Hermes plugin is a thin
adapter over the same core, so Hermes has full control without the core depending on Hermes internals.

## 2. Constraints from the requirement

| Requirement | Design answer |
|---|---|
| Manage skills and plugins, switch on only when needed | M5 activation manager with presets and idle shutdown |
| Resource pools, free first, paid only above set thresholds | M2 registry and pools, M3 router with paid gating rules |
| One secure place for tokens, keys, passwords | M1 secrets broker; values never enter model context |
| Dynamic switching on exhaustion or degradation | M4 metering feeds M3 failover |
| Always-on manager using only free resources | M6 supervisor; policy denies it `llm.paid` |
| Triggers by time, capacity or use | Core scheduler and trigger engine |
| Enable, disable, manual, automatic per resource | Uniform activation state on every module and resource |
| Laptop to server, host analysis | Core host profiler selects a capacity profile |
| Self-hosted models and tools | M2 treats local endpoints as first-class pool members |
| Offload to n8n, JevK5, OpenClaw, other agents | M11 connectors |
| Reporting, dashboards, alerts, logging | M9, on top of core audit and metrics |
| Attachable security testing | M10 scanner connectors, scheduled from the control plane |
| 100% Hermes-native control | Every function is exposed as a Hermes tool, command and dashboard panel |
| Open and closed-source tooling as the user allows | Connector license class plus explicit user allow-list |

## 3. Architecture

```
            Hermes Agent (CLI, gateway, desktop, dashboard)
                 |  plugin adapter: tools, hooks, commands, panels
+----------------v---------------------------------------------------+
| CORE (trusted)                                                     |
|  Module loader  Policy engine  Secrets broker  Event bus           |
|  State store    Audit log      Scheduler       Host profiler       |
|  Update control Control API (loopback)   CLI                       |
+----^-----------^-----------^-----------^-----------^---------------+
     | ModuleContext (only what the manifest was granted)
   M1 secrets  M2 registry  M3 router  M4 metering  M5 activation ... M12
```

### Core components

| Component | Responsibility | Notes |
|---|---|---|
| Module loader | Discover, verify, load, start, stop modules | Verifies manifest schema, signature and granted capabilities before import |
| Policy engine | Default-deny capability checks | Single choke point; every broker call passes through it |
| Secrets broker | Resolve `secret://name` at the point of use | Backends are modules (M1); core defines the interface only. Trusted in-process modules provide backends ([ADR-0002](adr/0002-module-backends-and-actions.md)) |
| Event bus | In-process publish and subscribe, typed events | Modules never call each other directly |
| State store | SQLite (WAL), one schema per module, migrations | Stdlib `sqlite3` |
| Audit log | Append-only, hash-chained JSON Lines | Each record carries the previous record's SHA-256 |
| Scheduler | Triggers: time, capacity, usage, event | Delegates to Hermes cron and idle tasks when hosted in Hermes |
| Host profiler | CPU, RAM, GPU, disk, network class | Selects `tiny`, `laptop`, `workstation` or `server` profile |
| Update control | Pinned sources, verify, stage, apply, roll back | Produces an SBOM delta per update |
| Control API | Loopback HTTP + local token, JSON | Binds 127.0.0.1 only; no remote listener in core |
| CLI | `switchyard <noun> <verb>` | Same operations as the API |

### Stack

Python >= 3.11, standard library only in the core: zero runtime dependencies
([ADR-0001](adr/0001-m0-core-stack.md)). Inside Hermes, settings come from `ctx.get_config`, so the core does not
parse YAML. Module manifests are TOML because `tomllib` is in the standard library and TOML has no implicit typing
surprises. No web framework in core; the control API uses `http.server` behind the policy engine, with the
hardening listed in section 4. Modules that need a library declare it in their own phase.

## 4. Trust and security model

**Trust levels**

| Level | What | Isolation |
|---|---|---|
| T0 | Core | Trusted computing base; kept small and fully reviewed |
| T1 | First-party modules in this repository | In-process, signed with the release, capability-checked |
| T2 | Third-party modules | Separate subprocess, JSON-RPC over stdio, scrubbed environment, no secret values; same OS user (see below) |
| T3 | External tools and services (gateways, n8n, scanners) | Reached only through a connector module with declared hosts |

Python cannot sandbox code inside one process. Capability checks on T1 modules are a correctness and audit
control, not a containment boundary. Anything not reviewed in this repository runs as T2.

**The same-user boundary (R1 review).** Switchyard runs as your OS user and keeps its state in files your user
can read and write. Anything else running as that user is outside its control: a T2 module process (it can
open `state.db`, read `api.token`, or open sockets without asking the core), and a model with an unrestricted
shell tool (it can run `switchyard` itself). For those, the T2 host is a fault and request boundary, not a
security boundary, and the audit log is tamper-evident only against changes to one of its two files. Real
containment needs the operating system: run untrusted modules only after review, and restrict the model's
shell with Hermes's command approval or sandbox. A future release may run T2 modules under a separate,
restricted account.

**Controls**

1. Default deny. A module gets only the capabilities its manifest requests and the user grants. Grants are
   stored, audited and revocable.
2. Secrets by reference. Modules and models handle `secret://name`. The core resolves the value inside the
   outbound request and never returns it to a module result, a log or model context. Known secret shapes are
   registered with Hermes redaction (`register_redaction_patterns`).
3. Egress allow-list. Requests made through the core (`ctx.net`) go only to hosts declared in
   `capabilities.net_hosts`. This binds in-process modules that use the broker; it is not an OS firewall.
4. Paid-resource gate. `llm.paid` is a separate capability with budget limits. The supervisor can never hold it.
5. Tamper-evident audit. Every grant, activation, routing decision above a threshold, secret use (name only),
   update and policy change is written to the hash-chained log. `switchyard audit verify` checks the chain.
6. Supply chain. Dependencies pinned with hashes; license allow-list enforced in CI; SBOM (CycloneDX) per
   release; build provenance attestation; module updates verified against a pinned commit or signature before
   staging; automatic rollback when the post-update health check fails.
7. Control interface. Loopback only, per-session token, origin check, no CORS wildcard. Remote access is out of
   scope for core and must come through Hermes's own authenticated dashboard or gateway.
8. Fail closed. On policy, signature or audit failure the affected module stops; the core keeps running.
9. Untrusted text. Content from tools, web pages, repositories and model output is data. No module may execute
   instructions found in it, and connectors label such content before it reaches a model.

**Threats considered:** malicious or compromised module, poisoned upstream repository, prompt injection through
tool output, secret exfiltration through logs or model context, runaway spend, quota exhaustion, local privilege
misuse through the control API, tampered audit trail, dependency confusion.

## 5. Module contract

A module is a directory with `module.toml` (schema: `src/switchyard/schemas/module.schema.json`), an entry class and tests.
Template: `templates/module/`.

| A module may contribute | Through |
|---|---|
| Capability (router, connector, scanner, ...) | Entry class methods and event subscriptions |
| Hermes tools, slash commands, CLI commands | `contributes.tools`, `contributes.commands` |
| Hermes hooks | `contributes.hooks` (names must exist in Hermes `VALID_HOOKS`) |
| Dashboard panels and settings forms | `contributes.panels` |
| Security rules that tighten policy | `contributes.policies` (a module can restrict, never widen, its own grant) |
| Triggers and schedules | `contributes.triggers` |
| Log and metric streams, report sections | `contributes.log_streams` |
| Update source | `[update]` |

Lifecycle states: `verified -> active <-> stopped`, with `failed` reachable from any step. A module is loaded
and activated only when every capability it requests (except those marked optional) is granted; until then
activation is refused with `policy.denied` and no module code runs (H1 A-5; there is no separate `granted`
state). Activation mode is `manual`, `auto` or `disabled`; the model may start only `auto` modules (H1 C-6). `idle_stop_seconds` stops an auto module that is not in use, which is how token
and resource use stays low.

Required entry methods: `activate(ctx)`, `deactivate()`, `health()`. Required tests: manifest validity,
activate and deactivate without leaks, denied-capability behaviour, and one test per contributed tool.

## 6. Hermes integration (verified names)

| Need | Hermes mechanism |
|---|---|
| Package and config | `plugin.yaml` with `manifest_version: 2`, `provides_hooks`, `config_schema` |
| Tools, commands | `register_tool`, `register_command`, `register_cli_command` |
| Per-turn routing and context trimming | hooks `pre_llm_call`, `pre_api_request`, `post_api_request`, `api_request_error`, `transform_api_error_classification` |
| Tool output reduction | hooks `transform_tool_result`, `transform_terminal_output` |
| Tool guard rails | hooks `pre_tool_call`, `post_tool_call`, `pre_approval_request` |
| Session and sub-agent tracking | hooks `on_session_start`, `on_session_end`, `subagent_start`, `subagent_stop`, `on_skill_lifecycle`, `post_compaction` |
| Sub-agent model assignment | `register_delegation_provider` |
| Secrets into Hermes | `register_secret_source`, `register_redaction_patterns` |
| Background supervisor | `register_idle_task`, Hermes cron (no-agent jobs for deterministic work) |
| Skills shipped by modules | `register_skill` |
| Compaction engines | `register_context_engine` |
| Dashboard tab | dashboard plugin `manifest.json` (`tab`, `entry`, `api`) with a Python `plugin_api.py` |
| Programmatic control | `register_rpc` |

Open items to verify in the relevant module's research step: the `model_switch` tool and per-task model
overrides in `delegate_task` (named in the requirement document, not yet checked in source).

## 7. Data and reporting

- State: `<data_dir>/state.db` (SQLite). Audit: `<data_dir>/audit/*.jsonl`. Config: `<data_dir>/config.toml`.
  `data_dir` defaults to the platform user-data location; inside Hermes it is the plugin data directory.
- Metrics per request: provider, model, pool, tokens in and out, cache hits, latency, cost estimate, outcome.
  No prompt or completion text is stored unless the user turns on a debug stream for a module.
- Reports are generated from the store by deterministic code. Models are used only for optional summaries, on
  the free pool.

## 8. Open source and third-party rules

Project license: Apache-2.0 (explicit patent grant; compatible with the MIT and Apache sources this builds on).

| Reuse class | Licenses | Allowed use |
|---|---|---|
| `vendor-ok` | MIT, BSD, ISC, Apache-2.0, CC0 | Copy or adapt with attribution in `NOTICE` and the SBOM |
| `process-only` | GPL, AGPL, LGPL | Run as a separate program through a connector; never import or copy |
| `reference-only` | No license, unclear, not found | Read for ideas only; write original code |
| `proprietary-connector` | Closed source | Connector only, off by default, user must allow it by name |

## 9. Non-goals

No remote multi-user service, no cloud-hosted secret storage, no bundled model weights, no replacement for
Hermes's own agent loop.
