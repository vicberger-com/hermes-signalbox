# Modules

Each section is the starting scope. The phase's research and pre-work Q&A refine it into `docs/modules/<id>.md`.
"Sources" lists upstream projects to study or reuse; the reuse class for each is in
[THIRD-PARTY.md](THIRD-PARTY.md). Capabilities use the names in `src/hermes_signalbox/schemas/module.schema.json`.

## M0 core

See [DESIGN.md](DESIGN.md) section 3 and [BUILD-PLAN.md](BUILD-PLAN.md). Acceptance: example module loads,
is denied an ungranted capability, is audited, survives update and rollback, and is controllable from the CLI,
the API and a Hermes tool.

## M1 secrets

- **Does:** one store for tokens, API keys and passwords. Backends: Vaultwarden through the `bw` CLI, OS keyring
  (Windows Credential Manager and DPAPI, macOS Keychain, Secret Service), environment variables for development
  only. Resolves `secret://name`, rotates on request, reports age and expiry by name.
- **Hermes:** `register_secret_source`, `register_redaction_patterns`.
- **Capabilities:** `secrets.read`, `process.spawn` (for `bw`), `ui.panel`.
- **Sources:** keyring library (verify license in research), Hermes vault conventions.
- **Acceptance:** a value never appears in any tool result, log, audit record or exception; a locked backend
  fails closed; rotation is audited by name.

## M2 resource registry and pools

- **Does:** catalog of providers, models, local endpoints, agents and tools with attachment controls. Each
  resource has state (manual, auto, disabled), cost class (free, paid, self-hosted), capability tags, limits and
  priority. Pools group resources; consumers (main agent, a sub-agent, a function) are bound to pools.
- **Hermes:** reads provider config and the models.dev cache; tool `signalbox_resources`.
- **Capabilities:** `fs.read`, `net.outbound` (catalog refresh hosts only), `ui.panel`.
- **Sources:** mnfst/awesome-free-llm-apis (CC0 data), open-free-llm-api/awesome-freellm-apis,
  mvalentsev/awesome-free-ai-coding, ClawLabsAI/free-ai-models.
- **Acceptance:** import, filter, prioritize, pool and bind resources; catalog refresh is signed-source or
  reviewed-diff only; nothing new is enabled without a user grant.

## M3 router and failover

- **Does:** picks a resource per request from the consumer's pool by task tier (T1 to T5), capability and
  health. Free first. Paid resources are used only when a gating rule matches (tier, complexity, context size,
  retries exhausted, explicit pin) and budget remains. Fails over on rate limit, quota, error or latency.
  Optional upstream gateways are treated as single resources.
- **Hermes:** hooks `pre_llm_call`, `pre_api_request`, `api_request_error`,
  `transform_api_error_classification`; commands for pin and auto; `register_delegation_provider`.
- **Capabilities:** `hermes.hooks`, `hermes.tools`, `llm.free`, `llm.paid` (gated), `net.outbound`.
- **Sources:** open-world-project/model-router, Waylish/hermes-smart-model-routing, Zelray/hermes-model-router,
  Shaf2665/Hermes-router, 0xzr/freellmpool; gateways as external processes: tashfeenahmed/freellmapi,
  cheaper-inference/OmniRoute, decolua/9router.
- **Acceptance:** deterministic routing tests per tier; paid never used without a matching rule and budget;
  failover within a bounded number of attempts; every paid decision audited.

## M4 metering, quotas and budgets

- **Does:** per-request accounting, per-key quota tracking, budget and threshold rules, exhaustion prediction,
  events that M3 and M6 act on.
- **Hermes:** hooks `post_api_request`, `post_llm_call`, `subagent_stop`.
- **Capabilities:** `hermes.hooks`, `ui.panel`.
- **Sources:** Hiutaky/token-saver (MIT). WolfMark-Ltd/spendsense is GPL-3.0: process-only, do not copy.
- **Acceptance:** totals match provider-reported usage within a stated tolerance; threshold events fire once;
  no prompt text stored by default.

## M5 skill and plugin activation manager

- **Does:** inventory of installed skills and plugins with token cost of each; presets ("coding", "research",
  "idle"); turns items on for a task and off after idle; progressive disclosure of skill descriptions.
- **Hermes:** `on_skill_lifecycle`, `pre_llm_call`, skills and plugins CLI, `register_skill`.
- **Capabilities:** `hermes.config.write`, `hermes.hooks`, `fs.read`, `ui.panel`.
- **Sources:** willingning-coder/eagle-eye, freehul/progressive-skill, jiangyuxue666/skill-auto-maintain,
  Kori-x/hermes-dashboard.
