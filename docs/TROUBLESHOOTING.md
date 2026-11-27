# Troubleshooting

Common issues and their fixes. Each entry: **Symptom → Cause → Fix (copy-paste commands)**.

---

## Module Stays "verified" — Won't Activate

**Symptom**: `hermes -p default signalbox module list` shows the module as "Manual start" or "Ready", and it
never becomes "Running".

**Cause**: The module's start mode is `manual` (offload, scanner, trimmer and updates ship that way). Modules
in `auto` mode start when Hermes starts; manual ones start when you start them.

**Fix**:
```bash
# Check module mode
hermes -p default signalbox module show <module>

# If manual mode: activate it
hermes -p default signalbox module activate <module>

# If auto mode but still verified: restart gateway
hermes gateway restart
```

If the module is in `auto` mode and still missing a permission, Signalbox says so at start-up. Look in the
Hermes log (or the terminal running `hermes-signalbox serve`) for a line that begins
`Signalbox: 1 module set to start with Hermes was not started`. The lines after it name each module, the
permissions it needs and the `module grant` command to run.

---

## "audit verify" Fails

**Symptom**: `hermes -p default signalbox audit verify` reports a problem and exits with a non-zero code.

**Cause**: A record in the audit log, or the stored end-of-chain marker, was changed or damaged.

**Fix**:
```bash
# Read the most recent records
hermes -p default signalbox audit tail --n 20

# Look for failed checks in the raw records
hermes -p default signalbox --json audit tail --n 100 | grep verify_failed

# After you have looked into it, acknowledge the failure
hermes -p default signalbox audit ack
```

---

## Daemon Won't Start / "Address already in use"

**Symptom**: `hermes-signalbox api serve` stops with a port conflict, or says another process hosts the
modules.

**Cause**: Either another program uses the port set under `[api] port` in `config.toml`, or Hermes is already
running Signalbox for this data directory. Leftover `api.port` and `api.token` files from a crashed daemon are
not the cause: Signalbox removes them itself when nothing is running.

**Fix**:
```bash
# See the data directory, the configured port and whether a process is hosting
hermes -p default signalbox config show
```

- If `hosting.here` or `hosting.pid` shows a running process, Hermes hosts the modules: do not start a second
  daemon. Use the Hermes chat or the API inside Hermes (see "Manual Module Won't Activate from CLI").
- Otherwise set `port = 0` under `[api]` in `config.toml` (0 picks a free port), or choose a free port, then
  start the daemon again:

```bash
hermes-signalbox api serve
```

---

## Two Data Directories Confusion

**Symptom**: Grants or modules show up in one place and not the other; a command works in a Hermes chat but
not at the terminal, or the reverse.

**Cause**: Signalbox inside Hermes uses the Hermes plugin data directory. The standalone command
`hermes-signalbox` uses its own default directory unless you tell it otherwise.

**Fix**:
```bash
# Option A (recommended): use the Hermes-hosted command, which always uses the Hermes directory
hermes -p default signalbox module list

# Option B: point the standalone command at the same directory.
# Take the path from the "data_dir:" line of this output:
hermes -p default signalbox config show
```

Then set `SIGNALBOX_DATA_DIR` to that path (for example `export SIGNALBOX_DATA_DIR="/path/from/above"`) and
run `hermes-signalbox module list`.

---

## Dashboard Tab Missing

**Symptom**: No "Signalbox" tab in the Hermes dashboard.

**Cause**: One of three things: the local API is off (the default); Signalbox was installed with pip (Hermes
shows a dashboard tab only for plugins installed into its plugins directory); or the plugin is not enabled.

**Fix**:

1. Add these two lines to `config.toml` in the data directory (`config show` prints the directory):

   ```toml
   [api]
   enabled = true
   ```

2. Install with `hermes plugins install`, not pip, and enable the plugin:

   ```bash
   hermes plugins install vicberger-com/hermes-signalbox --ref <SHA>
   hermes plugins enable signalbox
   ```

3. Restart Hermes completely.

---

## Grant Is Refused: "not requested in the manifest"

**Symptom**: `hermes -p default signalbox module grant <module> --capability <cap>` answers
`denied: cannot grant '<cap>' to '<module>': not requested in the manifest`.

**Cause**: A typing mistake in the permission name, or the module does not ask for that permission. Only
permissions a module asks for can be granted.

**Fix**:
```bash
# See what the module asks for and what it still needs
hermes -p default signalbox module show <module>
```

Grant one permission per command. `--capability` given twice in one command is refused.

---

## Update Rejected "Wider Capabilities"

**Symptom**: A module update is refused because the new version asks for more than the installed one.

**Cause**: The new version adds permissions, hosts, secrets or other contributions, or weakens isolation.
Signalbox does not accept that without your explicit yes.

**Fix**:
```bash
# See what the update would change, and the digest of the reviewed version
hermes -p default signalbox module preview <id> --ref <sha>

# If you accept the wider access, apply exactly the version you reviewed
hermes -p default signalbox module update <id> --ref <sha> --digest <digest> --accept-wider
```

