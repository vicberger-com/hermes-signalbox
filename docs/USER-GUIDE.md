# User guide

Switchyard is a Hermes plugin with a small core and modules you switch on one at a time. Nothing a module does is
allowed until you grant it, and everything that changes is written to a hash-chained audit log. Command and
setting details: [REFERENCE.md](REFERENCE.md). Security model and its limits: [DESIGN.md](DESIGN.md) section 4.

## 1. Install

Needs Hermes Agent 0.22 or newer and Python 3.11 or newer. Switchyard has no Python dependencies.

```bash
# pin an exact release commit (recommended): see the release page for the SHA of a tag
hermes plugins install vicberger-com/hermes-switchyard --ref <40-character commit SHA>
# or with pip, which also installs the `switchyard` command
pip install "git+https://github.com/vicberger-com/hermes-switchyard@<40-character commit SHA>"
```

**Install by owner/repository and commit, never by the bare name.** The Hermes plugin catalog has an entry named
`hermes-switchyard` that belongs to a different, unrelated project (it also adds a `/switchyard` command), so
`hermes plugins install hermes-switchyard` installs that one, not this. Always pass
`vicberger-com/hermes-switchyard` with `--ref <SHA>`, and do not install both. Because this repository is not in
the catalog, the install prints `Warning: custom (unreviewed) source — not from the Hermes catalog.`; that is
expected.

Releases carry `SHA256SUMS`, a CycloneDX SBOM of what the wheel installs, and a build provenance attestation
(`gh attestation verify <file> -R vicberger-com/hermes-switchyard`). Pin a commit SHA, not a tag name, for
both routes: tags are annotated but not yet signed.

The two routes differ in one way: Hermes 0.23 shows a plugin's dashboard tab only for plugins installed into a
plugins directory, so the Switchyard tab (section 5) needs `hermes plugins install`. A pip install provides the
plugin, the `switchyard` command and the model tools, without the tab; the wheel carries the dashboard files
under `switchyard/_plugin/` for when Hermes supports that.

Switchyard has no Python dependencies, and its `plugin.yaml` says so (`python_runtime: external`), so
`hermes plugins install` only places the plugin in the profile's plugins directory; Hermes's own environment is
not changed. Release 1.0.1 lacked that line: Hermes then installed the package into its shared environment, every
profile listed `switchyard`, and a Hermes Desktop install warned `install out of sync` on every command. To clear
that, install a later release over it (`hermes plugins install vicberger-com/hermes-switchyard --force --ref <SHA>`).
If `hermes plugins enable switchyard` asks whether the plugin may replace built-in tools, answer no
(`--no-allow-tool-override`): Switchyard replaces none.

With a plugin install, run the command line through Hermes for the profile, `hermes -p <profile> switchyard
<noun> <verb> ...`; every `switchyard ...` command in this guide works that way. The `switchyard` command itself
comes with the pip route.

## 2. First run

**Which data directory.** Switchyard keeps its state, grants, audit log and `config.toml` in one data directory.
A Hermes session uses the profile's plugin data directory; the `switchyard` command uses a platform default
(`%LOCALAPPDATA%\switchyard`, `~/Library/Application Support/switchyard` or `~/.local/share/switchyard`). These
are **two different stores** unless you point both at one: set `SWITCHYARD_DATA_DIR` (or pass `--data-dir`, which wins over the variable) to
the same absolute path everywhere. `switchyard config show` prints the directory in use and why it was chosen
(`data_dir_source`).

**Which process hosts modules.** Only one process hosts modules for a data directory: the Hermes gateway (or,
without a gateway, the Hermes process that runs your turns), or `switchyard api serve`. A one-shot command such
as `hermes gateway status` or `hermes switchyard ...` never becomes the host. If something else holds the
directory when Hermes starts, Hermes takes over within seconds of it letting go (audit record
`core.hosting_acquired`). `switchyard config show` prints the hosting process (`hosting.pid`). Commands marked `[daemon]` in `switchyard <noun> --help` (activate,
deactivate, health, panel, action, update, preview, rollback, check_updates, report) need that hosting process
with its loopback API. Other commands (list, show, grant, revoke, mode, remove, audit, config) work directly on
the data directory; `remove` only while no other process hosts it. A process that runs turns without hosting writes one `core.not_hosting` audit record.

For the commands in this guide, start the daemon first in its own terminal and leave it running (Ctrl+C stops
it):

```bash
switchyard api serve              # step 0: hosts the modules and the loopback API
```

