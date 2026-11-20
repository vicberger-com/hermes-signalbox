# Contributing

Applies to people and agents alike. Agents also follow [AGENTS.md](AGENTS.md).

## Git and GitHub

- Trunk-based. `main` is protected. Branch names: `feat/m3-router`, `fix/…`, `docs/…`, `chore/…`.
- Conventional Commits (`feat(m3): …`, `fix(core): …`). One logical change per PR. Squash merge.
- A PR needs: linked issue or phase, filled template, green CI, no unresolved review comment.
- Releases: semantic versions, annotated signed tags, changelog entry (Keep a Changelog format), SBOM attached.
- Never commit secrets, generated credentials, real usage data or prompts. gitleaks runs in CI and pre-commit.

## Code

- Python >= 3.11, type hints everywhere, `mypy --strict` on `src/`.
- ruff for lint and format; line length 110.
- Standard library first. A new dependency follows the five rules in `docs/THIRD-PARTY.md`.
- Small modules, pure functions where possible, no global mutable state, no import-time side effects.
- Errors are explicit types; never swallow an exception silently; fail closed on security checks.
- All I/O that touches the network, the file system outside the data directory, a subprocess or a secret goes
  through the core broker for that capability.
- Public names have docstrings that say what, inputs, outputs and failure modes.

## Tests

- Written before the implementation. pytest. Deterministic: no network, no real clock, no real provider calls.
- Each module ships the contract tests from `templates/module/tests/`.
- Security behaviours have their own tests (denied capability, redaction, audit chain, paid gate).

## Documentation

- Every module: `README.md` (purpose, capabilities and why, config keys, tools, events, data stored, removal).
- Design changes to the core contract need an ADR in `docs/adr/NNNN-title.md` (context, decision, consequences).
- Docs change in the same PR as the code.

## SBOM and licensing

- CycloneDX JSON SBOM generated in CI for every build and attached to every release.
- SPDX license identifier in `pyproject.toml`; third-party attributions in `NOTICE`.
- CI fails on a dependency whose license is not on the allow-list (MIT, BSD-2-Clause, BSD-3-Clause, ISC,
  Apache-2.0, PSF-2.0, CC0-1.0, MPL-2.0 for unmodified use).

## Local setup

Tooling is pinned with hashes in `requirements-dev.txt`. Regenerate it after changing the extras in
`pyproject.toml`: `uv pip compile pyproject.toml --extra dev --extra security --universal --generate-hashes -o requirements-dev.txt`.

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install --require-hashes -r requirements-dev.txt
pip install --no-deps --no-build-isolation -e .
pre-commit install
python -m pytest -q
```
