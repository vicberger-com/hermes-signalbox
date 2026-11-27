# Roadmap — Signalbox (Hermes Control Plane)

**Status**: Planning  
**Current**: v1.1.0, the first release under the name Signalbox.  
**Repository**: vicberger-com/hermes-signalbox

---

## Phase 1: Documentation & Polish (Current Sprint)

**Goal**: New user → working dashboard in <10 min (currently ~45 min)

- [x] **QUICKSTART.md** — 5-minute zero-to-dashboard path
- [x] **TROUBLESHOOTING.md** — 15+ common issues with Symptom→Cause→Fix
- [x] **README.md** — Links to QUICKSTART, TROUBLESHOOTING, grants table
- [x] **Module descriptions in dashboard** — One-line summary per module (v1.1.0, #210)
- [x] **Tooltips and legend** — State and start mode explained on hover and keyboard focus; disabled buttons say why (v1.1.0, #206, #208)
- [x] **Module version display** — Installed version, source and the last known update state (v1.1.0, #210). The page never checks for updates itself: that needs the `updates` module

---

## Phase 2: Operational Improvements (Next Sprint)

**First: operator validation surfaces (H6, v1.2.0).** A screen per module with its configuration in effect, controls, status, results and log, and the same at the command line and in chat ([ADR-0016](adr/0016-trust-but-validate.md), [gap analysis](qa/20-validation-gap.md)). Today every module registers a status panel and the dashboard displays none of them.

**Goal**: Zero "module stuck verified" support requests; grants self-service

| Enhancement | Description | Module(s) |
|-------------|-------------|-----------|
| **Grant wizard** | First-run interactive prompt: "Grant all required capabilities for all modules?" (#221). Done in v1.1.0: a start-up notice names each module that is waiting and the command to run | Core |
| **Auto-activate on grant** | When last missing grant given, auto-start `auto` modules (no restart needed) | Core |
| **Unified data directory** | Default `SIGNALBOX_DATA_DIR` to Hermes plugin data dir when installed as plugin | Core |
| **Dashboard module cards** | Version, description, start/stop and start mode are done in v1.1.0. Still open: granting from the page (today a deliberate limit: grants stay at the terminal or in chat) | Dashboard |
| **Live health endpoint** | `/signalbox module health <id>` in dashboard with auto-refresh | All |

---

## Phase 3: Feature Enhancements (Following Sprints)

| Enhancement | Description | Module(s) | Value |
|-------------|-------------|-----------|-------|
| **Skill cost presets** | One-click "coding"/"research"/"idle" presets that enable/disable skills | activation | Token savings |
| **Budget enforcement** | Hard stop when paid quota exhausted; notify + disable paid routing | meter + router | Cost control |
| **Secret rotation scheduler** | Cron-based rotation with expiry alerts | secrets | Security hygiene |
| **Scanner findings UI** | Dashboard panel with severity filter, acknowledgment, export | scanner | Vuln management |
| **Offload connector marketplace** | Discover/install n8n/JevK5/ACP connectors from catalog | offload | Extensibility |
| **Worker team templates** | Pre-built role/team configs (code-review, research, testing) | workers | Faster delegation |
| **Update channel UI** | Visual diff, SBOM delta, one-click update/rollback in dashboard | updates | Safe updates |
| **Resource pool cost optimizer** | Auto-rebalance pools based on real usage/cost | resources | Efficiency |
| **Supervisor custom checks** | User-defined deterministic checks (disk, memory, custom scripts) | supervisor | Flexibility |

---

## Phase 4: Architecture & Scale (Future)

| Enhancement | Description |
|-------------|-------------|
| **Stronger isolation for third-party modules** | Subprocess isolation exists since 1.0 (`isolation = "subprocess"`). Open: running those processes under a restricted OS account (#68) |
| **Multi-profile support** | Signalbox data per Hermes profile (currently single data dir) |
| **Remote dashboard auth** | OAuth/OIDC for dashboard API (currently loopback only) |
| **Module marketplace** | Signed module registry with dependency resolution |
| **WASM module support** | Sandbox modules in WebAssembly |

---

## Dependencies & Risks

| Risk | Mitigation |
|------|------------|
| Hermes plugin API changes | Pin Hermes version in CI; integration tests per release |
| Grant model confusion | QUICKSTART + TROUBLESHOOTING + first-run wizard |
| Dashboard React ↔ Python sync | Shared TypeScript/Python types from module manifests |
| Security audit scope | Each phase has dedicated Q&A in docs/qa/ |

---

## Success Metrics

- [ ] Fresh user → working dashboard in <10 min (currently ~45 min)
- [ ] Zero "module stuck verified" support requests
- [ ] All 12 modules have dashboard panels with controls
- [ ] Update/rollback success rate > 99%
- [ ] Dashboard accessibility + keyboard checks pass

---

## Related Issues

- #205 — Readable chat replies and command-line text (closed, v1.1.0)
- #206 — Modules view: silent failures, unexplained values (closed, v1.1.0)
- #207 — Reports view readable; Refresh gives feedback (closed, v1.1.0)
- #208 — Self-explaining page and glossary (closed, v1.1.0)
- #210 — Module description, version, source and update state (closed, v1.1.0)
- #221 — Grant requirements: documentation done; a start-up notice and first-run prompt are open
- #212 — Rename to Signalbox (merged)

---

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for coding, Git, documentation, and SBOM standards.  
Each phase has pre-work Q&A in `docs/qa/` — review before starting.