Then, in another terminal:

```bash
switchyard module list            # every module, its status, mode and requested capabilities
switchyard audit verify           # the audit chain is intact
switchyard config show            # data directory in use, why, and core settings
```

In a Hermes session the same operations are under `/switchyard`, for example `/switchyard module list`.

Exit codes: 0 success, 1 error or a failed result, 2 usage error (unknown name or invalid value), 3 refused by
policy (capability not granted, or not declared by the module).

**When Hermes hosts the modules** (Hermes Desktop, or any running gateway: it serves every profile and loads the
plugin as soon as it is enabled). The gateway is then the hosting process, so do not start `switchyard api
serve` for that profile; it reports that another process hosts modules. What works:

| You want to | Do |
|---|---|
| Grant, revoke, set modes, read the audit log, show config | The command line as usual (`hermes -p <profile> switchyard ...`); it works on the data directory. Hermes applies a new mode or a revoke within its next tick (15 s): `disabled` stops a running module, `auto` lets the model start it, a revoked required capability stops the module |
| Remove a module | `/switchyard module remove <id>` in a Hermes chat; the command line refuses while Hermes hosts |
| Start or stop a module, check its health, run any module action | `/switchyard <noun> <verb> ...` in a Hermes chat of that profile, for example `/switchyard module activate router` |
| Use the command line for those too | Set `[api] enabled = true` in `<data_dir>/config.toml` and restart Hermes. The API inside Hermes serves `module activate`, `deactivate`, `health`, `panel` and read-only actions; anything else is refused with a message naming `/switchyard` |
| Apply a changed `config.toml` | Restart Hermes; settings are read when the plugin loads |

Modules in `auto` mode whose grants are complete start whenever Hermes loads the plugin. Module status is kept
per process: `module list` from the command line shows `verified` for a module Hermes is running. The audit log
(`module.activated`) and `/switchyard module health <id>` show the hosting process's view.

## 3. Grant capabilities and activate a module

Each module's README lists what it requests and why. A module starts only when every capability it needs to
start is granted; `module show` lists any that are missing under `missing_grants`. Optional capabilities turn
on extra features and can be granted later.

| Module | Needed to start | Optional | Default mode |
|---|---|---|---|
| `activation` | `hermes.config.write`, `hermes.hooks`, `ui.panel` | | auto |
| `inbox` | `core.read`, `ui.panel` | | auto |
| `meter` | `hermes.hooks`, `ui.panel` | `fs.read` | auto |
| `offload` | `net.outbound`, `ui.panel` | `process.spawn` | manual |
| `resources` | `fs.read`, `ui.panel` | | auto |
| `router` | `hermes.hooks`, `ui.panel` | `llm.free`, `llm.paid` | auto |
| `scanner` | `process.spawn`, `schedule`, `ui.panel` | `notify` | manual |
| `secrets` | `process.spawn`, `secrets.read`, `ui.panel` | | auto |
| `supervisor` | `core.read`, `schedule`, `ui.panel` | | auto |
| `trimmer` | `hermes.output`, `ui.panel` | | manual |
| `updates` | `core.read`, `schedule`, `ui.panel` | `notify` | manual |
| `workers` | `hermes.delegation`, `hermes.hooks`, `schedule`, `ui.panel` | `llm.paid` | auto |

Grant only what you want the module to do, then start it (the daemon from section 2 must be running):

```bash
switchyard module show router
switchyard module grant router --capability hermes.hooks
switchyard module grant router --capability ui.panel
switchyard module activate router               # [daemon]
switchyard module health router                 # [daemon]
switchyard module mode router --mode auto       # start it with every hosting process
```

A grant only records consent; it never starts a module. In a running Hermes, a module whose last missing grant
you just gave stays stopped until you start it (`/switchyard module activate <id>` in a chat, or the command
line through the API, section 2) or until Hermes next loads the plugin, which starts `auto` modules whose grants
are complete.

`module revoke` withdraws a capability (a module that needs it stops, in a running Hermes within 15 s). `module mode <id> --mode disabled` keeps a
module from starting. Removing a module (`module remove`) always drops its grants; `--keep-data` keeps only its
stored data.

Module settings live in `<data_dir>/config.toml` under `[modules.<id>]`; each module README lists its keys.
Restart the hosting process after editing them.

## 4. What the model may do