---

## Manual Module Won't Activate from CLI

**Symptom**: `hermes -p default signalbox module activate <module>` answers
`'module activate' needs the running daemon`.

**Cause**: Starting a module, checking its health and running its actions need the process that hosts the
modules. When Hermes hosts them, the terminal command cannot reach that process unless the local API is on.

**Fix** (either one):

- In a Hermes chat of that profile:

  ```bash
  /signalbox module activate <module>
  ```

- Or turn on the API inside Hermes: add the two lines `[api]` and `enabled = true` to `config.toml` in the
  data directory, restart Hermes, then run:

  ```bash
  hermes -p default signalbox module activate <module>
  ```

Do not start `hermes-signalbox api serve` on a data directory that Hermes is already hosting.

---

## "Module Not Found" After Git Install

**Symptom**: Module doesn't appear in `module list` after install.

**Cause**: Module dir not in `<data_dir>/modules/<id>/` with valid `module.toml`.

**Fix**:
```bash
# Check discovered modules
hermes -p default signalbox module list

# Only modules with valid module.toml in data_dir/modules/ appear
# Reinstall with correct ref if missing
```

---

## Health Check Fails

**Symptom**: `hermes -p default signalbox module health <module>` reports a problem.

**Cause**: The module's own health check failed: a missing permission, a setting that is wrong, or an outside
service that is down.

**Fix**:
```bash
# The reason the module gives
hermes -p default signalbox module health <module>

# Its permissions and state
hermes -p default signalbox module show <module>
```

The module's log is `<data_dir>/logs/<module>.jsonl`.

---

## Router Not Routing to Free Models First

**Symptom**: Paid models are used when a free one would do.

**Cause**: A routing rule or a pinned model asks for it, or no daily limit for paid requests is set.

**Fix** (in a Hermes chat, or at the terminal when the API inside Hermes is on):
```bash
# Current pools, rules and budget
hermes -p default signalbox module action router --action status

# Why a request of a given size would go where it goes
hermes -p default signalbox module action router --action explain --args '{"tokens": 2000}'

# Limit paid requests per day
hermes -p default signalbox module action router --action budget --args '{"paid_requests_per_day": 20}'
```

All router actions and their arguments: [router README](../src/hermes_signalbox/modules/router/README.md).

---

## Meter Not Tracking Usage

**Symptom**: The usage summary shows nothing.

**Cause**: The `meter` module is not running, or it lacks the `hermes.hooks` permission that lets it see
requests.

**Fix**:
```bash
# State and permissions
hermes -p default signalbox module show meter

# Usage of the last 7 days
hermes -p default signalbox module action meter --action summary --args '{"days": 7}'

# Read the price table again after editing it
hermes -p default signalbox module action meter --action prices_reload
```

---

## Secrets Not Resolving

**Symptom**: A `secret://name` reference is not replaced.

**Cause**: No secret store is available, or no secret is stored under that name.

**Fix**:
```bash
# State and permissions
hermes -p default signalbox module show secrets

# Which stores are available and which names are known (values are never shown)
hermes -p default signalbox module action secrets --action status
```

Store the secret in your operating system's own store under the name Signalbox looks for; the
[secrets README](../src/hermes_signalbox/modules/secrets/README.md) lists the name format for each store
(Windows Credential Manager, macOS keychain, Secret Service, Vaultwarden). Never put a secret value on a
command line or in a chat: Signalbox has no command that takes one.

---

## Offload Connector Not Working

**Symptom**: Work is not sent to n8n, JevK5 or an agent command-line tool.

**Cause**: The connector is not in the allow list, the module lacks a permission, or it is not started.

**Fix**:
```bash
# State and permissions
hermes -p default signalbox module show offload

# Connectors and whether each is enabled
hermes -p default signalbox module action offload --action connectors
```

Connectors other than `jevk5` are off until you name them: add them to `allow` under `[modules.offload]` in
`config.toml` (for example `allow = ["n8n"]`) and restart Hermes. Agent command-line connectors also need
the optional `process.spawn` permission:

```bash
hermes -p default signalbox module grant offload --capability process.spawn
hermes -p default signalbox module activate offload
```

Read the [offload README](../src/hermes_signalbox/modules/offload/README.md) before allowing `codex`: it
can read local files.

---

## Where to Find Logs

| Log | Location |
|-----|----------|
| Module logs | `<data_dir>/logs/<module>.jsonl` |
| Audit log | `<data_dir>/audit/audit-*.jsonl` |
| Start-up notices and warnings | The Hermes log (logger `signalbox`), or the terminal running `hermes-signalbox api serve` |

Find `<data_dir>`:
```bash
hermes -p default signalbox config show
```

---

## Still Stuck?

1. Check `TROUBLESHOOTING.md` covers your issue
2. Run `hermes -p default signalbox audit verify` — if chain fails, that's the root
3. File an issue at https://github.com/vicberger-com/hermes-signalbox/issues with:
   - `hermes -p default signalbox module list` output
   - `hermes -p default signalbox audit tail --n 20` output
   - Steps to reproduce