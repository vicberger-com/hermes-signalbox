# Upgrading to 1.1: Switchyard is now Signalbox

Release 1.1.0 renames the plugin from **Switchyard** to **Signalbox**. Another plugin in the Hermes catalog used
the old name and registered the same `/switchyard` command (NousResearch/hermes-agent#160166). Behaviour,
modules, grants and data carry over. Names do not: update anything you typed or scripted.

## What changed

| Item | 1.0.x (Switchyard) | 1.1 (Signalbox) | Old name still works? |
|---|---|---|---|
| Plugin name | `switchyard` | `signalbox` | no |
| Chat command | `/switchyard ...` | `/signalbox ...` | no |
| Hermes CLI command | `hermes switchyard ...` | `hermes signalbox ...` | no |
| Standalone command | `switchyard ...` | `hermes-signalbox ...` | no |
| Model tools | `switchyard_modules`, `switchyard_audit`, `switchyard_host` | `signalbox_modules`, `signalbox_audit`, `signalbox_host` | no |
| Python package (third-party modules) | `switchyard` (`SwitchyardError`, ...) | `hermes_signalbox` (`SignalboxError`, ...) | no |
| Package and repository | `hermes-switchyard`, `vicberger-com/hermes-switchyard` | `hermes-signalbox`, `vicberger-com/hermes-signalbox` | GitHub redirects the old repository URL |
| Dashboard tab | `/switchyard` | `/signalbox` | no |
| Data directory variable | `SWITCHYARD_DATA_DIR` | `SIGNALBOX_DATA_DIR` | yes, in 1.1.x, with a deprecation warning |
| Development secrets variables | `SWITCHYARD_SECRET_<NAME>` | `SIGNALBOX_SECRET_<NAME>` | yes, in 1.1.x, with a deprecation warning |
| Stored secrets (Windows Credential Manager, macOS keychain, Secret Service) | service / prefix `switchyard` | `signalbox` | yes: read when the new name has no entry; new and rotated values are written under `signalbox` |
| Data directory (Hermes) | `plugin-data/agent-plugin-switchyard-<digest>` | `plugin-data/agent-plugin-signalbox-<digest>` | copied on first start (below) |
| Data directory (standalone default) | `.../switchyard` | `.../signalbox` | copied on first start (below) |

## Steps

1. Disable and remove Switchyard, so its gateway process lets go of the old data directory:
   `hermes plugins disable switchyard`, then `hermes plugins remove switchyard`.
2. Install and enable Signalbox (USER-GUIDE section 1):
   `hermes plugins install vicberger-com/hermes-signalbox --ref <SHA> --no-enable`, then
   `hermes plugins enable signalbox --no-allow-tool-override`.
3. Restart the gateway (`hermes gateway restart`). On its first start Signalbox copies the old data directory
   (next section). Check with `hermes signalbox audit tail`: the newest records include `core.migrated`, with the
   old path under `from`.
4. Rename `SWITCHYARD_DATA_DIR` and `SWITCHYARD_SECRET_*` in your environment or `.env` to the `SIGNALBOX_` names.
5. Update anything that calls the old commands or tool names (scripts, saved prompts, scheduled tasks, the
   standalone service from USER-GUIDE section 10).
6. When everything works, delete the old data directory if you no longer need it for a rollback.

## How the data directory is copied

On the first start of 1.1, when the new data directory has no state yet, Signalbox looks for exactly one old
one next to it: `agent-plugin-switchyard-*` in Hermes, `switchyard` for the standalone default. If it finds one:

- it takes the old directory's host lock, so no 1.0.x process can host modules from it during the copy;
- it copies everything except the old process's runtime files (`host.lock`, `api.port`, `api.token`) to a
  temporary sibling, verifies the audit chain in the copy, and only then renames the copy into place;
- it records `core.migrated` in the audit log;
- it leaves the old directory unchanged.

It copies nothing and stops with a message when:

| Message | Cause | What to do |
|---|---|---|
| `... is in use by a Switchyard 1.0.x process` | A 1.0.x gateway or daemon still hosts from the old directory | Step 1, restart Hermes, start again |
| `the audit log in ... does not verify` | The old audit log was changed or damaged | Check it with 1.0.x (`switchyard audit verify`); fix, or start fresh by setting `SIGNALBOX_DATA_DIR` to a new directory |
| `found several Switchyard data directories` | More than one old directory (several profiles or plugin keys) | Copy the right one by hand, or set `SIGNALBOX_DATA_DIR` |
| `... is not empty` | The new directory holds other files | Move them away, start again |

A directory you name yourself (`--data-dir`, the `data_dir` plugin setting, `SIGNALBOX_DATA_DIR` or the
deprecated variable) is used as is: nothing is copied into it.

## Rolling back to 1.0.3

The old directory is untouched by the copy, so reinstalling Switchyard 1.0.3 resumes where it stopped. It does not
see what happened under Signalbox, which wrote only to the new directory.

Record: [ADR-0015](adr/0015-rename-to-signalbox.md).
