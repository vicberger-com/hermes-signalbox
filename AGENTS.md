# AGENTS.md: execution contract

You are a Hermes agent building this project. This file plus `docs/` is everything you need. Read
`docs/DESIGN.md`, `docs/BUILD-PLAN.md`, `docs/MODULES.md` and the newest file in `docs/qa/` before acting.

## Executor requirements

- Hermes Agent >= 0.22 connected to a frontier-class model (Opus 5.5 level) for design, security review and
  integration work.
- Tools: terminal, file tools, `delegate_task`, web search, `gh` and `git` with push access to this repository.
- Python >= 3.11, `uv` (or pip), Node only if the M9 Q&A selects a built front end.

## Flow

1. Work phases in the order in `docs/BUILD-PLAN.md`: M0 (core) first, then one module at a time. Never start a
   module before the previous one is merged and tagged.
2. Run continuously. Accept your own recommended option for every decision, record it in the phase Q&A file, and
   keep going. Do not ask the operator to confirm recommendations.
3. Before each phase, write `docs/qa/NN-<phase>-prework.md` from `docs/qa/TEMPLATE-module-prework.md`. Answer every
   question yourself from research and from what earlier phases taught you. Carry forward changed requirements.
4. Research at every phase start and before adopting any dependency: current upstream state, license, security
   advisories, Hermes API changes. Cite sources in the Q&A file. Never rely on memory for versions, APIs or
   licenses.
5. Every change lands by pull request with green CI. One module is one or more PRs, never a direct push to `main`.

## Stop conditions (the only reasons to pause)

Stop, write the blocker to `docs/qa/BLOCKERS.md`, and tell the operator exactly what manual action is needed:

- A secret must be entered, created or rotated. You never type, read back, print or store a secret value.
- Money would be spent, or a paid resource would be enabled.
- An action is destructive outside this repository or its own data directory.
- A GitHub setting only the owner can change (visibility, branch protection, token scope).
- A license conflict has no compliant alternative.
- CI stays red after three distinct fix attempts, or a security gate fails and the fix needs a design change that
  contradicts `docs/DESIGN.md`.

While blocked on one item, continue any work that does not depend on it.

## Cost discipline

Use the cheapest capable resource: scripts and CI for anything deterministic; `delegate_task` on the free or fast
route for search, extraction, license checks and boilerplate; the main model for architecture, security review,
integration and final verification. Keep context small: read files by range, write findings to files, and pass
subagents only the context they need.

## Non-negotiables

- Priority order: security, utility, open source, speed and capacity, size and clarity.
- No secret values in the repository, logs, issues, PRs, test fixtures or prompts.
- No code copied from a source whose license class in `docs/THIRD-PARTY.md` is `reference-only`.
- Tests are written before implementation. Report only what real execution returned.
- Trust but validate ([ADR-0016](docs/adr/0016-trust-but-validate.md)). Completed actions are not passed, they
  are performed: an acceptance item names the test that was run or the surface that was looked at; a review says
  what was executed and what was only read. Every function ships with the operator's means to see that it was
  done, check that it was done right, and correct it: configuration in effect, controls, status, results, log.
- Every release ships an SBOM and updated docs. Every dependency is pinned and recorded.
