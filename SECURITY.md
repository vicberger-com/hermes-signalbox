# Security policy

## Reporting

Report vulnerabilities privately through GitHub: Security tab, "Report a vulnerability". Do not open a public
issue. Expect an acknowledgement within 7 days. Fixes are released with an advisory.

Report form: https://github.com/vicberger-com/hermes-switchyard/security/advisories/new. Security model and
known limits: [docs/DESIGN.md](docs/DESIGN.md) section 4; review history: [docs/qa/](docs/qa/).

## Supported versions

The latest 1.x minor release receives security fixes.

## Status and deprecation policy

Switchyard is **Beta** (H1 D-14): 1.x has one operator so far and no external review. Until that changes:

- A change that breaks configuration, grants or behaviour is announced in the CHANGELOG under `Changed` with
  the operator step it needs, and ships in a minor release, never a patch release.
- A setting, operation or module action that is going away is marked deprecated in the CHANGELOG and the
  reference at least one minor release before it is removed.
- Security fixes may change behaviour in a patch release when the old behaviour is the vulnerability; the
  CHANGELOG says so under `Security`.

## Baseline

- Security is the first priority and overrides utility, speed and size in every design decision.
- Default-deny capabilities, secrets by reference, loopback-only control API, hash-chained audit log,
  pinned and verified dependencies and updates. Details: `docs/DESIGN.md` section 4.
- No telemetry. No cloud-hosted secret storage.
- Every release carries a CycloneDX SBOM; public releases carry build provenance.

## Scope notes

In-process modules are not sandboxed (a Python limitation). Only modules reviewed in this repository run
in-process; all others run as separate subprocesses with a scrubbed environment. Those subprocesses run as your
OS user, so they are a fault boundary, not a security boundary: install only modules you trust. Likewise a model
with an unrestricted shell can do what your user can. Details: `docs/DESIGN.md` section 4, "The same-user
boundary". Reports that depend only on same-user access are handled as hardening, not vulnerabilities.
