# Hermes Switchyard

A security-first, open-source control plane for [Hermes Agent](https://github.com/NousResearch/hermes-agent):
one small core framework plus snap-on modules that manage skills, plugins, model/resource pools, sub-agents,
token use, security testing, reporting and updates. Hermes can operate 100% of it; so can a human.

**Status:** design + template (v0.0.1, bootstrap complete). No runtime code yet. The build is executed by a Hermes instance
following [AGENTS.md](AGENTS.md).

**Priorities (in order, used to break every tie):** 1 security, 2 utility, 3 open source, 4 speed and capacity,
5 size and code clarity.

## Read in this order

| File | What it is |
|---|---|
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
src/switchyard/schemas/        normative module manifest schema
templates/module/              copy this to start a module
tools/validate_manifest.py     stdlib manifest validator (used in CI)
tests/                         template tests
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
