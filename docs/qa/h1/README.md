# H1 review material

Phase H1 follows an evaluation of v1.0.0 carried out on 2026-11-20: four read-only reviews (A core trust layer,
B process, network and API boundary, C Hermes adapter and bundled modules, D engineering practice and
operations), each with probes run in a scratch directory against commit `a141ec0`.

| File | Content |
|---|---|
| [findings-index.md](findings-index.md) | Every finding: ID, severity, component, scope class, work package, status |
| [review-D-engineering.md](review-D-engineering.md) | Review D in full: tests, CI, release, packaging, first-run walkthrough, documentation accuracy |

## Totals

102 findings, 101 distinct (C-12 and D-17 are the same item; A-23 was withdrawn by its reviewer and is not
counted): 0 Critical, 5 High, 31 Medium, 51 Low, 15 Info.

## What is not here, and why

Reviews A, B and C describe weaknesses in a released version. Their mechanism, evidence and reproduction
scripts are kept in the maintainer's private record until each fix is merged
([BUILD-PLAN.md](../../BUILD-PLAN.md), "Maintenance phases", rule 5). The index lists them by ID, severity,
component and work package so the scope and progress are visible. When a fix merges:

1. Set the finding's status in `findings-index.md` to `fixed in #<PR>` (or `not reproduced`, `accepted`).
2. Add its disposition row to [15-h1-prework.md](../15-h1-prework.md) section 6.
3. At phase close, reviews A, B and C are added to this folder if every High and Medium item in them is fixed
   or dispositioned.

To report a vulnerability, use the private form named in [SECURITY.md](../../../SECURITY.md), not an issue.

## How reliable the findings are

The reviews were produced by a small model and each finding carries its own confidence label (confirmed by
probe, confirmed by reading, suspected). Seven were re-checked independently before the phase started: C-1,
C-4, C-6, D-1, D-2, D-3 and D-5. Every finding is reproduced in a test before it is fixed; one that does not
reproduce is recorded as such.

## Notes on review D

It was written against a scratch clone on a Windows workstation, so it contains local paths. "Not checked"
items in it (Linux and macOS runs, a live Hermes, GitHub settings) are covered by CI or by phase H2.
