# User guide

Signalbox is a Hermes plugin with a small core and modules you switch on one at a time. Nothing a module does is
allowed until you grant it, and everything that changes is written to a hash-chained audit log. Command and
setting details: [REFERENCE.md](REFERENCE.md). Security model and its limits: [DESIGN.md](DESIGN.md) section 4.
Upgrading from release 1.0.x under the plugin's former name: [UPGRADING-1.1.md](UPGRADING-1.1.md).

## 1. Install

Needs Hermes Agent 0.22 or newer and Python 3.11 or newer. Signalbox has no Python dependencies.

```bash
# pin an exact release commit (recommended): see the release page for the SHA of a tag
hermes plugins install vicberger-com/hermes-signalbox --ref <40-character commit SHA>
# or with pip, which also installs the `signalbox` command
pip install "git+https://github.com/vicberger-com/hermes-signalbox@<40-character commit SHA>"
```

**Install by owner/repository and commit.** Signalbox is not in the Hermes plugin catalog, so
`hermes plugins install` needs the repository and a pinned commit. Always pass
`vicberger-com/hermes-signalbox` with `--ref <SHA>`. Because this repository is not in
the catalog, the install prints `Warning: custom (unreviewed) source — not from the Hermes catalog.`; that is
expected.

Releases carry `SHA256SUMS`, a CycloneDX SBOM of what the wheel installs, and a build provenance attestation
(`gh attestation verify <file> -R vicberger-com/hermes-signalbox`). Pin a commit SHA, not a tag name, for
both routes: tags are annotated but not yet signed.

The two routes differ in one way: Hermes 0.23 shows a plugin's dashboard tab only for plugins installed into a
plugins directory, so the Signalbox tab (section 5) needs `hermes plugins install`. A pip install provides the
plugin, the `signalbox` command and the model tools, without the tab; the wheel carries the dashboard files
under `hermes_signalbox/_plugin/` for when Hermes supports that.

Signalbox has no Python dependencies, and its `plugin.yaml` says so (`python_runtime: external`), so
`hermes plugins install` only places the plugin in the profile's plugins directory; Hermes's own environment is
not changed.
If `hermes plugins enable signalbox` asks whether the plugin may replace built-in tools, answer no
(`--no-allow-tool-override`): Signalbox replaces none.

With a plugin install, run the command line through Hermes for the profile, `hermes -p <profile> signalbox
<noun> <verb> ...`; every `signalbox ...` command in this guide works that way. The `signalbox` command itself
comes with the pip route.

## 2. First run

**Which data directory.** Signalbox keeps its state, grants, audit log and `config.toml` in one data directory.
A Hermes session uses the profile's plugin data directory; the `signalbox` command uses a platform default
(`%LOCALAPPDATA%\signalbox`, `~/Library/Application Support/signalbox` or `~/.local/share/signalbox`). These
are **two different stores** unless you point both at one: set `SIGNALBOX_DATA_DIR` (or pass `--data-dir`, which wins over the variable) to
the same absolute path everywhere. `hermes-signalbox config show` prints the directory in use and why it was chosen
(`data_dir_source`).

**Which process hosts modules.** Only one process hosts modules for a data directory: the Hermes gateway (or,
without a gateway, the Hermes process that runs your turns), or `hermes-signalbox api serve`. A one-shot command such
as `hermes gateway status` or `hermes signalbox ...` never becomes the host. If something else holds the
directory when Hermes starts, Hermes takes over within seconds of it letting go (audit record
`core.hosting_acquired`). `hermes-signalbox config show` prints the hosting process (`hosting.pid`). Commands marked `[daemon]` in `signalbox <noun> --help` (activate,
deactivate, health, panel, action, update, preview, rollback, check_updates, report) need that hosting process
with its loopback API. Other commands (list, show, grant, revoke, mode, remove, audit, config) work directly on
the data directory; `remove` only while no other process hosts it. A process that runs turns without hosting writes one `core.not_hosting` audit record.

For the commands in this guide, start the daemon first in its own terminal and leave it running (Ctrl+C stops
it):

```bash
hermes-signalbox api serve              # step 0: hosts the modules and the loopback API
```

Then, in another terminal:

```bash
hermes-signalbox module list            # every module, its status, mode and requested capabilities
hermes-signalbox audit verify           # the audit chain is intact
hermes-signalbox config show            # data directory in use, why, and core settings
```

In a Hermes session the same operations are under `/signalbox`, for example `/signalbox module list`.

