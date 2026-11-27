# Security policy

## Reporting

Report vulnerabilities privately through GitHub: Security tab, "Report a vulnerability". Do not open a public
issue. Expect an acknowledgement within 7 days. Fixes are released with an advisory.

Report form: https://github.com/vicberger-com/hermes-signalbox/security/advisories/new. Security model and
known limits: [docs/DESIGN.md](docs/DESIGN.md) section 4; review history: [docs/qa/](docs/qa/).

## Supported versions

The latest 1.x minor release receives security fixes.

## Status and deprecation policy

Signalbox is **Beta** (H1 D-14): 1.x has one operator so far and no external review. Until that changes:

- A change that breaks configuration, grants or behaviour is announced in the CHANGELOG under `Changed` with
  the operator step it needs, and ships in a minor release, never a patch release.
- A setting, operation or module action that is going away is marked deprecated in the CHANGELOG and the
  reference at least one minor release before it is removed.
- Security fixes may change behaviour in a patch release when the old behaviour is the vulnerability; the
  CHANGELOG says so under `Security`.

## Known limits

- **One operator account.** Signalbox trusts the user account it runs as. A program running as that user can
  already read and change the data directory.
- **The Hermes dashboard on this computer.** The Hermes dashboard serves its session token to any program
  that requests the page from 127.0.0.1, and Signalbox's dashboard routes sit behind that token. Another
  local program, or another account on the same computer, can therefore start and stop modules, change
  start modes and acknowledge inbox notices. It cannot grant a permission, install, update or remove a
  module or change the configuration: the dashboard profile has no such route. This is a property of the
  Hermes dashboard; Signalbox cannot close it. Do not run the dashboard on a computer you share. (Found by
  reading the code in the independent review of 1.1.0; not exercised.)
- **A 1.0.x data directory is imported whole** on the first start, including its `config.toml` and
  `modules/`. Whoever could write that directory could write the new one.
- **The model reads module output.** Tool results that carry module-written text are marked as untrusted
  data, and chat replies show that text as words. Neither can stop a model from acting on what it reads.
- **Look-alike characters** (for example mathematical digits) in module-written text are shown as written.

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
