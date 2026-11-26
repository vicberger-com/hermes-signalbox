# ADR-0009: Notifications and the dashboard tab

Status: accepted, 2026-11-20. Phase: M9. Q&A: [10-m9-prework.md](../qa/10-m9-prework.md) question 10.

## Decision

1. `notify` (`ctx.notify.send(severity, title, detail)`): severity from a fixed list, single-line title (120)
   and detail (500), redacted, audited (`module.notify`), published as `core.notify`. Delivery is not the
   sender's concern.
2. The bundled `inbox` module stores `core.notify` and the bundled alert events for the operator. Listing is
   human-only.
3. `report show {kind}` builds redacted health, usage, security and changes reports from read-only operations.
4. The Hermes adapter starts the loopback control API when `[api] enabled = true`, with the **dashboard
   profile**: only the dashboard's operations, the inbox actions, and other module actions with the model's
   rights. Responses and error messages are redacted. `switchyard serve` keeps the full profile for the CLI.
   Module ids `core`, `hermes`, `api`, `cli`, `switchyard`, `dashboard` are reserved.
5. The dashboard tab (`dashboard/`) is plain JS against the Hermes plugin SDK. Its backend (`plugin_api.py`) is
   a proxy with a fixed list of operations to the control API. Grants, installs and config changes are not
   offered in the dashboard. Its writes sit behind Hermes's dashboard auth (session header, or `SameSite=Lax`
   cookies with a `Sec-Fetch-Site` check) and also refuse a write the browser marks as another page's
   (1.1, H1 C-18).

## Amendment (1.1.0, H5): presentation layer

6. Human surfaces do not show operation payloads. `hermes_signalbox.labels` is the single source for what a
   capability, status, mode, severity, actor or core audit action is called and means;
   `hermes_signalbox.present` turns an operation result into Markdown (chat) or plain text (CLI): summary
   first, labels instead of ids, local times, a next step. Both are pure functions with no state access.
7. Payloads are the machine contract and do not change for presentation: `--json`, `json=true` and the model
   tools return them as before. Module descriptions shown in tables are read from the manifests by the
   surface, not added to `module list`.
8. Each report kind has a stated purpose and a deterministic `summary` (`headline`, `counts`, `lines`) in its
   payload, so every surface shows the same sentence and none recomputes it.
9. The dashboard profile also serves `module mode` (`POST /modules/{id}/mode` in the dashboard backend, behind
   the same write guard as activate and deactivate; audited `module.mode_changed`, actor `api`). A mode cannot
   widen what a module may do: `disabled` only stops it and `auto` starts nothing that lacks a grant. Grants,
   installs, updates, removal and config stay off the dashboard. `GET /labels` serves the label tables; it is
   static and makes no call to the core.

## Consequences

- No outbound channels yet (webhooks, chat platforms); Hermes's message injection is not an alert channel.