Exit codes: 0 success, 1 error or a failed result, 2 usage error (unknown name or invalid value), 3 refused by
policy (capability not granted, or not declared by the module).

**When Hermes hosts the modules** (Hermes Desktop, or any running gateway: it serves every profile and loads the
plugin as soon as it is enabled). The gateway is then the hosting process, so do not start `hermes-signalbox api
serve` for that profile; it reports that another process hosts modules. What works:

| You want to | Do |
|---|---|
| Grant, revoke, set modes, read the audit log, show config | The command line as usual (`hermes -p <profile> signalbox ...`); it works on the data directory. Hermes applies a new mode or a revoke within its next tick (15 s): `disabled` stops a running module, `auto` lets the model start it, a revoked required capability stops the module |
| Remove a module | `/signalbox module remove <id>` in a Hermes chat; the command line refuses while Hermes hosts |
| Start or stop a module, check its health, run any module action | `/signalbox <noun> <verb> ...` in a Hermes chat of that profile, for example `/signalbox module activate router` |
| Use the command line for those too | Set `[api] enabled = true` in `<data_dir>/config.toml` and restart Hermes. The API inside Hermes serves `module activate`, `deactivate`, `health`, `panel` and read-only actions; anything else is refused with a message naming `/signalbox` |
| Apply a changed `config.toml` | Restart Hermes; settings are read when the plugin loads |

