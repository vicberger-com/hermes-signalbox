# Pre-work Q&A: M11 offload connectors

Date: 2026-11-20. Previous phase: M10, tag v0.11.0.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| M10 retro | External programs: files not pipes, tree kill, capped output | Agent CLIs run through the same broker |
| M9 retro | Enforce allow-lists in the server, not the client | Data-sent declarations are enforced in the module before anything leaves |
| M0 | `net.outbound` was a declared capability with a manifest host list but no broker | ADR-0010 adds the broker |

## 2. Research record

| Connector | License class | Transport | Notes |
|---|---|---|---|
| JevK5 | local (operator's own model) | HTTP POST `127.0.0.1:8090/v1/systemone` `{state, questions, kind?}` | `jevk5-decisions` skill; refuses browser `Origin`; localhost only |
| n8n | source-available (Sustainable Use License, fair-code) | HTTP webhook on this machine | Webhook paths act as credentials: never displayed or audited |
| Claude Code | proprietary | CLI print mode `claude -p --output-format text`, prompt on stdin | Uses the operator's logged-in account |
| Codex | proprietary | CLI `codex exec -`, prompt on stdin | Same |
| ACP (JSON-RPC over stdio) | | | Full ACP sessions deferred: print/exec modes cover one-shot offload without a session protocol |
| References | marlandoj/zouroboros-swarm-executors (no license: reference only), h4dex/opc-nexus; Rainhoole/hermes-agent-acp-skill not found (2026-11-19, replaced by CLI modes) | | Nothing copied |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Smallest scope? | | One `offload` module, four connectors, human-only `run`, read-only `connectors` and `report`; core `net.outbound` broker | default accepted |
| 2 | Capabilities | | `net.outbound` (manifest hosts `127.0.0.1`, `localhost`), `process.spawn` (optional), `ui.panel` | default accepted |
| 3 | Remote hosts? | (a) loopback only; (b) operator-added hosts | (a). The manifest host list is static and reviewed; remote n8n needs an operator-approved host mechanism (later ADR) | default accepted |
| 4 | New dependencies? | | None | default accepted |
| 5 | Security | | Threat table below | default accepted |
| 6 | State | | In-memory run counts only | default accepted |
| 7 | Who can offload | | Operator only (`run` human-only). Model-driven offload belongs to routing (M7) and is not added here | default accepted |
| 8 | Default enablement | | Open and local connectors on; source-available and proprietary off until named in `allow` | default accepted |
| 9 | Core contract change? | | ADR-0010 | default accepted |
| 10 | Live verification | | Tests use local fakes; live runs against the operator's JevK5, n8n and agent CLIs are an operator step (QUESTIONS.md Q-SY-M11) | default accepted |

### Threats and tests (question 5)

| Threat | Control | Test |
|---|---|---|
| Data beyond what a connector declares leaves the machine | Payload fields must be a subset of `sends`; refused before any request; agent CLIs without tools (Claude Code) or read-only sandbox (Codex), in an empty directory | `test_open_connector_and_data_sent_enforced` |
| Proprietary service used without consent | Off until allowed by name | `test_proprietary_connectors_off_until_allowed` |
| Request to an unlisted host, via redirect, or with credentials in the URL | Broker: manifest host list, no redirects, no proxies, no userinfo | `test_net_broker_rules` |
| Payload or webhook id recorded | Audit has connector, field names, host, method and status only; listing shows scheme and host | same, and listing test |
| Huge or hostile answers | Response capped at 4 MB; CLI output capped | `test_net_broker_rules` |
| Model offloads work | `run` is human-only | `test_failures_settings_and_rights` |

## 4. Acceptance tests (written before code)

- [x] Proprietary connectors are off until allowed by name.
- [x] Data-sent declaration is enforced.

## 5. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
| Declaring the fields sent bounds what leaves | An agent CLI with tools can read and send anything; the declaration needs the agent's own tool limits | Agent connectors |
| A socket timeout bounds a request | It bounds each read; a total deadline is separate | Network broker |

