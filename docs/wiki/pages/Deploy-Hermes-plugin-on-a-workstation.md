# Deploy Hermes plugin on a workstation

> **Type:** deployment · **Applies to:** v1.0.0 · **Last checked:** 2026-11-24 · **Status:** current

**Fits when:** one person uses Hermes (desktop, TUI or CLI) on their own machine and wants Signalbox to manage
models, skills and spend for those sessions.

## Layout

- Signalbox runs inside Hermes as a plugin. The Hermes gateway **hosts** modules: it runs their hooks, gates,
  transforms and schedules. Without a gateway, the first Hermes process that runs a turn hosts. One-shot
  commands (`hermes gateway status`, `hermes signalbox ...`) never host. Another process that runs turns while
  the host is up uses stored state only (one `core.not_hosting` audit record) and takes over if the host exits.
- Data directory: the Hermes profile's plugin data directory, unless `data_dir` is set.
- Nothing listens on the network unless `[api] enabled = true` (loopback only).

## Install

```bash
hermes plugins install vicberger-com/hermes-signalbox --ref <40-character commit SHA of v1.0.0>
```

Always install by owner/repository and a pinned commit (`--ref <SHA>`); Signalbox is not in the Hermes catalog.
The install warns that the source is custom (unreviewed); that is expected for a plugin outside the catalog.
Start a new chat after `hermes plugins enable signalbox`: the model tools reach new sessions only.

Verify the release first if you install from the wheel:

```bash
sha256sum -c SHA256SUMS --ignore-missing
gh attestation verify hermes_signalbox-1.0.0-py3-none-any.whl -R vicberger-com/hermes-signalbox
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
hermes-signalbox module list
hermes-signalbox audit verify
hermes-signalbox report show --kind health
```

While Hermes hosts the modules, run reports and other `[daemon]` commands in a chat (`/signalbox report show
--kind health`), or enable the API and restart Hermes ([user guide](https://github.com/vicberger-com/hermes-signalbox/blob/main/docs/USER-GUIDE.md) section 2).

## Operate

- Weekly: `hermes-signalbox report show --kind usage` and `--kind security`; read the inbox.
- After any alert: see [[Runbooks]].

## Upgrade and roll back

```bash
hermes plugins update signalbox
hermes-signalbox audit verify
```

Read [[Releases]] for changes you must act on (for 1.0.0: grant `core.read` to `inbox`).

## Remove

```bash
hermes plugins disable signalbox
hermes plugins remove signalbox
```

`disable` makes the running gateway unload Signalbox (modules stop, the API closes, the data directory is
released). If it says the gateway refused or did not answer, run `hermes gateway restart` before `remove`.

The data directory (audit log, state, logs, `config.toml`) stays; delete it yourself if you do not need the
audit history.

---
**Sources:** [USER-GUIDE.md](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/USER-GUIDE.md) · [REFERENCE.md](https://github.com/vicberger-com/hermes-signalbox/blob/v1.0.0/docs/REFERENCE.md)
