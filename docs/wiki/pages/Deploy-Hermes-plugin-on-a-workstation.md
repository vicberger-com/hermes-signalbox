# Deploy Hermes plugin on a workstation

> **Type:** deployment · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** current

**Fits when:** one person uses Hermes (desktop, TUI or CLI) on their own machine and wants Switchyard to manage
models, skills and spend for those sessions.

## Layout

- Switchyard runs inside Hermes as a plugin. The first Hermes session to start **hosts** modules: it runs their
  hooks, gates, transforms and schedules. Later sessions use stored state only (one `core.not_hosting` audit
  record each).
- Data directory: the Hermes profile's plugin data directory, unless `data_dir` is set.
- Nothing listens on the network unless `[api] enabled = true` (loopback only).

## Install

```bash
hermes plugins install vicberger-com/hermes-switchyard --ref <40-character commit SHA of v1.0.0>
```

Verify the release first if you install from the wheel:

```bash
sha256sum -c SHA256SUMS --ignore-missing
gh attestation verify hermes_switchyard-1.0.0-py3-none-any.whl -R vicberger-com/hermes-switchyard
```

## Configure

```toml
# <data_dir>/config.toml
[host]
profile = "workstation"

[modules.router]
providers = ["openrouter"]
```

Then grant and activate the modules you want, starting with `resources`, `router`, `meter` and `supervisor`
(see each [[Module catalog]] entry).

## Verify

```bash
switchyard module list
switchyard audit verify
switchyard report show --kind health
```

## Operate

- Weekly: `switchyard report show --kind usage` and `--kind security`; read the inbox.
- After any alert: see [[Runbooks]].

## Upgrade and roll back

```bash
hermes plugins update switchyard
switchyard audit verify
```

Read [[Releases]] for changes you must act on (for 1.0.0: grant `core.read` to `inbox`).

## Remove

```bash
hermes plugins remove switchyard
```

The data directory (audit log, state, logs, `config.toml`) stays; delete it yourself if you do not need the
audit history.

---
**Sources:** [USER-GUIDE.md](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/USER-GUIDE.md) · [REFERENCE.md](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/REFERENCE.md)
