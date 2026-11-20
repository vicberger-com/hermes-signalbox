# Wiki framework

The GitHub wiki is the reading and operating layer of hermes-switchyard: where people find their way, follow a
task, look up a module or capability, and fix a problem. It does not replace the versioned documents in this
repository. This file defines the structure, the page types and the rules; `templates/` holds one template per
page type; `pages/` holds the wiki source that is published.

## 1. Principles

1. **One source of truth.** Normative content (design, ADRs, module specifications, reference tables, security
   reviews) lives in the repository and is versioned with the code. The wiki summarises and links to it; it
   never restates a rule in different words. If a wiki page and a repository document disagree, the repository
   wins and the wiki page is a bug.
2. **Reviewed like code.** Wiki source lives in `docs/wiki/pages/` and changes by pull request. It is published
   to the GitHub wiki with `tools/wiki_publish.py`. Editing in the GitHub web editor is turned off for everyone
   but maintainers, so the published wiki can be rebuilt from the repository at any time.
3. **Security first, in the text too.** No secret values, tokens, real hostnames of private services or
   personal paths in examples. Every page that tells the reader to grant a capability says what that grant
   allows. Same-user limits are stated where they apply (DESIGN section 4).
4. **Every page says what version it describes** and when it was last checked against that version.
5. **Plain language.** Short sentences, the reader's task first, one idea per paragraph, tables for comparisons,
   real commands in code blocks.

## 2. Audiences and what they come for

| Audience | Comes for | Starts at |
|---|---|---|
| Operator (runs Hermes with Switchyard) | Install, grant, activate, budgets, alerts, updates, recovery | Home → Getting started |
| Evaluator (deciding whether to adopt) | What it does, security model, limits, maturity | Home → Overview, Security model |
| Module author | Contract, capabilities, manifest, testing, review | Home → Building modules |
| Contributor / maintainer | Build process, phases, reviews, release | Home → Project |

## 3. Information architecture

Status at creation (v1.0.0): every page exists. Complete worked examples, one per main type:
`Module-router` (module), `Deploy-Hermes-plugin-on-a-workstation` (deployment), `Release-1.0.0` (release),
`Home`, `Module-catalog`, `Capabilities`, `Decisions`. All other pages are generated skeletons marked
`Status: draft`, with the facts that come straight from manifests and code filled in and `<…>` where prose is
still needed.

Five sections, mirrored in `_Sidebar.md`. Page names are the wiki page titles; the file name is the title with
spaces replaced by `-` (GitHub wiki convention).

| Section | Pages (page type) | Normative source it links to |
|---|---|---|
| **Start** | Home (home), Overview (concept), Getting started (how-to), FAQ (faq), Glossary (glossary) | README, USER-GUIDE |
| **Concepts** | Architecture (concept), Security model (concept), Capabilities (index) + one page per capability (capability), Modules and lifecycle (concept), Audit log (concept), Hosting and processes (concept) | DESIGN, ADR-0001..0012 |
| **Modules** | Module catalog (index) + one page per bundled module (module) | `src/switchyard/modules/<id>/README.md`, `module.toml` |
| **Operate** | Deployment profiles (index) + one page per profile (deployment), runbooks (how-to): grant and activate, set budgets and paid rules, enable the dashboard, update and roll back a module, back up and restore, uninstall, respond to an alert, investigate an audit failure; Troubleshooting (index) + entries (troubleshooting) | USER-GUIDE, REFERENCE |
| **Build and project** | Building a module (how-to), Module contract (concept), Testing a module (how-to), Decisions (index) + one digest per ADR (decision), Roadmap (index → Project board), Releases (release), Contributing (concept) | MODULES, BUILD-PLAN, AGENTS, CONTRIBUTING, docs/adr, docs/qa, CHANGELOG |

Page count at 1.0: about 60 (12 module pages, 16 capability pages, 12 decision digests, 5 deployment profiles,
8 runbooks, and the rest).

## 4. Page types

Each type has a template in `templates/`. Every page starts with the same **page header** and ends with the
same **sources** block.

| Type | Template | Purpose | Required sections |
|---|---|---|---|
| home | `home.md` | Entry point and routing | What it is, start here by audience, status, links |
| concept | `concept.md` | Explain how and why something works | Summary, how it works, why, limits, related |
| how-to | `how-to.md` | One task, start to finish | Goal, before you start, steps, check it worked, undo, related |
| module | `module.md` | One bundled module | Card, what it does, capabilities with reasons, settings, actions, model access, events and audit, security notes, review history |
| capability | `capability.md` | One capability | What it allows, risk, broker and limits, who requests it, granting advice |
| deployment | `deployment.md` | One way to run Switchyard | Fits when, layout, install, configuration, verify, operate, upgrade, remove |
| troubleshooting | `troubleshooting.md` | One symptom | Symptom, cause, fix, prevent |
| decision | `decision.md` | Digest of one ADR | Decision in one paragraph, why, consequences for operators and authors, link |
| release | `release.md` | One release | Highlights, changes you must act on, security, verify the download |
| faq / glossary / index | `faq.md`, `glossary.md`, `index.md` | Lookup | Entries, alphabetical or grouped |

### Page header (all types)

```markdown
> **Type:** module · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** current
```

`Status` is one of `current`, `draft`, `outdated` (fix pending), `historical` (kept for older versions).

### Sources block (all types)

```markdown
---
**Sources:** [DESIGN.md §4](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/DESIGN.md) ·
[ADR-0006](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/adr/0006-schedules-core-view-gates.md)
```

Links to repository files are pinned to the release tag the page applies to, so a page never silently changes
meaning when `main` moves.

## 5. Conventions

| Topic | Rule |
|---|---|
| Titles | Sentence case; module pages `Module <id>`, capability pages `Capability <name>`, decisions `Decision ADR-NNNN`, profiles `Deploy <profile>`. No `:` or `/` in titles: they cannot be file names on Windows |
| Commands | Real, copy-pasteable, with the actual argument order (`switchyard module grant router --capability hermes.hooks`) |
| Placeholders | `<angle brackets>`, never realistic-looking values |
| Model vs operator | Every action table has a "Model may run" column |
| Capabilities | Always linked to their capability page; first mention says what the grant allows |
| Versions | `Applies to` names the oldest release the page is correct for; bump `Last checked` when re-verified |
| Callouts | `> **Security:**` for anything that widens access, `> **Note:**` for everything else; no other callouts |
| Length | A how-to fits on one screen of steps; split longer tasks |

## 6. Lifecycle and ownership

| Event | Wiki work |
|---|---|
| Module added or changed | Update its module page and any capability pages whose "requested by" list changed |
| ADR accepted | Add a decision digest; link it from affected concept pages |
| Release tagged | Add a release page; bump `Applies to`/`Last checked` on pages re-verified; mark changed pages `outdated` until fixed |
| Security review disposition | Module page "Security notes" links the review table; never paste findings that are not yet fixed |
| Backlog item done | Roadmap page links the Project board; no duplicated lists |

Checks before merging a wiki PR: links resolve and headers are present (`python tools/wiki_publish.py --check`, also run in CI), every page has a header and
sources block, no page restates a normative rule without a link.

## 7. Publishing

`python tools/wiki_publish.py --publish <clone>` replaces the pages in a local clone of
`hermes-switchyard.wiki.git` with `docs/wiki/pages/`; a maintainer reviews the diff, commits with the source
commit in the message, and pushes. The GitHub wiki needs one page created in the web interface
before its git repository exists. Restrict wiki editing to collaborators (repository Settings → Features →
Wikis → "Restrict editing to collaborators only").
