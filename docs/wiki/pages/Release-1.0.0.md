# Release 1.0.0

> **Type:** release · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** current

**Released:** 2026-11-20 · [Release page](https://github.com/vicberger-com/hermes-switchyard/releases/tag/v1.0.0) · [Changelog](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/CHANGELOG.md)

## Highlights

- First stable release: the core plus twelve bundled modules (M1-M12), after a whole-codebase hardening review.
- New [User guide](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/USER-GUIDE.md) and [Reference](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/REFERENCE.md).
- The model's limits are enforced in the core; everything module-written reaches the model labelled as data.

## Act on these when you upgrade

- Grant `core.read` to `inbox`: `switchyard module grant inbox --capability core.read`.
- The model can no longer deactivate modules or preview catalog imports.
- `module remove --keep-data` keeps data only, never grants.
- Module ids may not end in `_`; every meter quota fires at 100 %.

## Security

- 24 hardening findings and 10 follow-up findings fixed or dispositioned: see
  [docs/qa/14-r1-prework.md](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/qa/14-r1-prework.md).
- Same-user limits are documented in DESIGN section 4 and SECURITY.md.

## Verify the download

```bash
sha256sum -c SHA256SUMS --ignore-missing
gh attestation verify hermes_switchyard-1.0.0-py3-none-any.whl -R vicberger-com/hermes-switchyard
```

---
**Sources:** [CHANGELOG.md](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/CHANGELOG.md)