Modules in `auto` mode whose grants are complete start whenever Hermes loads the plugin. Module status is kept
per process: `module list` from the command line shows `verified` for a module Hermes is running. The audit log
(`module.activated`) and `/signalbox module health <id>` show the hosting process's view.

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
hermes-signalbox module show router
hermes-signalbox module grant router --capability hermes.hooks
hermes-signalbox module grant router --capability ui.panel
hermes-signalbox module activate router               # [daemon]
hermes-signalbox module health router                 # [daemon]
hermes-signalbox module mode router --mode auto       # start it with every hosting process
```

Grants and start modes are stored in the data directory and survive restarts of Hermes and of the daemon; you
grant once. A `manual` module never starts on its own, even with every grant: start it yourself.

A grant only records consent; it never starts a module. In a running Hermes, a module whose last missing grant
you just gave stays stopped until you start it (`/signalbox module activate <id>` in a chat, or the command
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
asking the model to use them. `/signalbox` commands work at once.

Hermes's model gets three tools: `signalbox_modules` (list, show, activate, health, and read-only module
actions), `signalbox_audit` (verify, tail) and `signalbox_host`. The model may start only modules you set to
`auto` mode whose required capabilities you granted; a module you keep `manual` is yours to start. Everything else (grants, modes, removal,
deactivation, updates, budgets, settings, acknowledgements) is for you only, and the core refuses it for the
model actor. Module output reaches the model labelled as untrusted data.

These rules apply to the Signalbox tools. A model that also has an unrestricted shell running as your user can
do what your user can, including running `signalbox` itself; use Hermes's own command approval or sandboxing
for that.

## 5. Dashboard

Set `[api] enabled = true` in `config.toml` and restart Hermes. The Hermes dashboard then shows a **Signalbox**
tab with three views: Modules, Inbox and Reports. Requests go through Hermes's authenticated dashboard to a
loopback API that serves a fixed list of operations (section "What the page cannot do" below). The tab uses the
plugin's own data directory; no extra setting is needed for it to find the API.

The page opens with a collapsed **What is this page?** introduction, and each view starts with a line saying
what it is for. **Refresh** reloads the view you are on: the button reads "Refreshing…" while it works, and the
time beside it ("Updated 14:02:07") is when the page last loaded.

### Modules

One row per installed module:

| Column | What it shows |
|---|---|
| Module | The module's name and one sentence on what it does |
| State | Running, Ready, Stopped or Error in plain words. Point at it, or move to it with Tab, for the meaning; Esc closes the note |
| Start mode | A selector: **Starts with Hermes**, **Manual start** or **Disabled**. Changing it takes effect at once and is written to the audit log |
| Health | What the module's own check reports while it runs |
| Version, Source | The installed version; "Bundled with Signalbox" or the git commit and channel, with links to the repository and documentation where the module names them |
| Update | The last known update state. The page never contacts the network: it says so when nothing has been checked, and a check needs the `updates` module (section 7) |
| Action | **Start** or **Stop** |

A button that cannot work is disabled, with the reason beside it. A module that still needs permissions lists
them in plain words with the command that grants the first one, ready to copy. If an action is refused anyway,
the row shows "Refused:" and the reason, and keeps it until your next action. A legend under the table explains
every state and start mode; the same words are in the glossary (section 12).

### Inbox

Notices from Signalbox and its modules that need a person: a module failed, a limit was reached, something was
refused. It needs the `inbox` module running (section 6). Each notice shows when it arrived, how serious it is
(a word and a symbol, with the meaning on focus), which module sent it, and its details as labelled fields.
Identical notices are merged into one with a count. Show **Open, Acknowledged or All** with the buttons above the
list; **Acknowledge** marks a notice (or every copy of a merged one) as seen, and the Inbox tab shows how many
are still open. Notices stay on this computer, and the model cannot list or acknowledge them.

### Reports

Choose Health, Usage, Security or Changes. Each report starts with a one-line summary and the question it
answers, then a table: modules with what each still needs, refusals grouped with a count, or changes as
sentences ("Dashboard started router"), with times in your time zone. A broken audit log is announced as an
alert. The stored report is under **Raw data (JSON)** at the bottom, collapsed until you open it. Reports only
read; choosing one changes nothing.

### What the page cannot do

The page can start and stop modules, set their start mode, show reports and acknowledge notices. It cannot
grant or revoke permissions, install, update or remove a module, or change settings: those stay with you at a
terminal or in a Hermes chat, so a web page can never widen what a module may do.

```text
hermes-signalbox module grant inbox --capability core.read      (terminal)
/signalbox module grant id=inbox capability=core.read            (Hermes chat)
```

## 6. Notifications and reports

The `inbox` module collects alerts from the supervisor, meter, scanner, workers and updates modules:

```bash
hermes-signalbox module grant inbox --capability core.read
hermes-signalbox module grant inbox --capability ui.panel
hermes-signalbox module activate inbox                # [daemon]
```

Reports (`--kind` is `health`, `usage`, `security` or `changes`; all need the daemon). When Hermes hosts the
modules, run them in a chat instead: `/signalbox report show kind=health` (a chat takes `key=value`; the
command-line form `--kind health` works there too). In the usage report, a module that
cannot report shows `unavailable: not installed`, `not active` or `action failed`.

```bash
hermes-signalbox report show --kind health
hermes-signalbox report show --kind security
```

## 7. Updates

Bundled modules update with Signalbox itself (`hermes plugins update signalbox`). Modules you installed
from git under `<data_dir>/modules` are updated by commit:

```bash
hermes-signalbox module check_updates                          # [daemon] installed commit vs the head of each channel
hermes-signalbox module preview <id> --ref <sha>               # [daemon] files changed, new permissions, notes, digest
hermes-signalbox module update <id> --ref <sha> --digest <digest>
hermes-signalbox module rollback <id>
```

When Hermes hosts the modules (section 2), `check_updates`, `preview`, `update` and `rollback` are chat-only:
run them as `/signalbox module check_updates` and so on in a Hermes chat. The API inside Hermes does not serve
them, so the command line refuses them there with a message naming `/signalbox`.

Updates run git. Signalbox uses the first git on `PATH` that it can actually run (on Windows with Hermes
Desktop, the packaged copy that comes first on `PATH` cannot be run by other programs, so a Git for Windows
install behind it is used). To choose one, set `[tools] git = "<absolute path>"` in `config.toml`;
`hermes-signalbox config show` prints the git in use.

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
hermes-signalbox audit tail --n 50
hermes-signalbox audit verify
```

If verification fails, the failure is recorded and reported until you investigate and run
`hermes-signalbox audit ack`. The audit log and its anchor are on your disk: they detect changes, but someone who can
rewrite both files as your user can forge history.

## 9. Uninstall

First note the data directory in use (`data_dir` in the output), since the plugin command goes away with the
plugin:

```bash
hermes -p <profile> signalbox config show
```

Then disable and remove the plugin:

```bash
hermes plugins disable signalbox
hermes plugins remove signalbox                          # also accepted: uninstall; pip route: pip uninstall hermes-signalbox
```

`hermes plugins disable` asks the running gateway to reload its plugins. When it prints `The running gateway
reloaded its plugins and unloaded signalbox`, Signalbox has stopped there: its modules are deactivated
(audit reason `unload`), the loopback API is closed and `api.port` / `api.token` are removed, and the data
directory is free. When it prints that the gateway refused, or that no running gateway answered while one is
running, restart it (`hermes gateway restart`) before removing the plugin. `hermes plugins remove` only deletes
the plugin files; it does not stop anything that is still running.

