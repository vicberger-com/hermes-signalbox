# Capabilities

> **Type:** index · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** current

Default deny: a module gets only the capabilities its manifest requests and you grant
(`hermes-signalbox module grant <id> --capability <name>`). Grants are stored, audited and revocable, and removing a
module drops them.

| Capability | Risk | Allows | Requested by |
|---|---|---|---|
| [[Capability core.read]] | medium | Read module states, verify the audit chain, read update checks, and subscribe to core events. | [[Module supervisor]], [[Module inbox]], [[Module updates]] |
| [[Capability fs.read]] | medium | Read files the operator points it at, as bounded JSON or text, through the file broker. | [[Module resources]], [[Module meter]] |
| [[Capability fs.write]] | n/a | Reserved. In the vocabulary but no broker exists in 1.0, so a grant has no effect. | — |
| [[Capability hermes.config.write]] | high | Change allow-listed Hermes config keys (skills.disabled). | [[Module activation]] |
| [[Capability hermes.delegation]] | medium | Route Hermes subagent delegation by role. | [[Module workers]] |
| [[Capability hermes.hooks]] | high | Observe Hermes events (requests, responses, subagents) and register gates and middleware. | [[Module router]], [[Module meter]], [[Module activation]], [[Module workers]] |
| [[Capability hermes.output]] | medium | Shorten terminal and tool output before the model reads it (deletion only). | [[Module trimmer]] |
| [[Capability hermes.tools]] | n/a | Reserved. Modules cannot register Hermes tools in 1.0; a grant has no effect. | — |
| [[Capability llm.free]] | low | Let the router choose free and self-hosted models. | [[Module router]] |
| [[Capability llm.paid]] | high | Let the router or a worker role use paid models, subject to rules and a daily budget. | [[Module router]], [[Module workers]] |
| [[Capability net.outbound]] | high | Make HTTP(S) requests to hosts listed in the module's manifest `net_hosts`. | [[Module offload]] |
| [[Capability notify]] | low | Send operator notifications (to the inbox and dashboard). | [[Module scanner]], [[Module updates]] |
| [[Capability process.spawn]] | high | Run external programs with a fixed argument list. | [[Module secrets]], [[Module scanner]], [[Module offload]] |
| [[Capability schedule]] | low | Run jobs on a timer. | [[Module supervisor]], [[Module workers]], [[Module scanner]], [[Module updates]] |
| [[Capability secrets.read]] | high | Use named secrets the manifest declares, by reference; values are resolved at the point of use. | [[Module secrets]] |
| [[Capability ui.panel]] | low | Show panels and status in the CLI and the dashboard. | [[Module secrets]], [[Module resources]], [[Module router]], [[Module meter]], [[Module activation]], [[Module supervisor]], [[Module workers]], [[Module trimmer]], [[Module inbox]], [[Module scanner]], [[Module offload]], [[Module updates]] |

> **Security:** capability checks bind modules that go through the core. Processes running as your OS user,
> including subprocess modules and a model with a shell, can act outside them. See [[Security model]].

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/src/switchyard/capabilities.py) · [DESIGN.md §4](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/DESIGN.md)
