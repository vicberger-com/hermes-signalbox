# Troubleshooting

Common issues and their fixes. Each entry: **Symptom → Cause → Fix (copy-paste commands)**.

---

## Module Stays "verified" — Won't Activate

**Symptom**: `hermes -p default signalbox module list` shows `status: verified` with `missing_grants: []` but module never goes `active`.

**Cause**: Module is in `manual` mode (offload, scanner, trimmer, updates). Auto modules activate on gateway restart; manual modules need explicit activation.

**Fix**:
```bash
# Check module mode
hermes -p default signalbox module show <module>

# If manual mode: activate it
hermes -p default signalbox module activate <module>

# If auto mode but still verified: restart gateway
hermes gateway restart
```

---

## "audit verify" Fails

**Symptom**: `hermes -p default signalbox audit verify` returns non-zero exit code.

**Cause**: Tampered or corrupted audit log/anchor record.

**Fix**:
```bash
# Inspect recent records
hermes -p default signalbox audit tail -n 20

# Check for verify_failed records
hermes -p default signalbox audit tail -n 100 | grep verify_failed

# After investigation, acknowledge
hermes -p default signalbox audit ack
```

---

## Daemon Won't Start / "Address already in use"

**Symptom**: `hermes-signalbox api serve` fails with port conflict.

**Cause**: Stale `api.port` / `api.token` files from crashed daemon.

**Fix**:
```bash
# Find data dir
hermes -p default signalbox config show | grep data_dir

# Remove stale files
rm <data_dir>/api.port <data_dir>/api.token

# Restart daemon
hermes-signalbox api serve
```

---

## Two Data Directories Confusion

**Symptom**: Grants/modules visible in CLI but not Hermes (or vice versa). Commands work in one context but not the other.

**Cause**: Hermes plugin data dir ≠ `signalbox` CLI default data dir.

**Fix**:
```bash
# Option A: Use Hermes-hosted commands (recommended)
hermes -p default signalbox module list

# Option B: Set unified data dir for both
export SIGNALBOX_DATA_DIR=$(hermes -p default signalbox config show | grep data_dir | cut -d' ' -f2)
# Then use signalbox CLI normally
signalbox module list
```

---

## Dashboard Tab Missing

**Symptom**: No "Signalbox" tab in Hermes Desktop dashboard.

**Cause**: Installed via pip or wrong plugin name; dashboard plugin not registered.

**Fix**:
```bash
# Must use hermes plugins install (not pip)
hermes plugins install vicberger-com/hermes-switchyard --ref <SHA>
hermes plugins enable signalbox

# Restart Hermes Desktop completely
```

---

## Grant Fails "Capability Not Declared"

**Symptom**: `hermes -p default signalbox module grant <module> --capability <cap>` errors with "capability not declared".

**Cause**: Typo in capability name, or module doesn't request that capability.

**Fix**:
```bash
# Check what capabilities the module actually requests
hermes -p default signalbox module show <module>
# Look at "requested" field — only these can be granted

# Grant only from the requested list
```

---

## Update Rejected "Wider Capabilities"

**Symptom**: Module update fails with "wider capabilities not accepted".

**Cause**: New version adds capabilities/hosts/secrets beyond what was granted.

**Fix**:
```bash
# Preview the update first
hermes -p default signalbox module preview <id> --ref <sha>

# If acceptable, apply with --accept-wider
hermes -p default signalbox module update <id> --ref <sha> --accept-wider --digest <digest>
```

---

## Manual Module Won't Activate from CLI

**Symptom**: `hermes -p default signalbox module activate <module>` fails or does nothing.

**Cause**: Hermes hosts modules; CLI `activate` needs the daemon running (separate process).

**Fix**:
```bash
# Use Hermes chat instead (works when Hermes hosts modules)
/signalbox module activate <module>

# Or start daemon, then use CLI
hermes-signalbox api serve &
hermes -p default signalbox module activate <module>
```

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

**Symptom**: `hermes -p default signalbox module health <module>` returns error.

**Cause**: Module's `health()` method raised exception (misconfig, missing dep, etc).

**Fix**:
```bash
# Get detailed error
hermes -p default signalbox module health <module>

# Check module logs
cat <data_dir>/logs/<module>.jsonl

# Common: missing capability, config error, external service down
```

---

## Router Not Routing to Free Models First

**Symptom**: Paid models used when free available.

**Cause**: Router rules misconfigured, or budget not set.

**Fix**:
```bash
# Check router status and rules
hermes -p default signalbox module run router status
hermes -p default signalbox module run router explain <request>

# Set budget if missing
hermes -p default signalbox module run router budget --set <amount>
```

---

## Meter Not Tracking Usage

**Symptom**: `meter summary` shows zero usage.

**Cause**: Meter hooks not firing, or wrong provider config.

**Fix**:
```bash
# Check meter status
hermes -p default signalbox module show meter

# Verify hooks registered
hermes -p default signalbox module run meter summary --days 7

# Reload prices if needed
hermes -p default signalbox module run meter prices_reload
```

---

## Secrets Not Resolving

**Symptom**: `secret://name` not replaced in outbound requests.

**Cause**: Backend not configured, or secret name mismatch.

**Fix**:
```bash
# Check secrets status
hermes -p default signalbox module show secrets
hermes -p default signalbox module run secrets status

# Configure backend (e.g., Vaultwarden)
# Then add secret
hermes -p default signalbox module run secrets add <name> <value>
```

---

## Offload Connector Not Working

**Symptom**: Work not sent to n8n/JevK5/agent CLI.

**Cause**: Connector not allowed by name, or host not in allow-list.

**Fix**:
```bash
# Check offload config
hermes -p default signalbox module show offload
hermes -p default signalbox module run offload connectors

# Allow connector by name
hermes -p default signalbox module grant offload --capability net.outbound --capability process.spawn --capability ui.panel
# Then activate
hermes -p default signalbox module activate offload
```

---

## Where to Find Logs

| Log | Location |
|-----|----------|
| Module logs | `<data_dir>/logs/<module>.jsonl` |
| Audit log | `<data_dir>/audit/audit-*.jsonl` |
| Daemon logs | `<data_dir>/logs/daemon.jsonl` (if running) |
| Hermes gateway | `~/.local/share/hermes/logs/` |

Find `<data_dir>`:
```bash
hermes -p default signalbox config show | grep data_dir
```

---

## Still Stuck?

1. Check `TROUBLESHOOTING.md` covers your issue
2. Run `hermes -p default signalbox audit verify` — if chain fails, that's the root
3. File an issue at https://github.com/vicberger-com/hermes-switchyard/issues with:
   - `hermes -p default signalbox module list` output
   - `hermes -p default signalbox audit tail -n 20` output
   - Steps to reproduce