- **Acceptance:** measured prompt-size reduction on a fixed benchmark; every config write is backed up, audited
  and reversible; a failed change rolls back.

## M6 supervisor

- **Does:** continuous background manager for control, configuration, monitoring and reporting. Deterministic
  checks first; a model only when judgement is needed, and only from the free pool.
- **Hermes:** `register_idle_task`, cron no-agent jobs, `inject_message` for operator alerts.
- **Capabilities:** `schedule`, `llm.free`, `notify`. Policy forbids `llm.paid` for this module id.
- **Sources:** JerryLiu369/hermes-proactive-agent (repository moved; resolve in research), 42-evey/hermes-plugins.
- **Acceptance:** runs for a soak period within a fixed resource budget; zero paid calls; recovers after restart.

## M7 workers, personas and teams

- **Does:** defines worker roles and teams, binds each to a pool and tool set, tracks spawned work in a ledger,
  stops stuck workers, verifies results before reporting.
- **Hermes:** `subagent_start`, `subagent_stop`, `register_delegation_provider`, kanban hooks.
- **Capabilities:** `hermes.hooks`, `hermes.tools`, `llm.free`, `llm.paid` (gated).
- **Sources:** BkashJEE/hermes-bot-forge, UmLyrithyreach/orchestrator, mattpocock/skills, kerpopule/hermes-jev-skills.
- **Acceptance:** per-role model binding honoured; ledger survives restart; loop detection test.

## M8 token economy

- **Does:** trims tool and terminal output, plugs in compaction engines, keeps task state in files across
  compaction.
- **Hermes:** `transform_tool_result`, `transform_terminal_output`, `register_context_engine`, `post_compaction`.
- **Capabilities:** `hermes.hooks`, `process.spawn` (optional external reducers).
- **Sources:** ogallotti/rtk-hermes, vincentkoc/tokenjuice, danbiocchi/hermes-vcc-engine (Apache-2.0),
  OthmanAdi/planning-with-files, ChrisLamDev/hermes-core-skills.
- **Acceptance:** reduction measured on recorded fixtures; errors, exit codes and paths are never dropped.

## M9 dashboard, reporting and notifications

- **Does:** one dashboard tab that hosts every module's panel; reports (usage, cost, health, security, changes);
  alert rules and channels; input and output controls per module.
- **Hermes:** dashboard plugin manifest and `plugin_api.py`; gateway channels for alerts; outbound webhooks.
- **Capabilities:** `ui.panel`, `notify`, `fs.read`.
- **Sources:** Diabloluo/hermes-hud, Kori-x/hermes-dashboard, outsourc-e/hermes-workspace.
- **Acceptance:** every module visible with state, health and controls; no outbound telemetry; panel code has no
  access to secret values; accessibility and keyboard checks pass.

## M10 security testing connectors

- **Does:** attaches scanners and runs them on schedule or on change: secrets (gitleaks), dependencies
  (pip-audit, osv-scanner), static analysis (bandit, semgrep), containers and files (trivy), skills audit.
  Findings go to the store, the dashboard and alerts.
- **Capabilities:** `process.spawn`, `schedule`, `fs.read`, `notify`.
- **Sources:** each scanner's license verified in research; all run as external processes.
- **Acceptance:** seeded-vulnerability fixtures are detected; scanner failure is reported, never silent.

## M11 offload connectors

- **Does:** sends suitable work to cheaper resources: n8n flows, JevK5 typed decisions, external agents over ACP
  (Claude Code, Codex, OpenClaw), other harnesses. Each connector declares license class, hosts and data sent.
- **Capabilities:** `net.outbound`, `process.spawn`, `secrets.read`.
- **Sources:** marlandoj/zouroboros-swarm-executors (no license: reference-only), h4dex/opc-nexus,
  Rainhoole/hermes-agent-acp-skill (not found on 2026-11-19; locate or replace in research).
- **Acceptance:** proprietary connectors are off until allowed by name; data-sent declaration is enforced.

## M12 update and release control for modules

- **Does:** per-module update channels, verification, staged apply, health check, rollback, SBOM delta, patch
  notes; scheduled update checks.
- **Capabilities:** `net.outbound` (declared sources), `fs.write`, `schedule`.
- **Acceptance:** tampered update rejected; failed health check rolls back; SBOM delta produced for each update.
