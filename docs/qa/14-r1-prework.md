# Pre-work Q&A: R1 hardening review, docs pass, public release

Date: 2026-11-20. Previous phase: M12, tag v0.13.0.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| M0-M12 | Each phase had a fresh-subagent review of its own diff | R1 reviews across phases: trust boundary, Hermes integration, bundled modules M1-M7 (M8-M12 were reviewed last and recently) |
| M8 | Replacing the Hermes compaction engine was deferred "to its own ADR before R1" | ADR-0012 records the decision |
| P0 / Q-GH-2 | Repository security settings were planned for P0 | Checked now; still off (BLOCKERS B-R1-1) |

## 2. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Hardening review scope | (a) whole codebase in three areas plus a docs audit; (b) only changed code | (a): cross-cutting weaknesses are what per-phase reviews miss | default accepted |
| 2 | Compaction engine | (a) defer past 1.0 (ADR-0012); (b) build now | (a): Hermes owns compaction; replacing it changes what the model remembers and needs its own design and measurements. Output trimming (M8) already covers the measured savings | default accepted |
| 3 | Release signing | (a) build provenance attestations, SHA256SUMS and SBOM (existing release workflow); (b) also sign tags | (a). Tag signing needs a signing key, which is a secret the operator would have to create; can be added later without changing anything else | default accepted |
| 4 | CodeQL | (a) GitHub default setup; (b) advanced workflow | (a): already on; an advanced job is rejected while default setup is enabled | default accepted |
| 5 | Supported versions after 1.0 | | Latest minor of 1.x receives security fixes | default accepted |
| 6 | Docs pass | | Gap list from an audit against the "Docs" gate; user guide `docs/USER-GUIDE.md` covering install, first run, grants, activation, dashboard, updates, uninstall | default accepted |
| 7 | Live checks still open | | Q-SY-M11 (offload connectors against real services) stays an operator step, recorded as a known limitation | default accepted |
| 8 | Repository settings | | Blocker B-R1-1: only the v1.0.0 tag waits | blocked (operator) |

## 3. Hardening review (2026-11-20)

Three fresh subagents reviewed the whole codebase by area (core trust boundary; Hermes integration; bundled
modules M1-M7) with probes; a fourth audited documentation coverage. M8-M12 had just been reviewed per phase.

| Finding | Disposition |
|---|---|
| (high) T2 modules run as the same user: they can write grants in `state.db`, read `api.token`, open sockets | **Accepted, documented** (DESIGN section 4 "same-user boundary", SECURITY.md). No in-process fix exists while the child can read every file the core can; OS confinement is future work |
| (high) A model with a shell can read `api.token` and use the dashboard API (inbox acks, activate/deactivate) | **Accepted, documented** (same boundary: such a model can also run `switchyard`). Model *tools* are restricted in the core now (below) |
| (high) Router: after repeated failures an allowed paid model took over uncharged | **Fixed.** Free-first after failures; paid pass-through is counted |
| (medium) Two processes appending forked the audit chain | **Fixed.** OS lock and head re-read per append; anchor never moves back |
| (medium) A detected truncation was forgotten after the next append | **Fixed.** Failure recorded until `audit ack` (operator only) |
| (medium) Module id `ab_` let module `ab` reach its tables; uninstall broke | **Fixed.** Ids cannot end in `_`; authorizer and drop require a valid table name |
| (medium) T2 inbox and log streams unbounded | **Fixed.** 64-frame queue (back-pressure); log streams rotate at 20 MB |
| (medium) T2 RPC timeout was per frame; calls could run forever under core locks | **Fixed.** One deadline per call |
| (medium) Grants survived `remove --keep-data` and reattached to different code | **Fixed.** Removal always drops grants |
| (medium) Model could deactivate the router and disable its hard stop | **Fixed.** `deactivate` removed from model tools; core refuses operator-only ops for the model actor |
| (medium) Non-hosting processes run turns without gates, silently | **Fixed (visibility).** `core.not_hosting` audit record; documented in the user guide |
| (medium) Trimming could drop 401/403/rejected/blocked lines | **Fixed.** Added to the must-keep set |
| (medium) Router budget is not a cap when nothing free exists | **Fixed (counting) and documented.** Pass-through is charged and visible; blocking needs `hard_stop` |
| (medium) Supervisor silent when a safety module stopped | **Fixed.** A module that ran at the last pass and stopped is a finding (high for safety modules) |
| (medium) Import could relabel a paid resource free and keep it `auto` | **Fixed.** Cost changes listed in the preview and demoted to `manual` |
| (medium) Quotas without 100 % never exhausted; cost quotas inert without prices | **Fixed.** 100 always added; cost quotas refused without prices |
| (medium) Secret leak guard matched only the exact value | **Fixed (tripwire).** Case, hex, base64, URL forms and 12-character pieces; documented as a tripwire |
| (low) Any module could subscribe to `*` | **Fixed.** `*` and `core.*` need `core.read` (inbox now requests it) |
| (low) A kept broker facade worked after deactivation or revocation | **Fixed.** Facades re-check on every call |
| (low) Human-only ops were guarded only in the adapter | **Fixed.** `MODEL_OPS` allow-list in `Core.run` |
| (low) Module text reached the model unlabelled | **Fixed.** Module action results wrapped as `untrusted_data` |
| (low) `import_preview` (read-only) replaced the operator's pending import | **Fixed.** Operator only |
| (low) Hard stop ignored an exhausted total quota for unknown models | **Fixed** for the `all` scope |
| (low) Secrets shorter than 4 characters were not redacted | **Fixed.** Refused at use |
| (docs) No user guide; operations, settings, audit actions, events and tools undocumented | **Fixed.** `docs/USER-GUIDE.md`, `docs/REFERENCE.md` |

Changes visible to existing users: grant `core.read` to `inbox`; the model can no longer deactivate modules or
preview imports; `module remove --keep-data` no longer keeps grants; module ids may not end in `_`; every quota
fires at 100 %.

## 4. Acceptance

- [x] Hardening review findings fixed or dispositioned.
- [x] Docs gaps closed; user guide written; links resolve.
- [ ] All gates green; SBOM and provenance attached to the release.
- [ ] B-R1-1 resolved before tagging v1.0.0.

## 5. Retro (fill in after release)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
| Per-phase reviews cover the system | Cross-phase paths (router + resources import + meter thresholds) only showed in a whole-system review | Future major releases: repeat the area review |
| A subprocess is an isolation boundary | Same-user processes can reach every file the core uses | Trust model wording; OS confinement roadmap |

