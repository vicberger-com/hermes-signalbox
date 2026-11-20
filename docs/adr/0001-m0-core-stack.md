# ADR-0001: M0 core stack and storage

Status: accepted, 2026-11-19. Phase: M0. Q&A: [01-m0-prework.md](../qa/01-m0-prework.md).

## Context

`DESIGN.md` section 3 planned PyYAML (to read Hermes config) and httpx or stdlib `urllib` as runtime
dependencies, to be confirmed in M0 research. Research on 2026-11-19 found:

- Inside Hermes the plugin reads its settings through `ctx.get_config`, so the core never parses Hermes YAML.
- The control API is loopback-only; the CLI is its only client. Stdlib `http.server` and `http.client` cover both,
  with known pitfalls (CRLF in `send_header`, unbounded reads) that are cheap to guard against.
- Data-directory resolution, host profiling and manifest validation each fit in under 150 lines of stdlib code.
- Hermes v0.23.2 added `plugins.isolation: host`, which runs a whole third-party plugin in a separate process.
  It does not separate Switchyard modules from each other.

## Decision

1. The core (`src/switchyard`) has **zero runtime dependencies**. Standard library only, Python >= 3.11.
2. State is **one SQLite file** (`<data_dir>/state.db`, WAL). Module tables are prefixed `m_<module_id>__` and are
   created only through `ModuleContext.state`, which validates names and binds parameters.
3. Switchyard keeps **its own T2 subprocess host** (JSON-RPC 2.0 over stdio, length-prefixed frames). Hermes plugin
   isolation is complementary: it isolates Switchyard from Hermes; T2 isolates modules from Switchyard.
4. The core never imports Hermes internals. Only `switchyard.hermes` (the adapter) touches the `ctx` object
   Hermes passes to `register(ctx)`.

## Consequences

- No third-party code in the trusted base; the SBOM for the core is the Python runtime alone.
- Modules that need a library declare it themselves and are reviewed in their own phase.
- If a later phase needs YAML (for example writing Hermes config in M5), the dependency is added to that module,
  not the core, and recorded in that phase's Q&A.