The tools reach the model in the next chat after you enable the plugin: Hermes adds a plugin's tools to new
sessions only (`hermes plugins enable` prints `deferred: tools (next session)`), so start a new chat before
asking the model to use them. `/switchyard` commands work at once.

Hermes's model gets three tools: `switchyard_modules` (list, show, activate, health, and read-only module
actions), `switchyard_audit` (verify, tail) and `switchyard_host`. The model may start only modules you set to
`auto` mode whose required capabilities you granted; a module you keep `manual` is yours to start. Everything else (grants, modes, removal,
deactivation, updates, budgets, settings, acknowledgements) is for you only, and the core refuses it for the
model actor. Module output reaches the model labelled as untrusted data.

These rules apply to the Switchyard tools. A model that also has an unrestricted shell running as your user can
do what your user can, including running `switchyard` itself; use Hermes's own command approval or sandboxing
for that.

## 5. Dashboard

Set `[api] enabled = true` in `config.toml` and restart Hermes. The Hermes dashboard then shows a Switchyard tab
(module status, panels, reports, the inbox). Requests go through Hermes's authenticated dashboard to a loopback
API that accepts a fixed allow-list of read operations plus activate, deactivate and inbox acknowledgements.
The tab uses the plugin's own data directory; its Health column shows each running module's check. No extra
setting is needed for the tab to find the API. Release 1.0.2's tab looked in, and created, `plugin-data/switchyard`
in the Hermes home; that directory is unused and can be deleted.

## 6. Notifications and reports

The `inbox` module collects alerts from the supervisor, meter, scanner, workers and updates modules:

```bash
switchyard module grant inbox --capability core.read
switchyard module grant inbox --capability ui.panel
switchyard module activate inbox                # [daemon]
```

Reports (`--kind` is `health`, `usage`, `security` or `changes`; all need the daemon). When Hermes hosts the
modules, run them in a chat instead: `/switchyard report show --kind health`. In the usage report, a module that
cannot report shows `unavailable: not installed`, `not active` or `action failed`.

```bash
switchyard report show --kind health
switchyard report show --kind security
```

## 7. Updates

Bundled modules update with Switchyard itself (`hermes plugins update switchyard`). Modules you installed
from git under `<data_dir>/modules` are updated by commit:

```bash
switchyard module check_updates                          # [daemon] installed commit vs the head of each channel
switchyard module preview <id> --ref <sha>               # [daemon] files changed, new permissions, notes, digest
switchyard module update <id> --ref <sha> --digest <digest>
switchyard module rollback <id>
```

When Hermes hosts the modules (section 2), `check_updates`, `preview`, `update` and `rollback` are chat-only:
run them as `/switchyard module check_updates` and so on in a Hermes chat. The API inside Hermes does not serve
them, so the command line refuses them there with a message naming `/switchyard`.

Updates run git. Switchyard uses the first git on `PATH` that it can actually run (on Windows with Hermes
Desktop, the packaged copy that comes first on `PATH` cannot be run by other programs, so a Git for Windows
install behind it is used). To choose one, set `[tools] git = "<absolute path>"` in `config.toml`;
`switchyard config show` prints the git in use.

An update that adds capabilities, hosts, secrets or contributions, or weakens isolation, is refused unless you
pass `--accept-wider`. An update to an older version (by the manifest's version number; a pre-release counts as
older than its release) is refused unless you pass `--allow-downgrade`; `module preview` shows `downgrade: true`.
A failed health check rolls the update back.

`module rollback` restores the version that the last update replaced. It refuses when that version's files were
changed after it was set aside, and it runs the health check afterwards: an unhealthy result is printed and the
command exits 1, so check the module before relying on it. The `updates` module checks on a schedule and alerts;
it never installs.

## 8. Audit log

```bash
switchyard audit tail --n 50
switchyard audit verify
```

If verification fails, the failure is recorded and reported until you investigate and run
`switchyard audit ack`. The audit log and its anchor are on your disk: they detect changes, but someone who can
rewrite both files as your user can forge history.

## 9. Uninstall

First note the data directory in use (`data_dir` in the output), since the plugin command goes away with the
plugin:

```bash
hermes -p <profile> switchyard config show
```

Then disable and remove the plugin:

```bash
hermes plugins disable switchyard
hermes plugins remove switchyard                          # also accepted: uninstall; pip route: pip uninstall hermes-switchyard
```

