# Roadmap — Signalbox (Hermes Control Plane)

**Status**: Planning  
**Current**: v1.0.3 (Switchyard) → v1.1.0 (Signalbox rename merged in #212)  
**Repository**: vicberger-com/hermes-signalbox

---

## Phase 1: Documentation & Polish (Current Sprint)

**Goal**: New user → working dashboard in <10 min (currently ~45 min)

- [x] **QUICKSTART.md** — 5-minute zero-to-dashboard path
- [x] **TROUBLESHOOTING.md** — 15+ common issues with Symptom→Cause→Fix
- [x] **README.md** — Links to QUICKSTART, TROUBLESHOOTING, grants table
- [ ] **Module descriptions in dashboard** — Show one-line summary per module (issue #210)
- [ ] **Hover tooltips** — Status/mode/actions in dashboard (issue #207)
- [ ] **Module version display** — Show installed vs latest in dashboard

---

## Phase 2: Operational Improvements (Next Sprint)

**Goal**: Zero "module stuck verified" support requests; grants self-service

| Enhancement | Description | Module(s) |
|-------------|-------------|-----------|
| **Grant wizard** | First-run interactive prompt: "Grant all required capabilities for all modules?" | Core |
| **Auto-activate on grant** | When last missing grant given, auto-start `auto` modules (no restart needed) | Core |
| **Unified data directory** | Default `SIGNALBOX_DATA_DIR` to Hermes plugin data dir when installed as plugin | Core |
| **Dashboard module cards** | Show version, description, one-click grant/activate per module | Dashboard |
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
| **Subprocess isolation (T2)** | Run third-party modules in separate processes with JSON-RPC |
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

- #205 — Module descriptions in dashboard
- #207 — Dashboard accessibility (hover tooltips, clickable indicators)
- #208 — Glossary for status/mode/action terms
- #210 — Module version display
- #212 — Rename to Signalbox (merged)

---

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for coding, Git, documentation, and SBOM standards.  
Each phase has pre-work Q&A in `docs/qa/` — review before starting.