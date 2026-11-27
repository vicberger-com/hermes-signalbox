# Quickstart — Signalbox in 5 Minutes

Get from zero to a working dashboard with module grants in ~5 minutes.

## Prerequisites

- Hermes Agent 0.22+
- Python 3.11+
- Git

## 1. Install (pinned commit)

```bash
# Get latest release SHA from https://github.com/vicberger-com/hermes-signalbox/releases
export SHA=<40-char-commit-sha>
hermes plugins install vicberger-com/hermes-signalbox --ref $SHA
hermes plugins enable signalbox
```

> **Note**: The plugin is named `signalbox` (v1.1+). For v1.0.x, use `switchyard`.

## 2. Grant the required permissions (one time)

A module does nothing until you grant it the permissions (capabilities) it asks for. Each command grants
**one** permission: `--capability` given twice in one command is refused. Paste the whole block.

```bash
# Modules that start with Hermes
hermes -p default signalbox module grant activation --capability hermes.config.write
hermes -p default signalbox module grant activation --capability hermes.hooks
hermes -p default signalbox module grant activation --capability ui.panel
hermes -p default signalbox module grant inbox --capability core.read
hermes -p default signalbox module grant inbox --capability ui.panel
hermes -p default signalbox module grant meter --capability hermes.hooks
hermes -p default signalbox module grant meter --capability ui.panel
hermes -p default signalbox module grant resources --capability fs.read
hermes -p default signalbox module grant resources --capability ui.panel
hermes -p default signalbox module grant router --capability hermes.hooks
hermes -p default signalbox module grant router --capability ui.panel
hermes -p default signalbox module grant secrets --capability process.spawn
hermes -p default signalbox module grant secrets --capability secrets.read
hermes -p default signalbox module grant secrets --capability ui.panel
hermes -p default signalbox module grant supervisor --capability core.read
hermes -p default signalbox module grant supervisor --capability schedule
hermes -p default signalbox module grant supervisor --capability ui.panel
hermes -p default signalbox module grant workers --capability hermes.delegation
hermes -p default signalbox module grant workers --capability hermes.hooks
hermes -p default signalbox module grant workers --capability schedule
hermes -p default signalbox module grant workers --capability ui.panel

# Modules you start yourself (step 4)
hermes -p default signalbox module grant offload --capability net.outbound
hermes -p default signalbox module grant offload --capability ui.panel
hermes -p default signalbox module grant scanner --capability process.spawn
hermes -p default signalbox module grant scanner --capability schedule
hermes -p default signalbox module grant scanner --capability ui.panel
hermes -p default signalbox module grant trimmer --capability hermes.output
hermes -p default signalbox module grant trimmer --capability ui.panel
hermes -p default signalbox module grant updates --capability core.read
hermes -p default signalbox module grant updates --capability schedule
hermes -p default signalbox module grant updates --capability ui.panel
```

These are the permissions each module cannot run without. Some modules also ask for optional ones (for
example `llm.paid` for `router`, which allows paid models); grant those only when you want what they allow.
See the [permissions table](USER-GUIDE.md#3-grant-capabilities-and-activate-a-module) for each module.

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

Or use the dashboard: **Signalbox tab → Modules**, then the **Start** button on each row. The button is
disabled, with the reason beside it, until the module has the permissions it needs.

## 5. Open the dashboard

The dashboard tab needs Signalbox's local API, which is off by default.

1. Find the data directory:

   ```bash
   hermes -p default signalbox config show
   ```

   The first line, `data_dir:`, is the folder.
2. Open `config.toml` in that folder in a text editor (create the file if it is not there) and add these two
   lines, each on its own line:

   ```toml
   [api]
   enabled = true
   ```

3. Restart Hermes, then open the **Signalbox** tab in the Hermes dashboard.

## Verify It Works

```bash
# Each module should show "Running", or "Manual start" for the ones you start yourself
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