The data directories are left in place; delete them yourself if you do not need the audit history (audit log,
state, logs, `config.toml`):

- the plugin's data directory in the profile's Hermes home, `plugin-data/agent-plugin-signalbox-<digest>`
  (the `data_dir` you noted; a `data_dir` plugin setting or `SIGNALBOX_DATA_DIR` points it elsewhere);
- with the pip route, the `hermes-signalbox` command's own directory (section 2), unless `SIGNALBOX_DATA_DIR`
  or `--data-dir` pointed it at the same place;
- after an upgrade from the plugin's former name, the old data directory that 1.1.0 copied from; see
  [UPGRADING-1.1.md](UPGRADING-1.1.md).

## 10. Running the daemon as a service

Use this only when no Hermes process hosts the data directory: a pip install with a data directory of its own,
or Hermes not running on that machine. Under Hermes the gateway already is the service (section 2).

Run `hermes-signalbox api serve` from a service manager that starts it at logon and restarts it if it stops. The
daemon needs no administrator rights; run it as your own user, with the same `SIGNALBOX_DATA_DIR` that your
`signalbox` commands use. After a crash, the next command removes the daemon's stale `api.port` and
`api.token` and reports that no daemon is running.

The Windows recipe was run end to end on Windows 11 (1.1): start, commands through the daemon, a hard kill,
restart, and stop. The systemd and launchd recipes follow each service manager's documented form and have not
yet been run end to end.

Windows (Task Scheduler, as your user, no administrator rights). Replace the program path with the output of
`where signalbox` and the data directory with yours; passing `--data-dir` keeps the task independent of
environment variables:

```powershell
$exe     = "C:\Path\To\hermes_signalbox.exe"
$action  = New-ScheduledTaskAction -Execute $exe -Argument '--data-dir "C:\Path\To\data" api serve'
$logon   = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$watch   = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$set     = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName "Signalbox daemon" -Action $action -Trigger @($logon, $watch) -Settings $set
```

Task Scheduler's "restart on failure" setting only retries a task that fails to start; it does not restart a
daemon that stops later. The repeating trigger does: every 5 minutes it starts the task again, and
`IgnoreNew` makes that a no-op while the daemon runs. Task Scheduler does not keep the program's output; if the
task's "Last Run Result" is not 0x41301 (running), run the same command in a terminal to see the error.
Remove the task with `Unregister-ScheduledTask -TaskName "Signalbox daemon"`.

Linux (systemd user unit `~/.config/systemd/user/signalbox.service`, then
`systemctl --user enable --now signalbox`):

```ini
[Unit]
Description=Signalbox daemon

[Service]
ExecStart=%h/.local/bin/signalbox api serve
Restart=on-failure

[Install]
WantedBy=default.target
```

macOS (launchd agent `~/Library/LaunchAgents/com.vicberger.signalbox.plist` with `ProgramArguments` set to the
`signalbox` path, `api`, `serve`, and `RunAtLoad` and `KeepAlive` set to true; load it with
`launchctl load ~/Library/LaunchAgents/com.vicberger.signalbox.plist`).

`systemctl --user stop` and `launchctl unload` send a stop signal, and the daemon shuts down cleanly and removes
its `api.port` and `api.token`. Ending the task in Task Scheduler terminates the process instead; the next
`signalbox` command then removes the stale files.

## 11. Security notes (H3 evaluation)

**H3-26: Challenge context versioning.** The API challenge-response proof uses a static context string (`signalbox-api-v1:`). If the proof format ever changes, the context string will be versioned (e.g., `signalbox-api-v2:`). Clients should not hardcode the context string.

**H3-27: Unix environment variable hardening.** The process broker blocks dangerous environment variables on both Windows and Unix. On Unix, variables like `LD_PRELOAD`, `LD_LIBRARY_PATH`, `DYLD_INSERT_LIBRARIES`, `DYLD_LIBRARY_PATH`, `PYTHONPATH`, `PYTHONHOME`, `JAVA_TOOL_OPTIONS`, and variables with prefixes `LD_`, `DYLD_`, `PYTHON`, `SSH_`, `GPG_`, `PINENTRY_` are refused. See `src/hermes_signalbox/process.py` for the complete list.

## 12. Reading the output, and a glossary

