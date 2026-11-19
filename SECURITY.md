# Security policy

## Reporting

Report vulnerabilities privately through GitHub: Security tab, "Report a vulnerability". Do not open a public
issue. Expect an acknowledgement within 7 days. Fixes are released with an advisory.

## Supported versions

Until 1.0.0 only the latest tagged release is supported.

## Baseline

- Security is the first priority and overrides utility, speed and size in every design decision.
- Default-deny capabilities, secrets by reference, loopback-only control API, hash-chained audit log,
  pinned and verified dependencies and updates. Details: `docs/DESIGN.md` section 4.
- No telemetry. No cloud-hosted secret storage.
- Every release carries a CycloneDX SBOM; public releases carry build provenance.

## Scope notes

In-process modules are not sandboxed (a Python limitation). Only modules reviewed in this repository run
in-process; all others run as separate subprocesses with a scrubbed environment.
