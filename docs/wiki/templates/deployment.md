# Deploy <profile name>

> **Type:** deployment · **Applies to:** v<X.Y.Z> · **Last checked:** <YYYY-MM-DD> · **Status:** draft

**Fits when:** <who and what this profile is for.>

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
hermes-signalbox module list
hermes-signalbox audit verify
```

## Operate

<Daily and weekly checks; where alerts appear.>

## Upgrade and roll back

<Commands; what to check after.>

## Remove

<Commands; what is left behind.>

---
**Sources:** [<document>](https://github.com/vicberger-com/hermes-signalbox/blob/v<X.Y.Z>/<path>) · [<document>](<link>)
