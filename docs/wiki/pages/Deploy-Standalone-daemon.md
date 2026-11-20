# Deploy Standalone daemon

> **Type:** deployment · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Fits when:** `switchyard api serve` hosts modules and the loopback API without a Hermes session.

## Layout

<Which processes run, which one hosts modules, where the data directory is, what listens where.>

## Install

```bash
<commands>
```

## Configure

```toml
# <data_dir>/config.toml
<keys>
```

## Verify

```bash
switchyard module list
switchyard audit verify
```

## Operate

<Daily and weekly checks; where alerts appear.>

## Upgrade and roll back

<Commands; what to check after.>

## Remove

<Commands; what is left behind.>

---
**Sources:** [USER-GUIDE.md](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/USER-GUIDE.md)
