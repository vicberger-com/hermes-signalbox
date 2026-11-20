# Changelog

Format: Keep a Changelog. Versions: Semantic Versioning.

## [Unreleased]

### Added
- `switchyard` package (phase M0, part 1): data-directory resolution, core configuration (`config.toml`),
  manifest loader returning a typed `Manifest` with entry-path containment checks, error hierarchy.
- Coverage gate (90%) on `src/switchyard`; mypy strict and bandit now include `src/`.

### Changed
- The manifest schema moved to `src/switchyard/schemas/module.schema.json` so it ships in the wheel.
  `tools/validate_manifest.py` is now a thin CLI over `switchyard.manifest`.

### Fixed
- Schema `pattern` checks used Python's `$`, which accepts a trailing newline; they now follow JSON Schema
  semantics (a module id such as `"example\n"` is rejected).

## [0.0.1] - 2026-11-19

Repository bootstrap (phase P0). No runtime code.

### Added
- Design, build plan, module catalog, pre-engagement Q&A and third-party license review.
- Module manifest schema, stdlib validator, module template and contract tests.
- CI, security scanning, release and Dependabot configuration.

### Changed
- Tooling is installed from a hash-pinned `requirements-dev.txt`; `ci-required` and `security-required` gate jobs added.
- Secret scanning runs the pinned gitleaks CLI. Repository moved to the `vicberger-com` organization.