Chat replies and command-line output are written for a person: a summary line first, then a table or a short
list with plain labels, then the next step when there is one. For example, `hermes-signalbox module list` on a
new install begins and ends with:

```text
0 of 12 modules running · 0 failed · 12 waiting for permissions

Next step: a module starts once it has every permission it needs. Grant one with hermes-signalbox module grant activation --capability hermes.config.write.
```

In a Hermes chat, `/signalbox module list` gives the same content as Markdown. At a terminal, the rows between
those two lines are a table when the window is wide enough, and one short block per module when it is not.

For scripts, ask for the data instead: `--json` at a terminal, before the noun or at the end of the command
(`hermes-signalbox module list --json`), or `json=true` in a chat (`/signalbox module list json=true`). Both
return the operation's payload unchanged from earlier versions. The model's tools always receive that payload,
never the text for people.

The tables below list every label the program shows, with its internal name (what `--json` and the audit log
contain) and its meaning. They are generated from the program's own label table, so they cannot drift from what
you see.

<!-- glossary:start (generated by tools/gen_glossary.py; do not edit by hand) -->
### Permissions

| Capability | Shown as | Meaning |
|---|---|---|
| `core.read` | Read Signalbox state | See the module list, audit records and reports. It cannot change them. |
| `fs.read` | Read files | Read the files and folders listed in its manifest, and nothing else. |
| `fs.write` | Write files | Create and change files in the folders listed in its manifest. |
| `hermes.config.write` | Change Hermes settings | Edit Hermes configuration; each change is audited and can be rolled back. |
| `hermes.delegation` | Run sub-agents | Hand tasks to Hermes sub-agents and choose which model they use. |
| `hermes.hooks` | Watch and steer Hermes requests | See Hermes events and act before a model call is made. |
| `hermes.output` | Edit Hermes output | Shorten or transform tool output before the model sees it. |
| `hermes.tools` | Add Hermes tools | Offer its own tools to the model. |
| `llm.free` | Use free models | Make model calls on the free pool. No spend. |
| `llm.paid` | Use paid models | Make model calls on paid providers. This can cost money. |
| `net.outbound` | Network access | Connect to the hosts listed in its manifest, and to no others. |
| `notify` | Send alerts | Post notices to the Inbox. |
| `process.spawn` | Run programs | Start the programs listed in its manifest. |
| `schedule` | Run on a timer | Run its jobs on a schedule while Signalbox is hosted. |
| `secrets.read` | Use stored secrets | Use the secrets named in its manifest. Their values are never shown. |
| `ui.panel` | Show a dashboard panel | Add its panel to the Signalbox dashboard tab. |

### Module states

| State | Shown as | Meaning |
|---|---|---|
| `active` | Running | Started and doing its work. |
| `failed` | Error | Could not start or stopped with an error. The error text says why. |
| `stopped` | Stopped | Was running and has been stopped. Start it again to use it. |
| `verified` | Ready | Checked and installed, but not started. |

### Start modes

| Mode | Shown as | Meaning |
|---|---|---|
| `auto` | Starts with Hermes | Starts on its own once every permission it needs is granted. |
| `disabled` | Disabled | Never starts until you change its mode. |
| `manual` | Manual start | Starts only when you start it. |

### Notice severities

| Severity | Shown as | Meaning |
|---|---|---|
| `critical` | Critical | Act now: security or spending is at risk. |
| `high` | High | Act today: a module failed or a limit was reached. |
| `info` | Information | For your records. Nothing to do. |
| `low` | Low | Worth a look when convenient. |
| `medium` | Medium | Look at it soon: something is not working as intended. |

### Who did it

| Actor | Shown as | Meaning |
|---|---|---|
| `api` | Dashboard | A click in the Signalbox dashboard tab. |
| `cli` | CLI | A command typed in a terminal. |
| `core` | Signalbox | Signalbox itself, enforcing a rule or running a scheduled step. |
| `hermes` | The model | The Hermes model, through its Signalbox tools. |
| `hermes-user` | You (chat) | A /signalbox command typed in a Hermes chat. |

### Audit log actions

