# ADR-0016: Trust but validate

Status: accepted, 2026-11-27 (operator statement). Applies from H6; gap analysis:
[20-validation-gap.md](../qa/20-validation-gap.md).

## Context

Signalbox exists to do work for the operator: route requests, count usage, hold secrets, run checks, start
and stop modules, with less manual effort than before. Handing work over does not hand over responsibility.
The operator stated the principle on 2026-11-27, and stated that it is not new: the build plan has required
since M0 that every module "has its own panel or settings section, log stream, health check and report
section". The 1.1.0 usability review showed where that requirement was passed and not performed: all twelve
bundled modules register a status panel, and the dashboard page displays none of them.

## Decision

**Being given the capability, the access and the permission to do something does not remove the duty to show
that it was done and done right.** For every function Signalbox performs, the operator can answer four
questions without reading source code or raw data:

1. **Is it safe and secure?** What the function is allowed to do, and what it was refused.
2. **Was it done?** What ran, when, on whose instruction.
3. **Was it done right?** The result, measured against what was asked and against the stated standard.
4. **What should improve?** Enough history and measurement to see a trend and decide a change.

The operator's task is not to spot-check. It is to understand each function and its results, and to be able
to review and, when needed, correct them. A function the operator cannot see at a reasonable level of detail
fails this principle, however well it works.

### What every module provides

Each module has its own screen in the dashboard, and the same information at the command line and in chat,
with five parts:

| Part | Content |
|---|---|
| Configuration | Every setting in effect, its value, its default and where the value came from; the permissions granted and not granted |
| Controls | Every operation the module offers, what it does, and either a control that performs it or the exact command that does |
| Status | State, health, and what the module is doing now |
| Results | What the module did and the effect it had (requests routed and where, usage counted, findings raised, output trimmed), over a chosen period |
| Log and report | The module's own log and its audit records, readable and filterable; its section of each report |

The core has the same five parts for itself (hosting, the audit chain, the API, the data directory).

### What does not change

The security model does not change. Seeing is not the same as changing:

- **Visibility is complete on every surface.** Nothing Signalbox does is hidden from the operator.
- **A change is made on a surface that is trusted to make it.** The dashboard's server profile serves a fixed
  list of operations (ADR-0009 and the M9 review); granting a permission, installing, updating and removing a
  module and changing configuration stay at the terminal. Where the dashboard cannot perform an operation it
  shows what the operation is and the command that performs it, ready to copy. Widening the list is an
  operator decision recorded per operation, never a side effect of building a screen.
- Module-written text is shown as text, never as markup or instructions (reviews R-1, R-4, R-9).
- Every change made through any surface is written to the audit log with the surface as the actor.

### The same rule for the work itself

"Completed actions are not passed, they are performed." A requirement is met when its result has been
observed, not when its code exists:

- An acceptance item names the test that was run, or the surface that was looked at and by whom.
- A feature ships with the means to validate it (the view, the log line, the report section) in the same
  change, not later.
- A review states what was executed and what was only read.
- Pre-work question 13 and the validation gate in the build plan make this part of every phase.

## Consequences

- H6 builds the per-module screens and the command-line and chat equivalents, starting from the panels and
  actions the modules already have.
- Module contract: a module declares its settings (with defaults and meanings), so that "configuration in
  effect" can be shown for any module, third-party ones included.
- A module that performs work without leaving a readable record of it does not meet the definition of done.
- The dashboard page grows; the width and layout rules from the 1.1.0 review apply to every new view.
