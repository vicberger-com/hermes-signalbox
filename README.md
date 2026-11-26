# Hermes Signalbox

(Formerly Switchyard; renamed in 1.1.0. Upgrading: [docs/UPGRADING-1.1.md](docs/UPGRADING-1.1.md).)

A security-first, open-source control plane for [Hermes Agent](https://github.com/NousResearch/hermes-agent):
one small core framework plus snap-on modules that manage skills, plugins, model/resource pools, sub-agents,
token use, security testing, reporting and updates. Hermes can operate 100% of it; so can a human.

**Status:** v1.0.3. The core (module lifecycle with in-process and subprocess hosts, default-deny capabilities,
hash-chained audit log, secrets by reference, CLI, loopback API, Hermes plugin) and twelve bundled modules:
secrets, resource registry and pools, router and failover, metering and quotas, skill activation, supervisor,
workers, output trimming, dashboard and inbox, security scanners, offload connectors, and module updates. Built
by a Hermes instance following [AGENTS.md](AGENTS.md); every phase had a fresh security review (results in each
module README and `docs/qa/`).

Start with the [user guide](docs/USER-GUIDE.md). Install by owner/repository and commit
(`hermes plugins install vicberger-com/hermes-signalbox --ref <SHA>`).

**Priorities (in order, used to break every tie):** 1 security, 2 utility, 3 open source, 4 speed and capacity,
5 size and code clarity.

## Read in this order

| File | What it is |
|---|---|
| [docs/USER-GUIDE.md](docs/USER-GUIDE.md) | Install, first run, grants, activation, dashboard, updates, uninstall |
| [docs/REFERENCE.md](docs/REFERENCE.md) | Every operation, tool, core setting, audit action and event |
| [docs/wiki/README.md](docs/wiki/README.md) | Wiki framework: structure, page types, templates, publishing |
| [AGENTS.md](AGENTS.md) | Execution contract for the building agent: flow, auto-accept rule, stop conditions |
| [docs/DESIGN.md](docs/DESIGN.md) | Architecture, trust model, module contract, Hermes integration points |
| [docs/BUILD-PLAN.md](docs/BUILD-PLAN.md) | Phase order, per-module loop, gates, definition of done |
| [docs/MODULES.md](docs/MODULES.md) | Core (M0) and modules M1 to M12: scope, sources to reuse, acceptance |
| [docs/qa/00-pre-engagement.md](docs/qa/00-pre-engagement.md) | Pre-engagement Q&A with accepted defaults |
| [docs/THIRD-PARTY.md](docs/THIRD-PARTY.md) | Candidate upstream sources, verified licenses, reuse class |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Coding, Git, documentation and SBOM standards |
| [SECURITY.md](SECURITY.md) | Reporting and the security baseline |

## Layout

```
src/hermes_signalbox/                core, Hermes adapter, bundled modules (src/hermes_signalbox/modules/<id>/README.md)
src/hermes_signalbox/schemas/        normative module manifest schema
dashboard/                     Hermes dashboard tab
templates/module/              copy this to start a module
tools/validate_manifest.py     stdlib manifest validator (used in CI)
tests/                         core, module and acceptance tests
docs/qa/                       Q&A records, one file per phase
.github/                       CI, security scans, release, Dependabot, templates
```

## Quick check

```bash
python tools/validate_manifest.py templates/module/module.toml
python -m pytest -q
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Third-party reuse rules are in
[docs/THIRD-PARTY.md](docs/THIRD-PARTY.md).
