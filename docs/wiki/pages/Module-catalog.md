# Module catalog

> **Type:** index · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** current

The twelve bundled modules. All run in-process and are reviewed in this repository; modules you install from
git run as subprocesses. A module does nothing until you grant its capabilities; `auto` modules then start with
every hosting process, `manual` ones when you activate them.

| Module | Phase | Activation | What it does |
|---|---|---|---|
| [[Module secrets]] | M1 | auto | Secret backends (OS stores, Vaultwarden, development env), age and expiry by name, rotation. |
| [[Module resources]] | M2 | auto | Catalog of providers, models, endpoints, agents and tools; pools; consumer bindings; reviewed imports. |
| [[Module router]] | M3 | auto | Picks the model for each Hermes request from the registry: free first, paid only by rule and budget, failover with cool-down. |
| [[Module meter]] | M4 | auto | Counts every Hermes API response by day, provider and model; quotas with once-per-period thresholds; burn-rate forecast. |
| [[Module activation]] | M5 | auto | Skill inventory with prompt cost, presets, index-size benchmark, timed presets; every config change backed up and reversible. |
| [[Module supervisor]] | M6 | auto | Scheduled deterministic checks (failed modules, audit chain, quotas, ruled-out models); de-duplicated findings and alerts; no LLM calls. |
| [[Module workers]] | M7 | auto | Worker roles and teams for Hermes delegation: each role routes to its own model pool or Hermes profile; a ledger of spawned work, stuck and loop detection. |
| [[Module trimmer]] | M8 | manual | Shortens long terminal and tool output before it reaches the model: repeated lines, noisy middles; errors, exit codes and paths are always kept. |
| [[Module inbox]] | M9 | auto | Collects operator notifications and alerts (supervisor, meter, workers, failed modules) for the dashboard; nothing leaves the machine. |
| [[Module scanner]] | M10 | manual | Runs external security scanners (gitleaks, bandit, pip-audit, osv-scanner, semgrep, trivy) on a schedule; findings to the store, dashboard and alerts; failures are findings too. |
| [[Module offload]] | M11 | manual | Sends suitable work to cheaper local resources: JevK5 typed decisions, n8n flows, and (when allowed by name) agent CLIs. Each connector declares license class, hosts and data sent. |
| [[Module updates]] | M12 | manual | Checks git-installed modules against the head of their update channel on a schedule and announces available updates. It never applies one: preview and update are operator commands. |

---
**Sources:** [MODULES.md](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/MODULES.md) · [module.toml files](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/modules)