`hermes plugins disable` asks the running gateway to reload its plugins. When it prints `The running gateway
reloaded its plugins and unloaded switchyard`, Switchyard has stopped there: its modules are deactivated
(audit reason `unload`), the loopback API is closed and `api.port` / `api.token` are removed, and the data
directory is free. When it prints that the gateway refused, or that no running gateway answered while one is
running, restart it (`hermes gateway restart`) before removing the plugin. `hermes plugins remove` only deletes
the plugin files; it does not stop anything that is still running.

The data directories are left in place; delete them yourself if you do not need the audit history (audit log,
state, logs, `config.toml`):

- the plugin's data directory in the profile's Hermes home, `plugin-data/agent-plugin-switchyard-<digest>`
  (the `data_dir` you noted; a `data_dir` plugin setting or `SWITCHYARD_DATA_DIR` points it elsewhere);
- `plugin-data/switchyard`, if release 1.0.2's dashboard tab created it (unused since 1.0.3);
- with the pip route, the `switchyard` command's own directory (section 2), unless `SWITCHYARD_DATA_DIR` or
  `--data-dir` pointed it at the same place.

## 10. Running the daemon as a service

Use this only when no Hermes process hosts the data directory: a pip install with a data directory of its own,
or Hermes not running on that machine. Under Hermes the gateway already is the service (section 2).

Run `switchyard api serve` from a service manager that starts it at logon and restarts it if it stops. The
daemon needs no administrator rights; run it as your own user, with the same `SWITCHYARD_DATA_DIR` that your
`switchyard` commands use. After a crash, the next command removes the daemon's stale `api.port` and
`api.token` and reports that no daemon is running.

The Windows recipe was run end to end on Windows 11 (1.1): start, commands through the daemon, a hard kill,
restart, and stop. The systemd and launchd recipes follow each service manager's documented form and have not
yet been run end to end.

Windows (Task Scheduler, as your user, no administrator rights). Replace the program path with the output of
`where switchyard` and the data directory with yours; passing `--data-dir` keeps the task independent of
environment variables:

```powershell
$exe     = "C:\Path\To\switchyard.exe"
$action  = New-ScheduledTaskAction -Execute $exe -Argument '--data-dir "C:\Path\To\data" api serve'
$logon   = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$watch   = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$set     = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName "Switchyard daemon" -Action $action -Trigger @($logon, $watch) -Settings $set
```

Task Scheduler's "restart on failure" setting only retries a task that fails to start; it does not restart a
daemon that stops later. The repeating trigger does: every 5 minutes it starts the task again, and
`IgnoreNew` makes that a no-op while the daemon runs. Task Scheduler does not keep the program's output; if the
task's "Last Run Result" is not 0x41301 (running), run the same command in a terminal to see the error.
Remove the task with `Unregister-ScheduledTask -TaskName "Switchyard daemon"`.

Linux (systemd user unit `~/.config/systemd/user/switchyard.service`, then
`systemctl --user enable --now switchyard`):

```ini
[Unit]
Description=Switchyard daemon

[Service]
ExecStart=%h/.local/bin/switchyard api serve
Restart=on-failure

[Install]
WantedBy=default.target
```

macOS (launchd agent `~/Library/LaunchAgents/com.vicberger.switchyard.plist` with `ProgramArguments` set to the
`switchyard` path, `api`, `serve`, and `RunAtLoad` and `KeepAlive` set to true; load it with
`launchctl load ~/Library/LaunchAgents/com.vicberger.switchyard.plist`).

`systemctl --user stop` and `launchctl unload` send a stop signal, and the daemon shuts down cleanly and removes
its `api.port` and `api.token`. Ending the task in Task Scheduler terminates the process instead; the next
`switchyard` command then removes the stale files.

## 11. Security notes (H3 evaluation)

**H3-26: Challenge context versioning.** The API challenge-response proof uses a static context string (`switchyard-api-v1:`). If the proof format ever changes, the context string will be versioned (e.g., `switchyard-api-v2:`). Clients should not hardcode the context string.

**H3-27: Unix environment variable hardening.** The process broker blocks dangerous environment variables on both Windows and Unix. On Unix, variables like `LD_PRELOAD`, `LD_LIBRARY_PATH`, `DYLD_INSERT_LIBRARIES`, `DYLD_LIBRARY_PATH`, `PYTHONPATH`, `PYTHONHOME`, `JAVA_TOOL_OPTIONS`, and variables with prefixes `LD_`, `DYLD_`, `PYTHON`, `SSH_`, `GPG_`, `PINENTRY_` are refused. See `src/switchyard/process.py` for the complete list.
