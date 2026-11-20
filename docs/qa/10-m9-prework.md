# Pre-work Q&A: M9 dashboard, reporting and notifications

Date: 2026-11-20. Previous phase: M8, tag v0.9.0.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| M6-M8 retros | Module-written text must not reach the model | Notification text is for the operator: the inbox list is human-only |
| M6 | Alerts were events and audit records only, delivery deferred to M8/M9 | The inbox collects them; the dashboard shows them |
| M0 | Loopback control API exists (`[api] enabled`), was only started by `switchyard serve` | The Hermes adapter starts it when enabled; the dashboard backend proxies to it |

## 2. Research record

| Topic | Source (Hermes v0.23.2, 2026-11-20) | Finding |
|---|---|---|
| Dashboard tab | `plugins/hermes-achievements/dashboard/`, `hermes_cli/web_routers/dashboard_ui.py` 400-440 | `dashboard/manifest.json` (name, label, tab path, `entry` JS, `css`, `api`); the JS registers with `window.__HERMES_PLUGINS__.register(name, Component)` using `window.__HERMES_PLUGIN_SDK__` (React, `fetchJSON`, components). Static assets are served **unauthenticated** by suffix allow-list, so they must hold no data |
| Dashboard backend | `hermes_cli/web_server_dashboard.py` 927-1050 | `plugin_api.py` exports a FastAPI `router` mounted at `/api/plugins/<name>/`, behind dashboard auth and the plugin-consent gate; may run in the dashboard process, not the agent process |
| Gateway alert channels | `plugins_context.py` 397-420 (M6 research) | `inject_message` feeds text to the model: not an alert channel. Deferred |
| References | Diabloluo/hermes-hud, Kori-x/hermes-dashboard, outsourc-e/hermes-workspace | Layout ideas; nothing copied |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Smallest scope? | | One dashboard tab (modules with state, health and activate/deactivate; inbox; reports), core `notify` capability, bundled `inbox` module, `report show` operation. Outbound webhooks and gateway channels deferred | default accepted |
| 2 | Capabilities | | New broker for existing `notify`; inbox requests only `ui.panel`. No `net.outbound`, no `fs.read` | default accepted |
| 3 | Reuse, adapt or write? | | Write (plain JS, no build step, no npm dependencies) | default accepted |
| 4 | New dependencies? | | None in Switchyard; the backend imports Hermes's FastAPI lazily | default accepted |
| 5 | Security | | Threat table below | default accepted |
| 6 | State; uninstall | | Inbox table `items` (last 1000, acknowledged first to go). Removed with the module unless `keep_data` | default accepted |
| 7 | Control surface | | Dashboard: module list and show, panels, activate/deactivate, reports, inbox list/ack. Grants, installs and config stay CLI-only | default accepted |
| 8 | Where the backend gets data | (a) proxy to the loopback control API; (b) open the state database directly | (a): one code path with its auth, validation, audit and redaction; works when the dashboard runs in another process | default accepted |
| 9 | Report kinds | | health, usage, security, changes; redacted; built from read-only operations | default accepted |
| 10 | Core contract change? | | ADR-0009 | default accepted |
| 11 | Operator input? | | Set `[api] enabled = true` to use the tab (documented) | default accepted |

### Threats and tests (question 5)

| Threat | Control | Test |
|---|---|---|
| Panel or report shows a secret value | API responses redacted; reports redacted; notify redacts | `test_notify_reaches_the_inbox_redacted_and_bounded`, `test_reports` |
| Unauthenticated access | Backend only under Hermes dashboard auth; static bundle holds no data; control API token on disk, loopback only | `test_dashboard_bundle_is_accessible_and_local` |
| Outbound telemetry | Bundle has no external URLs and only uses the SDK's fetch to its own routes | same |
| Dashboard escalates privileges | The API Hermes starts uses the dashboard profile (fixed operations, enforced in the server, not only in the proxy); no grants, installs or config | `test_dashboard_api_profile_refuses_privileged_ops`, `test_dashboard_backend_proxy` |
| Path or parameter injection | Module ids, panel names and inbox ids validated before use | same |
| Model reads module-written notification text | Inbox `list` is human-only | `test_alert_events_min_severity_ack_and_bounds` |
| Notification flood | Fields capped and single-line; inbox capped at 1000 | same |

## 4. Acceptance tests (written before code)

- [x] Every module visible with state, health and controls (`test_dashboard_backend_proxy`, `Modules` view).
- [x] No outbound telemetry (`test_dashboard_bundle_is_accessible_and_local`).
- [x] Panel code has no access to secret values (redaction at the API; no secret routes).
- [x] Accessibility and keyboard checks (static checks: buttons for every action, tablist/tab roles,
  `aria-selected`, live status region, table caption and header scopes, labelled select, visible focus).

## 5. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
| An allow-list in the client is enough | Anything that can read the token can call the server directly: enforce the allow-list in the server | Every local API |
| Oldest-first pruning is fair | Floods evict what matters; prune by importance first | Inbox, any bounded alert store |
| Redact after formatting | Caps can split a secret; redact the full text first | Every redacted field |
| `.gitignore` patterns are harmless | `dist/` hid the dashboard bundle from the repository; CI caught it | Shipped static assets |

