# Quickstart — Signalbox in 5 Minutes

Get from zero to a working dashboard with module grants in ~5 minutes.

## Prerequisites

- Hermes Agent 0.22+
- Python 3.11+
- Git

## 1. Install (pinned commit)

```bash
# Get latest release SHA from https://github.com/vicberger-com/hermes-switchyard/releases
export SHA=<40-char-commit-sha>
hermes plugins install vicberger-com/hermes-switchyard --ref $SHA
hermes plugins enable signalbox
```

> **Note**: The plugin is named `signalbox` (v1.1+). For v1.0.x, use `switchyard`.

## 2. Grant All Capabilities (one-time)

Run this once — grants all 12 modules their required capabilities:

```bash
# Auto modules (activate on gateway restart)
hermes -p default signalbox module grant activation --capability hermes.config.write --capability hermes.hooks --capability ui.panel
hermes -p default signalbox module grant inbox --capability core.read --capability ui.panel
hermes -p default signalbox module grant meter --capability hermes.hooks --capability ui.panel
hermes -p default signalbox module grant resources --capability fs.read --capability ui.panel
hermes -p default signalbox module grant router --capability hermes.hooks --capability ui.panel
hermes -p default signalbox module grant secrets --capability process.spawn --capability secrets.read --capability ui.panel
hermes -p default signalbox module grant supervisor --capability core.read --capability schedule --capability ui.panel
hermes -p default signalbox module grant workers --capability hermes.delegation --capability hermes.hooks --capability schedule --capability ui.panel

# Manual modules (activate after grants)
hermes -p default signalbox module grant offload --capability net.outbound --capability process.spawn --capability ui.panel
hermes -p default signalbox module grant scanner --capability process.spawn --capability schedule --capability ui.panel
hermes -p default signalbox module grant trimmer --capability hermes.output --capability ui.panel
hermes -p default signalbox module grant updates --capability core.read --capability schedule --capability ui.panel
```

See the [Module Capabilities Table](USER-GUIDE.md#3-grant-capabilities-and-activate-a-module) for the full breakdown per module.

## 3. Restart Gateway (activates auto modules)

```bash
hermes gateway restart
```

Wait ~3 seconds for modules to start.

## 4. Activate Manual Modules (optional but recommended)

```bash
hermes -p default signalbox module activate offload
hermes -p default signalbox module activate scanner
hermes -p default signalbox module activate trimmer
hermes -p default signalbox module activate updates
```

Or use the dashboard: **Signalbox tab → Modules → click "Activate"** on each.

## 5. Open Dashboard

```bash
# Enable API if not already
echo '[api] enabled = true' >> $(hermes -p default signalbox config show | grep data_dir | cut -d' ' -f2)/config.toml

# Restart Hermes Desktop
# Click the **Signalbox** tab in the dashboard
```

## Verify It Works

```bash
# All modules should show "active" (auto) or "verified" (manual, until activated)
hermes -p default signalbox module list

# Audit chain intact
hermes -p default signalbox audit verify

# Health report
hermes -p default signalbox report show --kind health
```

## Next Steps

- Read [USER-GUIDE.md](USER-GUIDE.md) for depth
- See [Module Capabilities Table](USER-GUIDE.md#3-grant-capabilities-and-activate-a-module) for per-module details
- Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) if anything fails
- Explore [REFERENCE.md](REFERENCE.md) for all operations