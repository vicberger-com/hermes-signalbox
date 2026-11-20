# ADR-0009: Notifications and the dashboard tab

Status: accepted, 2026-11-20. Phase: M9. Q&A: [10-m9-prework.md](../qa/10-m9-prework.md) question 10.

## Decision

1. `notify` (`ctx.notify.send(severity, title, detail)`): severity from a fixed list, single-line title (120)
   and detail (500), redacted, audited (`module.notify`), published as `core.notify`. Delivery is not the
   sender's concern.
2. The bundled `inbox` module stores `core.notify` and the bundled alert events for the operator. Listing is
   human-only.
3. `report show {kind}` builds redacted health, usage, security and changes reports from read-only operations.
4. The Hermes adapter starts the loopback control API when `[api] enabled = true`; its responses are redacted.
5. The dashboard tab (`dashboard/`) is plain JS against the Hermes plugin SDK. Its backend (`plugin_api.py`) is
   a proxy with a fixed list of operations to the control API. Grants, installs and config changes are not
   offered in the dashboard.

## Consequences

- No outbound channels yet (webhooks, chat platforms); Hermes's message injection is not an alert channel.
