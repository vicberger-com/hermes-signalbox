# Changelog

Format: Keep a Changelog. Versions: Semantic Versioning.

## [Unreleased]

## [0.0.1] - 2026-11-19

Repository bootstrap (phase P0). No runtime code.

### Added
- Design, build plan, module catalog, pre-engagement Q&A and third-party license review.
- Module manifest schema, stdlib validator, module template and contract tests.
- CI, security scanning, release and Dependabot configuration.

### Changed
- Tooling is installed from a hash-pinned `requirements-dev.txt`; `ci-required` and `security-required` gate jobs added.
- Secret scanning runs the pinned gitleaks CLI. Repository moved to the `vicberger-com` organization.