| Action | Shown as | Meaning |
|---|---|---|
| `api.start_failed` | Local API did not start | The local control API could not start; the detail says why. |
| `audit.acknowledged` | Audit problem acknowledged | An operator confirmed they looked into an audit-log failure. |
| `audit.verify_failed` | Audit check failed | The audit log failed its integrity check. Treat this as tampering until explained. |
| `core.adapter_error` | Hermes adapter error | The link to Hermes hit an error and carried on. |
| `core.hosting_acquired` | Started hosting modules | This process took over running the modules. |
| `core.migrated` | Data copied from Switchyard | A 1.0.x data directory was copied to the new location. |
| `core.not_hosting` | Not hosting modules | Another process runs the modules for this data directory. |
| `core.tick_failed` | Scheduled step failed | A background step failed; the next run retries it. |
| `core.transform_skipped` | Output edit skipped | An output transform was skipped to protect the request. |
| `event.depth_exceeded` | Event loop stopped | Modules triggered each other too deeply; the chain was cut. |
| `event.handler_failed` | Event handler failed | A module failed while handling an event. |
| `fs.read` | File read | A module read a file it is allowed to read. |
| `fs.read_failed` | File read refused | A module tried to read a file and was refused or failed. |
| `hermes.config.rollback` | Hermes setting rolled back | A change to Hermes settings was undone. |
| `hermes.config.write` | Hermes setting changed | A module changed a Hermes setting; a backup was kept. |
| `module.action` | Module command run | A module command was run. |
| `module.activated` | Module started | A module was started. |
| `module.auto_skipped` | Auto-start skipped | A module set to start with Hermes was skipped; it lacks a permission. |
| `module.deactivate_failed` | Module stop failed | A module raised an error while stopping. |
| `module.deactivated` | Module stopped | A module was stopped. |
| `module.delegation_failed` | Sub-agent routing failed | A module failed while routing a sub-agent. |
| `module.delegation_refused` | Sub-agent routing refused | A sub-agent request was refused by a rule. |
| `module.failed` | Module failed | A module could not start or crashed. |
| `module.gate_blocked` | Request blocked | A module blocked a Hermes request by rule. |
| `module.gate_rejected` | Block ignored | A module tried to block a request without the right to. |
| `module.hook_failed` | Hook failed | A module failed while watching a Hermes event. |
| `module.hook_timeout` | Hook too slow | A module took too long on a Hermes event and was skipped. |
| `module.hooks_paused` | Hooks paused | A module's hooks were paused after repeated failures. |
| `module.installed` | Module installed | A module was installed. |
| `module.job_skipped` | Scheduled job skipped | A scheduled job was skipped because the last run was still going. |
| `module.job_timeout` | Scheduled job too slow | A scheduled job ran past its time limit. |
| `module.middleware_rejected` | Request change ignored | A module's change to a request was rejected. |
| `module.mode_changed` | Start mode changed | A module's start mode was changed. |
| `module.notify` | Alert sent | A module posted a notice to the Inbox. |
| `module.rejected` | Module rejected | A module failed verification and was not loaded. |
| `module.reloaded` | Module reloaded | A module's files were read again. |
| `module.removed` | Module removed | A module was uninstalled. |
| `module.rolled_back` | Update rolled back | A module was restored to its previous version. |
| `module.transform_paused` | Output edits paused | A module's output edits were paused after failures. |
| `module.update_check_failed` | Update check failed | Checking a module's update source failed. |
| `module.update_previewed` | Update previewed | An update was staged for review; nothing was applied. |
| `module.update_rejected` | Update refused | An update was refused by a safety check. |
| `module.updated` | Module updated | A module was updated to a new version. |
| `module.verified` | Module verified | A module passed verification. |
| `net.request` | Network request | A module connected to an allowed host. |
| `policy.denied` | Permission refused | Something was refused because a permission is missing. |
| `policy.grant_refused` | Grant refused | A permission could not be granted; the module does not request it. |
| `policy.granted` | Permission granted | A permission was granted to a module. |
| `policy.grants_removed` | Permissions removed | All of a module's permissions were removed. |
| `policy.revoked` | Permission revoked | A permission was taken away from a module. |
| `process.spawned` | Program started | A module started an allowed program. |
| `secret.backend_added` | Secret store added | A secret store was connected. |
| `secret.backend_error` | Secret store error | A secret store returned an error. |
| `secret.backend_removed` | Secret store removed | A secret store was disconnected. |
| `secret.leak_blocked` | Secret leak blocked | A secret value was about to appear in output and was removed. |
| `secret.unavailable` | Secret unavailable | A module asked for a secret that could not be read. |
| `secret.used` | Secret used | A module used a stored secret (name only; the value is never recorded). |
| `trigger.failed` | Trigger failed | A lazy-start trigger failed to start its module. |
<!-- glossary:end -->
